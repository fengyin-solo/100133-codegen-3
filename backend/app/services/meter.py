"""仪表校准业务规则：台账维护、校准登记、到期结论重算都收在这里。

数据分两张表：
- meter：仪表台账（一台仪表一条，以仪表编号为业务键）；
- meter_calibration：校准记录（一台仪表可有多条，同一编号以最近一次为准）。

台账的「最近校准日 / 下次校准日 / 校准时量程」由最近一条校准记录回写，
状态结论统一由 meter_rules.evaluate_meter 计算，列表与详情走同一口径。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services import meter_rules
from app.store import store

MODULE = "meter"
CALIBRATION_MODULE = "meter_calibration"
REQUIRED_FIELDS = ["仪表编号", "仪表名称", "安装位置"]
LIFECYCLE_ACTIONS = {"停用": "停用", "启用": "在用", "报废": "报废"}

# 校准记录保存时允许写入的字段
CALIBRATION_FIELDS = ["仪表编号", "校准日期", "下次校准日", "校准时量程", "校准人员"]


class MeterService:
    # ---- 台账查询 ----------------------------------------------------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for row in rows:
            self._apply_verdict(row)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("仪表编号", ""))]
        if status:
            rows = [row for row in rows if row.get("仪表状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            self._apply_verdict(entry)
        return entry

    def find_by_no(self, meter_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("仪表编号", "")).strip() == meter_no.strip():
                return row
        return None

    # ---- 台账维护 ----------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        meter_no = str(values["仪表编号"]).strip()
        if self.find_by_no(meter_no) is not None:
            return None, [f"仪表编号 {meter_no} 已存在，台账中同一编号只能登记一次"]

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + ["测量参数", "仪表量程"]:
            entry[field] = str(values.get(field) or "").strip() or None
        # 校准日期只能来自校准记录，台账登记时一律留空
        entry["最近校准日"] = None
        entry["下次校准日"] = None
        entry["生命周期状态"] = "在用"
        entry["漂移标记"] = False
        rows.append(entry)
        self._apply_verdict(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """更新台账基础信息；校准日期是判定口径的数据源头，不允许在台账里直接改。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"仪表 {entry_id} 不存在或已归档"]
        protected = {"最近校准日", "下次校准日"} & set(values.keys())
        if protected:
            return None, [
                "校准日期不允许直接修改，请通过「校准登记」新增校准记录，"
                f"系统会以最近一次记录回写{ '、'.join(sorted(protected)) }"
            ]
        for field in ["仪表名称", "安装位置", "测量参数", "仪表量程"]:
            if field in values:
                entry[field] = str(values.get(field) or "").strip() or None
        self._apply_verdict(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"仪表 {entry_id} 不存在或已归档"
        if action not in LIFECYCLE_ACTIONS:
            return None, (
                f"动作「{action}」不属于仪表校准可执行范围，"
                f"可选：{'、'.join(LIFECYCLE_ACTIONS)}"
            )
        target = LIFECYCLE_ACTIONS[action]
        if str(entry.get("生命周期状态") or "在用") == target:
            return None, f"仪表当前已是{target}状态，无需重复{action}"
        entry["生命周期状态"] = target
        self._apply_verdict(entry)
        return entry, f"仪表已{action}"

    def mark_drift(self, entry_id: int, flagged: bool) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"仪表 {entry_id} 不存在或已归档"
        entry["漂移标记"] = flagged
        self._apply_verdict(entry)
        return entry, "已登记漂移预警" if flagged else "漂移预警已解除"

    # ---- 校准记录 ----------------------------------------------------------

    def list_calibrations(self, meter_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(CALIBRATION_MODULE)
        if meter_no:
            rows = [row for row in rows if str(row.get("仪表编号", "")).strip() == meter_no.strip()]
        return sorted(rows, key=self._record_sort_key, reverse=True)

    def latest_calibration(self, meter_no: str) -> dict[str, Any] | None:
        """同一仪表编号出现多次时，以校准日期最近（同日再比记录 id）的一次为准。"""
        matches = [
            row for row in store.rows(CALIBRATION_MODULE)
            if str(row.get("仪表编号", "")).strip() == meter_no.strip()
        ]
        if not matches:
            return None
        return max(matches, key=self._record_sort_key)

    def create_calibration(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        record = {
            field: (str(values.get(field) or "").strip() or None)
            for field in CALIBRATION_FIELDS
        }
        meter_no = record["仪表编号"] or ""
        meter = self.find_by_no(meter_no)

        errors = meter_rules.validate_calibration(record, meter)
        if errors:
            return None, errors

        rows = store.rows(CALIBRATION_MODULE)
        record["id"] = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        rows.append(record)

        # 以最近一次校准记录回写台账，保证台账与校准记录口径一致
        assert meter is not None
        self._sync_from_latest(meter)
        self._apply_verdict(meter)
        return record, []

    # ---- 规则上线后的存量重标 ----------------------------------------------

    def reevaluate_all(self, *, today: date | None = None) -> dict[str, Any]:
        """既有仪表数据按新口径重新标一遍，同时用最近校准记录回写台账日期。"""
        changed: list[dict[str, Any]] = []
        for meter in store.rows(MODULE):
            self._sync_from_latest(meter)
            before = meter.get("仪表状态")
            self._apply_verdict(meter, today=today)
            if before != meter["仪表状态"]:
                changed.append({"仪表编号": meter.get("仪表编号"), "原结论": before, "新结论": meter["仪表状态"]})
        return {"total": len(store.rows(MODULE)), "changed": len(changed), "details": changed}

    # ---- 内部口径 ----------------------------------------------------------

    @staticmethod
    def _record_sort_key(row: dict[str, Any]) -> tuple[date, int]:
        parsed = meter_rules.parse_date(row.get("校准日期"))
        return parsed or date.min, int(row.get("id", 0))

    def _sync_from_latest(self, meter: dict[str, Any]) -> None:
        latest = self.latest_calibration(str(meter.get("仪表编号") or ""))
        if latest is None:
            return
        meter["最近校准日"] = latest.get("校准日期")
        meter["下次校准日"] = latest.get("下次校准日")
        if latest.get("校准时量程"):
            meter["校准时量程"] = latest.get("校准时量程")

    @staticmethod
    def _apply_verdict(meter: dict[str, Any], *, today: date | None = None) -> None:
        result = meter_rules.evaluate_meter(meter, today=today)
        meter["仪表状态"] = result["verdict"]
        meter["距下次校准天数"] = result["remaining_days"]
        meter["到期阈值天数"] = result["threshold_days"]
        meter["判定原因"] = result["reason"]
        # 兼容看板 overview 使用的工作流字段
        meter["status"] = result["verdict"]
        meter["pending"] = result["verdict"] == meter_rules.STATUS_PENDING
        meter["abnormal"] = result["verdict"] in {
            meter_rules.STATUS_PENDING,
            meter_rules.STATUS_DRIFT,
        }
