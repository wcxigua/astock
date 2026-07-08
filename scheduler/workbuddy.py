from typing import Callable, Optional, Dict, Any
from datetime import datetime, time
from utils.logger import get_logger


class WorkBuddyInterface:
    def __init__(self):
        self.logger = get_logger("WorkBuddy")
        self._tasks: Dict[str, dict] = {}
        self.logger.info("WorkBuddy 定时值守接口已初始化")
        self.logger.info("预留任务槽位: [盘中盯盘] [定时复盘] [信号推送]")

    def register_task(self, name: str, task_func: Callable, schedule: str, enabled: bool = True):
        self._tasks[name] = {
            "func": task_func,
            "schedule": schedule,
            "enabled": enabled,
            "created_at": datetime.now(),
        }
        self.logger.info(f"任务已注册: {name} | 调度: {schedule} | 启用: {enabled}")

    def unregister_task(self, name: str):
        self._tasks.pop(name, None)
        self.logger.info(f"任务已移除: {name}")

    def get_all_tasks(self) -> dict:
        return self._tasks

    def enable_task(self, name: str):
        if name in self._tasks:
            self._tasks[name]["enabled"] = True
            self.logger.info(f"任务已启用: {name}")

    def disable_task(self, name: str):
        if name in self._tasks:
            self._tasks[name]["enabled"] = False
            self.logger.info(f"任务已禁用: {name}")

    def run_task(self, name: str, **kwargs) -> Optional[Any]:
        task = self._tasks.get(name)
        if not task:
            self.logger.error(f"任务不存在: {name}")
            return None
        if not task["enabled"]:
            self.logger.warning(f"任务已禁用: {name}")
            return None
        try:
            result = task["func"](**kwargs)
            self.logger.info(f"任务执行成功: {name}")
            return result
        except Exception as e:
            self.logger.error(f"任务执行失败 [{name}]: {e}")
            return None
