"""官方行为库服务：校验名称并交给机器人执行。"""

from __future__ import annotations

from ..domain.entities import BehaviorResult
from ..domain.errors import UnknownBehaviorError
from .ports import RobotPort


class BehaviorService:
    def __init__(self, robot: RobotPort) -> None:
        self._robot = robot

    def list(self) -> list[str]:
        return self._robot.list_behaviors()

    def ensure_exists(self, name: str) -> None:
        name = (name or "").strip()
        if name not in self._robot.list_behaviors():
            raise UnknownBehaviorError(
                f"未知行为：{name}，请先用 list_behaviors 查看可用名称"
            )

    def execute(self, name: str) -> BehaviorResult:
        self.ensure_exists(name)
        return self._robot.run_behavior(name)
