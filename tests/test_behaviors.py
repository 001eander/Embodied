"""官方行为库：名称校验、任务队列与运动锁。"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from embodied.app import create_app
from embodied.domain.errors import UnknownBehaviorError
from embodied.service.behavior import BehaviorService
from embodied.service.config import Settings
from embodied.service.fake_robot import FakeRobot
from embodied.service.qi_robot import _MOTION_SERVICES, QiRobot

BEHAVIOR = "animations/Stand/Gestures/Hey_1"


@pytest.fixture
def app():
    return create_app(Settings(dry_run=True))


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_behavior_manager_shares_motion_lock() -> None:
    assert "ALBehaviorManager" in _MOTION_SERVICES


def test_service_rejects_unknown_behavior() -> None:
    service = BehaviorService(FakeRobot(Settings(dry_run=True)))
    with pytest.raises(UnknownBehaviorError):
        service.ensure_exists("animations/Stand/Gestures/Nope")


async def test_behaviors_list(client) -> None:
    response = await client.get("/api/behaviors")
    assert response.status_code == 200
    assert BEHAVIOR in response.json()["behaviors"]


async def test_behavior_job_flow(client) -> None:
    response = await client.post(f"/api/behaviors/{BEHAVIOR}", json={"wait": False})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    for _ in range(50):
        job = (await client.get(f"/api/jobs/{job_id}")).json()
        if job["status"] in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert job["status"] == "done"
    assert job["kind"] == "behavior"
    assert job["result"]["name"] == BEHAVIOR


async def test_behavior_wait(client) -> None:
    response = await client.post(f"/api/behaviors/{BEHAVIOR}", json={"wait": True})
    assert response.status_code == 202
    assert response.json()["name"] == BEHAVIOR


async def test_behavior_unknown(client) -> None:
    response = await client.post("/api/behaviors/animations/Nope", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_behavior"


class _PollingRobot(QiRobot):
    def __init__(self, running: list[bool]) -> None:
        super().__init__(Settings(dry_run=True))
        self._running = running
        self.calls: list[tuple[str, str, tuple]] = []

    def _invoke(self, service: str, method: str, args: tuple = ()):
        self.calls.append((service, method, tuple(args)))
        if method == "isBehaviorRunning":
            return self._running.pop(0)
        return ["animations/Stand/Gestures/Hey_1"] if method == "getInstalledBehaviors" else None


def test_run_behavior_polls_until_finished() -> None:
    robot = _PollingRobot([True, True, False, False])
    result = robot.run_behavior(BEHAVIOR)

    polls = [call for call in robot.calls if call[1] == "isBehaviorRunning"]
    assert len(polls) == 4
    assert result.name == BEHAVIOR
    assert robot._motion_lock.acquire(timeout=0.1)
    robot._motion_lock.release()


def test_run_behavior_holds_motion_lock() -> None:
    robot = _PollingRobot([True, False, False])
    seen: list[bool] = []
    original = robot._invoke

    def _invoke(service: str, method: str, args: tuple = ()):
        if method == "isBehaviorRunning":
            seen.append(robot._motion_lock._is_owned())
        return original(service, method, args)

    robot._invoke = _invoke  # type: ignore[method-assign]
    robot.run_behavior(BEHAVIOR)
    assert seen and all(seen)
