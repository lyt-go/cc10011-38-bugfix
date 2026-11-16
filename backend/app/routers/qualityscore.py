"""数据质量分接口：评分规则维护、评分快照生成与查询、服务发布门禁视图。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.qualityscore import QualityscoreService

router = APIRouter(prefix="/api/qualityscore", tags=["数据质量分"])

service = QualityscoreService()

LIST_FIELDS = [
    "规则编号", "数据集名称",
    "完整性权重", "准确性权重", "时效性权重", "一致性权重",
    "准入门槛", "评分周期", "规则版本",
    "完整性得分", "准确性得分", "时效性得分", "一致性得分", "总分数",
    "最近快照编号", "最近评分时间",
]
STATUSES = ["草稿", "规则评审中", "已启用", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    dataset: str | None = Query(default=None, description="按数据集名称检索"),
    status: str | None = Query(default=None, description="草稿、规则评审中、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号、数据集与状态过滤数据质量分列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, dataset=dataset, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/snapshots", response_model=PageResult[dict])
def list_snapshots(
    rule_code: str | None = Query(default=None, description="按规则编号过滤快照"),
    period: str | None = Query(default=None, description="按评分周期过滤快照"),
    status: str | None = Query(default=None, description="有效、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """评分快照清单：维度得分、权重、规则版本与评分周期都可追溯。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_snapshots(rule_code=rule_code, period=period, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/snapshots", response_model=ActionResult)
def create_snapshot(payload: EntryPayload) -> ActionResult:
    """生成数据质量评分快照：依赖未完成、版本/周期冲突或重复提交都会被拦下。"""
    snapshot, message = service.generate_snapshot(payload.values)
    if snapshot is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=snapshot)


@router.get("/snapshots/{snapshot_id}", response_model=dict)
def get_snapshot(snapshot_id: int) -> dict:
    """读取单张快照明细，核对冻结的权重、维度得分与评分周期。"""
    snapshot = service.get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"评分快照 {snapshot_id} 不存在")
    return snapshot


@router.get("/gate/{dataset_name}", response_model=dict)
def get_gate(dataset_name: str) -> dict:
    """服务详情联动入口：返回该数据集当前的质量门禁判定与维度得分核对视图。"""
    return service.describe_gate(dataset_name)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据质量分清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "qualityscore", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条评分规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"评分规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条评分规则；四项权重与准入门槛都做数值口径校验，缺字段不静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message="；".join(missing))
    return ActionResult(ok=True, message="评分规则已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """编辑评分规则：权重/门槛/数据集/周期变化会递增规则版本并作废旧快照。"""
    entry, errors = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="评分规则已保存，规则版本与快照口径已同步", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条评分规则执行提交规则评审、启用规则、停用规则；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
