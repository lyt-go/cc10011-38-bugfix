"""聚合配置接口：维护聚合规则，覆盖提交规则评审、生效规则、废弃规则等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.aggregate import AggregateService

router = APIRouter(prefix="/api/aggregate", tags=["聚合配置"])

service = AggregateService()

LIST_FIELDS = ["规则编号", "源数据粒度", "目标粒度", "聚合函数集", "数据偏移分钟", "补全策略", "空值处理", "输出数据集"]
STATUSES = ["草稿", "规则评审中", "已生效", "已废弃"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    dataset: str | None = Query(default=None, description="按输出数据集检索"),
    status: str | None = Query(default=None, description="草稿、规则评审中、已生效、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号、输出数据集与状态过滤聚合配置列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, dataset=dataset, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条聚合规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"聚合规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条聚合规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="聚合规则已登记", entry=entry)


@router.post("/{entry_id}/refresh", response_model=ActionResult)
def refresh_dataset(entry_id: int, payload: EntryPayload) -> ActionResult:
    """聚合数据集更新：落库最新维度指标并联动重算数据质量总分。"""
    entry, message, recomputed = service.refresh_dataset(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    entry = dict(entry)
    entry["重算结果"] = recomputed
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条聚合规则执行提交规则评审、生效规则、废弃规则；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出聚合配置清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "aggregate", "total": total, "items": items}
