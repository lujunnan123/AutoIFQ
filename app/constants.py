"""界面使用的固定配置、流程定义与文案。"""

from __future__ import annotations

from dataclasses import dataclass

# ---- 应用与窗口 -----------------------------------------------------------

APP_NAME = "AutoIFQ"
WINDOW_TITLE = "AutoIFQ · 自动询价助手"
APP_VERSION = "AutoIFQ UI · v1.0"

DEFAULT_WINDOW_SIZE = (1200, 800)
MIN_WINDOW_SIZE = (1040, 760)
SIDE_PANEL_WIDTH = 392

# ---- 文件导入 -------------------------------------------------------------

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
FILE_SIZE_HINT = "仅支持 .txt 单个文件 · 不超过 20 MB"
FILE_DIALOG_FILTER = "文本文件 (*.txt);;所有文件 (*)"

# ---- 流程步骤 -------------------------------------------------------------


@dataclass(frozen=True)
class StepSpec:
    name: str
    hint: str
    detail: str


STEPS: tuple[StepSpec, ...] = (
    StepSpec("螃蟹上号", "账号登录与环境初始化", "账号登录 · 环境自检"),
    StepSpec("表格写入", "解析清单并写入表格", "解析清单 · 写入数据表"),
    StepSpec("对话聊天", "按模板与商家沟通询价", "按模板与商家沟通"),
    StepSpec("完成询价", "收集并汇总商家报价", "汇总报价 · 校验结果"),
    StepSpec("填入表格", "将报价结果回填表格", "回填表格 · 保存结果"),
)


class StepStatus:
    """步骤状态（与进度块绘制逻辑对应）。"""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# ---- 运行参数 -------------------------------------------------------------


@dataclass(frozen=True)
class SpinFieldSpec:
    key: str
    label: str
    minimum: float
    maximum: float
    default: float
    suffix: str
    tip: str
    decimals: int = 0
    step: float = 1.0


PARAMETER_FIELDS: tuple[SpinFieldSpec, ...] = (
    SpinFieldSpec(
        "threads", "线程数", 1, 64, 1, " 线程", "同时运行的账号 / 线程数量"
    ),
    SpinFieldSpec(
        "interval_sec", "操作间隔", 0.5, 300.0, 3.0, " 秒",
        "相邻操作之间的等待间隔", decimals=1, step=0.5,
    ),
    SpinFieldSpec(
        "merchant_count", "咨询商家数量", 1, 999, 20, " 家",
        "每个商品需要咨询的商家数量",
    ),
    SpinFieldSpec(
        "timeout_sec", "单次超时", 10, 600, 90, " 秒",
        "单次对话等待回复的最长时间",
    ),
    SpinFieldSpec(
        "retries", "重试次数", 0, 10, 2, " 次", "步骤失败后的自动重试次数"
    ),
)

# ---- 日志 -----------------------------------------------------------------

LOG_LEVEL_COLORS: dict[str, str] = {
    "info": "#9aacc2",
    "success": "#3fe0a4",
    "warn": "#f5c35a",
    "error": "#ff7b8f",
    "accent": "#74adff",
    "muted": "#6b7d93",
}
