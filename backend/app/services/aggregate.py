"""聚合配置业务规则：状态流转、字段校验与聚合数据集更新联动。"""
from __future__ import annotations

from typing import Any

from app.services.qualityscore import (
    SCORE_FIELDS,
    QualityscoreService,
    parse_dimension_scores,
)
from app.store import store

MODULE = "aggregate"
REQUIRED_FIELDS = ["规则编号", "源数据粒度", "目标粒度"]
STATUS_ORDER = ["草稿", "规则评审中", "已生效", "已废弃"]
ACTION_RULES = {"提交规则评审": "规则评审中", "生效规则": "已生效", "废弃规则": "已废弃"}
NEGATIVE_ACTIONS = []


class AggregateService:
    def __init__(self) -> None:
        # 聚合数据集更新是质量评分链路的上游事件，由质量分服务统一重算总分。
        self.quality_service = QualityscoreService()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        dataset: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if dataset:
            rows = [row for row in rows if dataset in str(row.get("输出数据集", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 输出数据集是质量评分链路的关联键，一并落库，缺失时允许后续补登。
        for field in ["聚合函数集", "数据偏移分钟", "补全策略", "空值处理", "输出数据集"]:
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"聚合规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于聚合配置可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"聚合规则已{action}"

    def refresh_dataset(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """上游聚合数据集更新：落库最新维度指标，并触发质量总分重算。

        只有「已生效」的聚合规则能产出可用于质量评分的数据集；
        未生效/已废弃规则的更新不得进入评分链路。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"聚合规则 {entry_id} 不存在或已归档", []
        if entry.get("status") != "已生效":
            return None, (
                f"聚合规则 {entry_id} 当前状态为「{entry.get('status')}」，"
                "只有已生效规则产出的数据集才能更新质量评分"
            ), []

        dataset_name = str(entry.get("输出数据集") or "").strip()
        if not dataset_name:
            return None, "该聚合规则未配置输出数据集，无法关联质量评分规则", []

        incoming: dict[str, float] | None = None
        if any(str(values.get(field) or "").strip() for field in SCORE_FIELDS):
            scores, errors = parse_dimension_scores(values)
            if errors:
                return None, "维度指标校验失败：" + "；".join(errors), []
            assert scores is not None
            incoming = scores
            entry.update(incoming)
            entry["数据集更新时间"] = values.get("更新时间") or ""

        # 修复点：聚合数据集更新后按当前权重重算总分，总分不再滞留。
        recomputed = self.quality_service.refresh_dataset_scores(dataset_name, incoming)
        entry["数据集更新时间"] = entry.get("数据集更新时间") or ""
        return entry, (
            f"聚合数据集「{dataset_name}」已更新，"
            + (f"已重算 {len(recomputed)} 条启用规则的质量总分" if recomputed else "暂无需重算的启用评分规则")
        ), recomputed
