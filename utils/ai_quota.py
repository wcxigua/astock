from datetime import date
from utils.logger import get_logger

logger = get_logger("AIQuota")


class AIQuota:
    MAX_DAILY = 3

    def __init__(self):
        self._today: date | None = None
        self._count = 0

    def _reset_if_new_day(self):
        today = date.today()
        if self._today != today:
            self._today = today
            self._count = 0
            logger.info(f"AI调用额度已重置（新交易日 {today}）")

    def can_call(self) -> bool:
        self._reset_if_new_day()
        return self._count < self.MAX_DAILY

    def record_call(self):
        self._count += 1
        remaining = self.MAX_DAILY - self._count
        logger.info(f"AI调用已记录（今日第 {self._count} 次，剩余 {remaining} 次）")

    def remaining(self) -> int:
        self._reset_if_new_day()
        return max(0, self.MAX_DAILY - self._count)


ai_quota = AIQuota()
