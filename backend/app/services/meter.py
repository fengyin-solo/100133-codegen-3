"""仪表校准业务规则：到期判定、保存校验与状态流转都收在这里。

判定口径（列表、详情、导出共用 evaluate 一套逻辑，保证台账与详情结论一致）：
- 在用仪表的下次校准日距今天不足阈值时自动标为「待校准」，阈值默认 30 天、按安装位置区分；
- 已停用、已报废的仪表不参与到期判定，状态保持原样；
- 同一仪表编号出现多条校准记录时，以校准日期最近的一条为准（并列取登记 id 较大者）；
- 最近校准日晚于下次校准日、量程核验不符仍在用的数据，保存时直接拦下并说明原因。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "meter"
CALIBRATION_MODULE = "_meter_calibration"

REQUIRED_FIELDS = ["仪表编号", "仪表名称", "安装位置"]
LEDGER_FIELDS = ["仪表编号", "仪表名称", "安装位置", "测量参数", "仪表量程"]

STATUS_ORDER = ["正常", "漂移预警", "待校准", "已停用", "已报废"]
EXEMPT_STATUSES = {"已停用", "已报废"}
RANGE_RESULTS = {"符合", "不符"}

# 到期预警阈值：默认 30 天，按安装位置加严或放宽；位置含关键词即命中
DEFAULT_THRESHOLD_DAYS = 30
THRESHOLD_DAYS_BY_LOCATION = {
    "出水口": 45,
    "排放口": 45,
    "进水口": 30,
    "化验室": 15,
}

ACTION_RULES = {
    "校准登记": "正常",
    "漂移预警": "漂移预警",
    "停用仪表": "已停用",
    "报废仪表": "已报废",
    "启用仪表": "正常",
}


def parse_date(value: Any) -> date | None:
    """把 YYYY-MM-DD 字符串解析成日期；非法或为空时返回 None。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def threshold_for(location: str) -> int:
    """按安装位置取预警阈值；没有命中关键词时用默认 30 天。"""
    for keyword, days in THRESHOLD_DAYS_BY_LOCATION.items():
        if keyword in location:
            return days
    return DEFAULT_THRESHOLD_DAYS


def latest_calibration(meter_code: str) -> dict[str, Any] | None:
    """取该仪表编号最近一条校准记录：校准日期最新者优先，并列取登记 id 较大者。"""
    records = [row for row in store.rows(CALIBRATION_MODULE) if row.get("仪表编号") == meter_code]
    if not records:
        return None
    return max(records, key=lambda row: (parse_date(row.get("校准日期")) or date.min, int(row.get("id", 0))))


def evaluate(entry: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """按统一口径给一条仪表台账算出展示结论：状态、剩余天数、阈值与判定说明。"""
    today = today or date.today()
    base_status = str(entry.get("status") or STATUS_ORDER[0])
    record = latest_calibration(str(entry.get("仪表编号") or ""))
    source = record if record is not None else entry
    raw_last = source.get("校准日期") if record is not None else source.get("最近校准日")
    raw_next = source.get("下次校准日")
    last_day = parse_date(raw_last)
    next_day = parse_date(raw_next)
    range_check = str(source.get("量程核验") or "符合").strip() or "符合"
    location = str(entry.get("安装位置") or "")
    threshold = threshold_for(location)
    remaining = (next_day - today).days if next_day is not None else None

    issues: list[str] = []
    exempt = base_status in EXEMPT_STATUSES
    if exempt:
        derived = base_status
        conclusion = f"{base_status}仪表不参与到期判定"
        remaining = None
    else:
        if range_check == "不符":
            issues.append("量程核验不符，仪表不得继续在用，请停用或报废")
        if remaining is None:
            derived = "待校准"
            issues.append("缺少有效的下次校准日，无法判定到期，按待校准处理")
        elif remaining < 0:
            derived = "待校准"
            issues.append(f"已超过下次校准日 {-remaining} 天，须立即安排校准")
        elif remaining < threshold:
            derived = "待校准"
            issues.append(f"距下次校准日 {remaining} 天，低于「{location or '未填位置'}」{threshold} 天阈值")
        elif base_status == "漂移预警":
            derived = "漂移预警"
        else:
            derived = "正常"
        if issues:
            conclusion = "；".join(issues)
        elif derived == "漂移预警":
            conclusion = "人工标记漂移预警，请跟踪复核"
        else:
            conclusion = "校准在有效期内，状态正常"

    abnormal = not exempt and (range_check == "不符" or remaining is None or remaining < 0)
    view = dict(entry)
    view.update({
        "最近校准日": last_day.isoformat() if last_day else (str(raw_last) if raw_last else ""),
        "下次校准日": next_day.isoformat() if next_day else (str(raw_next) if raw_next else ""),
        "量程核验": range_check,
        "剩余天数": remaining,
        "预警阈值": threshold,
        "仪表状态": derived,
        "判定结论": conclusion,
        "pending": derived in ("待校准", "漂移预警"),
        "abnormal": abnormal,
    })
    return view


def validate_calibration(values: dict[str, Any], *, in_use: bool) -> str | None:
    """保存前校验：日期格式、校准时间线、量程核验结论；返回 None 表示通过。"""
    for field in ("最近校准日", "校准日期", "下次校准日"):
        raw = values.get(field)
        if raw not in (None, "") and parse_date(raw) is None:
            return f"{field}「{raw}」不是有效日期，请按 YYYY-MM-DD 填写"
    last_day = parse_date(values.get("最近校准日") or values.get("校准日期"))
    next_day = parse_date(values.get("下次校准日"))
    if last_day and next_day and last_day > next_day:
        return (
            f"最近校准日 {last_day.isoformat()} 晚于下次校准日 {next_day.isoformat()}，"
            "校准时间线矛盾，数据未保存"
        )
    range_check = str(values.get("量程核验") or "").strip()
    if range_check and range_check not in RANGE_RESULTS:
        return "量程核验只能填「符合」或「不符」"
    if in_use and range_check == "不符":
        return "量程核验不符的仪表不得继续在用，请先停用或报废，数据未保存"
    return None


class MeterService:
    def __init__(self) -> None:
        # 规则随服务上线：既有仪表数据先按新口径重标一遍
        self.recalculate()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        today: date | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        views = [evaluate(row, today) for row in store.rows(MODULE)]
        if keyword:
            views = [view for view in views if keyword in str(view.get("仪表编号", ""))]
        if status:
            views = [view for view in views if view.get("仪表状态") == status]
        total = len(views)
        start = max(page - 1, 0) * size
        return views[start:start + size], total

    def get_entry(self, entry_id: int, today: date | None = None) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return evaluate(entry, today) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values.get("仪表编号") or "").strip()
        if any(str(row.get("仪表编号")) == code for row in store.rows(MODULE)):
            return None, f"仪表编号 {code} 已存在，同一编号只建一本台账"
        error = validate_calibration(values, in_use=True)
        if error:
            return None, error
        last_day = parse_date(values.get("最近校准日"))
        next_day = parse_date(values.get("下次校准日"))
        if (last_day is None) != (next_day is None):
            return None, "登记首次校准需同时填写最近校准日与下次校准日"
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field) or "").strip() for field in LEDGER_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        rows.append(entry)
        if next_day is not None and last_day is not None:
            # 首次校准信息进校准记录，台账日期一律以校准记录为准
            self._append_calibration(
                code,
                last_day,
                next_day,
                str(values.get("量程核验") or "符合").strip(),
                values.get("登记人"),
            )
        self.recalculate()
        return self.get_entry(int(entry["id"])), f"仪表 {code} 已登记"

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"仪表 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于仪表校准可执行范围"
        base = str(entry.get("status") or STATUS_ORDER[0])
        code = str(entry.get("仪表编号") or "")
        if action == "校准登记":
            if base == "已报废":
                return None, "仪表已报废，不再安排校准"
            error = validate_calibration(values, in_use=base not in EXEMPT_STATUSES)
            if error:
                return None, error
            next_day = parse_date(values.get("下次校准日"))
            if next_day is None:
                return None, "校准登记必须填写有效的下次校准日（YYYY-MM-DD）"
            calibrated_on = parse_date(values.get("校准日期")) or date.today()
            self._append_calibration(
                code,
                calibrated_on,
                next_day,
                str(values.get("量程核验") or "符合").strip(),
                values.get("登记人"),
            )
            entry["status"] = STATUS_ORDER[0]
            message = f"校准记录已登记，{code} 以最近一条校准记录为准"
        elif action == "启用仪表":
            if base not in EXEMPT_STATUSES:
                return None, "仅已停用或已报废的仪表需要启用"
            entry["status"] = STATUS_ORDER[0]
            message = f"仪表 {code} 已启用，重新参与到期判定"
        else:
            if base in EXEMPT_STATUSES and action == "漂移预警":
                return None, f"仪表{base}，无需再标漂移预警"
            entry["status"] = ACTION_RULES[action]
            message = f"仪表 {code} 已{action}"
        self.recalculate()
        return self.get_entry(entry_id), message

    def calibrations_for(self, entry_id: int) -> dict[str, Any] | None:
        """列出该仪表的全部校准记录，并标出当前判定采用的一条。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        code = str(entry.get("仪表编号") or "")
        latest = latest_calibration(code)
        records = [row for row in store.rows(CALIBRATION_MODULE) if row.get("仪表编号") == code]
        records.sort(key=lambda row: (parse_date(row.get("校准日期")) or date.min, int(row.get("id", 0))), reverse=True)
        items = [dict(row, 是否采用=row is latest) for row in records]
        return {
            "仪表编号": code,
            "判定口径": "同一仪表编号出现多条校准记录时，以校准日期最近的一条为准",
            "items": items,
        }

    def summary(self, today: date | None = None) -> dict[str, Any]:
        views = [evaluate(row, today) for row in store.rows(MODULE)]
        counts = {status: 0 for status in STATUS_ORDER}
        abnormal = 0
        for view in views:
            counts[view["仪表状态"]] = counts.get(view["仪表状态"], 0) + 1
            if view["abnormal"]:
                abnormal += 1
        return {"total": len(views), "异常": abnormal, **counts}

    def recalculate(self, today: date | None = None) -> dict[str, Any]:
        """按现行口径重标全部既有仪表：把派生状态与标记写回台账，供看板统计。"""
        for row in store.rows(MODULE):
            view = evaluate(row, today)
            row["仪表状态"] = view["仪表状态"]
            row["pending"] = view["pending"]
            row["abnormal"] = view["abnormal"]
        return self.summary(today)

    def _append_calibration(
        self,
        code: str,
        calibrated_on: date,
        next_day: date,
        range_check: str,
        operator: Any,
    ) -> None:
        rows = store.rows(CALIBRATION_MODULE)
        rows.append({
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "仪表编号": code,
            "校准日期": calibrated_on.isoformat(),
            "下次校准日": next_day.isoformat(),
            "量程核验": range_check if range_check in RANGE_RESULTS else "符合",
            "登记人": str(operator or "").strip() or "未登记",
        })
