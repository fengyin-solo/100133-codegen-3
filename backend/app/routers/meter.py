"""仪表校准接口：维护仪表台账，覆盖校准登记、到期重标、停用报废等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.meter import MeterService

router = APIRouter(prefix="/api/meter", tags=["仪表校准"])

service = MeterService()

LIST_FIELDS = ["仪表编号", "仪表名称", "安装位置", "测量参数", "仪表量程", "最近校准日", "下次校准日", "量程核验", "剩余天数", "预警阈值", "仪表状态", "判定结论"]
STATUSES = ["正常", "漂移预警", "待校准", "已停用", "已报废"]
ACTIONS = ["校准登记", "漂移预警", "停用仪表", "报废仪表", "启用仪表"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出仪表校准清单：按现行口径标注后的全量台账。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "meter", "total": total, "items": items}


@router.post("/recalculate", response_model=ActionResult)
def recalculate_entries() -> ActionResult:
    """按现行判定口径重标全部既有仪表；规则调整后调用一次即可。"""
    summary = service.recalculate()
    return ActionResult(
        ok=True,
        message=f"已按新口径重标 {summary['total']} 台仪表：待校准 {summary['待校准']} 台、异常 {summary['异常']} 台",
        entry=summary,
    )


@router.get("/stats")
def stats() -> dict[str, Any]:
    """按现行口径汇总各状态仪表数量，供台账顶部卡片使用。"""
    return service.summary()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按仪表编号检索"),
    status: str | None = Query(default=None, description="正常、漂移预警、待校准、已停用、已报废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按仪表编号与状态过滤仪表校准列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一台仪表；违反校准口径（时间线矛盾、量程不符在用）会被拦下并说明原因。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单台仪表详情；判定结论与台账列表同口径。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"仪表 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/calibrations")
def list_calibrations(entry_id: int) -> dict[str, Any]:
    """列出该仪表的全部校准记录，并标出当前判定采用的一条。"""
    result = service.calibrations_for(entry_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"仪表 {entry_id} 不存在或已归档")
    return result


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单台仪表执行校准登记、漂移预警、停用报废等动作；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
