"""仪表校准接口：台账维护、校准登记、阈值配置与存量重标。

所有校准结论由后端统一规则计算后返回，前端只负责展示，
保证台账列表与仪表详情给出的结论一致。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import meter_rules
from app.services.meter import CALIBRATION_FIELDS, MeterService

router = APIRouter(prefix="/api/meter", tags=["仪表校准"])

service = MeterService()

LIST_FIELDS = ["仪表编号", "仪表名称", "安装位置", "测量参数", "仪表量程", "最近校准日", "下次校准日", "仪表状态"]
STATUSES = meter_rules.VERDICTS


@router.get("/thresholds")
def get_thresholds() -> dict[str, Any]:
    """查看各安装位置的到期阈值配置。"""
    return {
        "默认阈值天数": meter_rules.DEFAULT_THRESHOLD_DAYS,
        "安装位置阈值": dict(meter_rules.LOCATION_THRESHOLDS),
    }


@router.put("/thresholds", response_model=ActionResult)
def update_thresholds(payload: EntryPayload) -> ActionResult:
    """调整指定安装位置的到期阈值（天）；改完立即按新阈值重标全部仪表。"""
    location = str(payload.values.get("安装位置") or "").strip()
    raw_days = payload.values.get("阈值天数")
    if not location:
        return ActionResult(ok=False, message="安装位置不能为空")
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return ActionResult(ok=False, message=f"阈值天数必须是整数，收到的是「{raw_days}」")
    if days <= 0:
        return ActionResult(ok=False, message="阈值天数必须大于 0")
    meter_rules.LOCATION_THRESHOLDS[location] = days
    report = service.reevaluate_all()
    return ActionResult(ok=True, message=f"{location}阈值已调整为 {days} 天，存量仪表已重标", entry=report)


@router.post("/reevaluate", response_model=ActionResult)
def reevaluate_all() -> ActionResult:
    """规则上线/数据修正后，按当前口径把既有仪表全部重新标一遍。"""
    report = service.reevaluate_all()
    return ActionResult(
        ok=True,
        message=f"已按新口径重标 {report['total']} 台仪表，其中 {report['changed']} 台结论发生变化",
        entry=report,
    )


@router.get("/calibrations")
def list_calibrations(
    meter_no: str | None = Query(default=None, description="按仪表编号过滤校准记录"),
) -> dict[str, Any]:
    """校准记录列表；同一仪表编号有多条时按校准日期倒序，最近一次排最前。"""
    items = service.list_calibrations(meter_no)
    return {"total": len(items), "items": items, "fields": CALIBRATION_FIELDS}


@router.post("/calibrations", response_model=ActionResult)
def create_calibration(payload: EntryPayload) -> ActionResult:
    """登记一条校准记录。

    最近校准日晚于下次校准日、或量程不符且仪表仍在用时，直接拦下并说明原因；
    保存成功后以最近一次记录回写台账日期并重算结论。
    """
    record, errors = service.create_calibration(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    meter = service.find_by_no(str(record["仪表编号"]))
    return ActionResult(ok=True, message="校准记录已保存，台账已按最近一次校准更新", entry={"校准记录": record, "仪表": meter})


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按仪表编号检索"),
    status: str | None = Query(default=None, description="正常、漂移预警、待校准、停用中、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按仪表编号与结论过滤仪表台账；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出仪表校准清单：返回当前台账的全量数据与统一结论。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "meter", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条仪表明细；不存在时给出可读的错误说明，结论与台账列表同口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"仪表 {entry_id} 不存在或已归档")
    meter_no = str(entry.get("仪表编号") or "")
    calibrations = service.list_calibrations(meter_no)
    entry["校准记录"] = calibrations
    entry["最近校准记录"] = calibrations[0] if calibrations else None
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一台仪表，缺字段或编号重复时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="仪表已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改台账基础信息；校准日期只能通过校准登记写入，直接改会被拦下。"""
    entry, errors = service.update_entry(entry_id, payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="仪表信息已更新", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单台仪表执行停用、启用、报废；停用/报废后不再参与到期判定。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/drift", response_model=ActionResult)
def mark_drift(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记/解除漂移预警；到期判定优先，未到期时结论展示为漂移预警。"""
    flagged = bool(payload.values.get("flagged", True))
    entry, message = service.mark_drift(entry_id, flagged)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
