"""飞书询价数据的本地筛选：文本、数字、日期、选项与图片。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .excel_table import REQUIRED_COLUMNS
from .feishu_table import FeishuRecord

FIELD_TYPES: dict[str, str] = {
    "账号": "text",
    "账号内容": "text",
    "收购日期": "date",
    "可不可二次": "choice",
    "成本": "number",
    "拉群前报价": "number",
    "上架情况": "choice",
    "账号内容图片": "image",
}

FIELD_OPERATORS: dict[str, tuple[str, ...]] = {
    "text": (
        "contains",
        "not_contains",
        "equals",
        "not_equals",
        "empty",
        "not_empty",
    ),
    "number": (
        "eq",
        "neq",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
        "empty",
        "not_empty",
    ),
    "date": ("on", "before", "after", "between", "empty", "not_empty"),
    "choice": ("is", "is_not", "empty", "not_empty"),
    "image": ("has_image", "no_image"),
}

OPERATOR_LABELS: dict[str, str] = {
    "contains": "包含",
    "not_contains": "不包含",
    "equals": "等于",
    "not_equals": "不等于",
    "empty": "为空",
    "not_empty": "不为空",
    "eq": "等于",
    "neq": "不等于",
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
    "between": "介于",
    "on": "等于",
    "before": "早于",
    "after": "晚于",
    "is": "等于",
    "is_not": "不等于",
    "has_image": "有图片",
    "no_image": "无图片",
}

_EMPTY_OPERATORS = {"empty", "not_empty", "has_image", "no_image"}


@dataclass(frozen=True)
class FilterCondition:
    field: str
    operator: str
    value: Any = None
    value2: Any = None

    @property
    def field_type(self) -> str:
        return FIELD_TYPES.get(self.field, "text")


@dataclass(frozen=True)
class FilterGroup:
    joiner: str = "AND"
    conditions: tuple[FilterCondition, ...] = ()

    def matches(self, record: FeishuRecord) -> bool:
        if not self.conditions:
            return True
        checks = [
            _matches_condition(record, condition)
            for condition in self.conditions
        ]
        if self.joiner.upper() == "OR":
            return any(checks)
        return all(checks)


def filter_records(
    records: Iterable[FeishuRecord],
    group: FilterGroup,
) -> list[int]:
    """返回满足条件的记录下标。"""
    return [
        index
        for index, record in enumerate(records)
        if group.matches(record)
    ]


def _field_value(record: FeishuRecord, field: str) -> object:
    if field == "账号内容图片":
        return record.has_images or bool(record.screenshots)
    if field == "上架情况":
        return record.listing_status
    try:
        index = REQUIRED_COLUMNS.index(field)
    except ValueError:
        return None
    if index >= len(record.values):
        return None
    return record.values[index]


def _matches_condition(
    record: FeishuRecord,
    condition: FilterCondition,
) -> bool:
    field_type = condition.field_type
    raw = _field_value(record, condition.field)
    operator = condition.operator

    if field_type == "image":
        has_image = bool(raw)
        return has_image if operator == "has_image" else not has_image

    if field_type == "date":
        current = _as_date(raw)
        if operator == "empty":
            return current is None
        if operator == "not_empty":
            return current is not None
        target = _as_date(condition.value)
        target2 = _as_date(condition.value2)
        if current is None:
            return False
        if operator == "on":
            return target is not None and current == target
        if operator == "before":
            return target is not None and current < target
        if operator == "after":
            return target is not None and current > target
        if operator == "between":
            if target is None and target2 is None:
                return True
            if target is not None and current < target:
                return False
            if target2 is not None and current > target2:
                return False
            return True
        return False

    if field_type == "number":
        current = _as_number(raw)
        if operator == "empty":
            return current is None
        if operator == "not_empty":
            return current is not None
        target = _as_number(condition.value)
        target2 = _as_number(condition.value2)
        if current is None:
            return False
        if operator == "eq":
            return target is not None and _num_equal(current, target)
        if operator == "neq":
            return target is None or not _num_equal(current, target)
        if operator == "gt":
            return target is not None and current > target
        if operator == "gte":
            return target is not None and current >= target
        if operator == "lt":
            return target is not None and current < target
        if operator == "lte":
            return target is not None and current <= target
        if operator == "between":
            if target is None and target2 is None:
                return True
            if target is not None and current < target:
                return False
            if target2 is not None and current > target2:
                return False
            return True
        return False

    # text / choice
    current = "" if raw is None else str(raw).strip()
    if operator == "empty":
        return not current
    if operator == "not_empty":
        return bool(current)
    target = "" if condition.value is None else str(condition.value).strip()
    if field_type == "choice":
        if operator == "is":
            return current == target
        if operator == "is_not":
            return current != target
        return False

    lowered = current.lower()
    target_lower = target.lower()
    if operator == "contains":
        return target_lower in lowered
    if operator == "not_contains":
        return target_lower not in lowered
    if operator == "equals":
        return lowered == target_lower
    if operator == "not_equals":
        return lowered != target_lower
    return False


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = (
        str(value)
        .strip()
        .replace(",", "")
        .replace("，", "")
        .replace("¥", "")
        .replace("￥", "")
    )
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _num_equal(left: float, right: float) -> bool:
    return abs(left - right) < 1e-9


def field_operators(field: str) -> tuple[str, ...]:
    return FIELD_OPERATORS.get(FIELD_TYPES.get(field, "text"), ())


def is_empty_operator(operator: str) -> bool:
    return operator in _EMPTY_OPERATORS


def condition_to_text(condition: FilterCondition) -> str:
    label = OPERATOR_LABELS.get(condition.operator, condition.operator)
    if is_empty_operator(condition.operator):
        return f"{condition.field} {label}"
    if condition.operator == "between":
        return (
            f"{condition.field} {label} "
            f"{_value_text(condition.value)} ~ "
            f"{_value_text(condition.value2)}"
        )
    return f"{condition.field} {label} {_value_text(condition.value)}"


def _value_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)
