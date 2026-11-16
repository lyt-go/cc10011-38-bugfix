"""数据服务业务规则：状态流转、字段校验与数据质量发布门禁。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.qualityscore import QualityscoreService
from app.store import store

MODULE = "dataservice"
REQUIRED_FIELDS = ["服务编号", "服务名称", "接口路径"]
STATUS_ORDER = ["草稿", "服务评审中", "已上线", "已下线"]
ACTION_RULES = {"提交服务评审": "服务评审中", "上线服务": "已上线", "下线服务": "已下线"}
NEGATIVE_ACTIONS = ["下线服务"]


class DataserviceService:
    def __init__(self) -> None:
        # 数据服务是数据质量评分快照的下游消费方，发布门禁由质量分服务判定。
        self.quality_service = QualityscoreService()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        name: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("服务编号", ""))]
        if name:
            rows = [row for row in rows if name in str(row.get("服务名称", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def detail_with_gate(self, entry_id: int) -> dict[str, Any] | None:
        """服务详情：在原始落库记录上补质量门禁核对视图。

        两个入口（评分列表 / 服务详情）必须呈现同一口径：
        总分合格但维度得分缺失时直接标记「数据矛盾」，不再显示自相矛盾的状态。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        detail = dict(entry)
        detail["质量门禁"] = self.quality_service.describe_gate(str(entry.get("关联数据集") or ""))
        return detail

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 关联数据集是发布门禁的输入，登记时可预留，发布前必须补齐。
        entry["关联数据集"] = str(values.get("关联数据集") or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 落库点：服务发布所依据的质量快照凭证字段，发布通过后回填。
        entry["质量快照编号"] = None
        entry["质量规则版本"] = None
        entry["质量总分"] = None
        entry["质量准入判定"] = None
        entry["发布校验时间"] = None
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"服务接口 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据服务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        if action == "上线服务":
            # 发布门禁：停用规则不参与、版本/门槛须一致、维度得分须齐全。
            passed, message, snapshot = self.quality_service.evaluate_publish_gate(
                str(entry.get("关联数据集") or "")
            )
            if not passed:
                entry["质量准入判定"] = "驳回"
                return None, f"服务发布被数据质量门禁拦截：{message}"
            # 按既有数据流把快照凭证落到服务记录上，供详情页与审计追溯。
            entry["质量快照编号"] = snapshot["快照编号"]
            entry["质量规则版本"] = snapshot["规则版本"]
            entry["质量总分"] = snapshot["总分数"]
            entry["质量准入判定"] = "通过"
            entry["发布校验时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry["发布校验说明"] = message

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"服务接口已{action}"
