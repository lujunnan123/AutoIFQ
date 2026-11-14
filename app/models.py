"""运行状态与参数数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"


@dataclass(frozen=True)
class RunParams:
    """一次询价任务的全部运行参数。"""

    threads: int
    interval_sec: float
    merchant_count: int
    timeout_sec: int
    retries: int
    phrases: tuple[str, ...]

    def summary(self) -> str:
        return (
            f"线程 {self.threads} · 间隔 {self.interval_sec:.1f}s · "
            f"目标商家 {self.merchant_count} 家 · 超时 {self.timeout_sec}s · "
            f"重试 {self.retries} 次 · 询问话术 {len(self.phrases)} 条"
        )
