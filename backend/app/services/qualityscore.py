"""数据质量分业务规则：评分权重、加权总分、评分快照与服务发布门禁。

链路说明（与前端「数据质量分 / 聚合配置 / 数据服务」三个入口对应）：

1. 评分规则保存：完整性、准确性、时效性、一致性四项权重全部落库，
   权重必须为数值且四项之和为 1（或 100），不再只保留完整性权重。
2. 评分快照：读取「已生效」的上游聚合数据集与「已启用」的评分规则，
   按四项维度得分 × 权重计算加权总分，快照冻结规则版本、准入门槛、
   评分周期、权重与维度得分，保证维度得分与评分周期可追溯。
3. 聚合数据集更新：聚合配置刷新后，按当前权重重算关联评分规则的总分数，
   总分不再滞留；历史快照保持不变，作为该评分周期的冻结凭证。
4. 版本冲突取舍（方案取舍轴）：规则内容变更（权重/门槛/数据集/周期）时
   规则版本递增（v1→v2），旧快照标记为「已作废」但保留明细；服务发布
   门禁只认与当前规则版本、当前准入门槛同时一致的有效快照——选择保留
   历史而不是覆盖历史，以牺牲少量冗余换取评分周期可追溯。
5. 服务发布门禁：停用规则不得参与发布检查；快照四个维度得分缺一不可，
   杜绝「总分合格、维度得分缺失」的自相矛盾状态。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "qualityscore"
SNAPSHOT_MODULE = "quality_snapshot"

DIMENSIONS = ["完整性", "准确性", "时效性", "一致性"]
WEIGHT_FIELDS = [f"{name}权重" for name in DIMENSIONS]
SCORE_FIELDS = [f"{name}得分" for name in DIMENSIONS]
REQUIRED_FIELDS = ["规则编号", "数据集名称", *WEIGHT_FIELDS]

STATUS_ORDER = ["草稿", "规则评审中", "已启用", "已停用"]
ACTION_RULES = {"提交规则评审": "规则评审中", "启用规则": "已启用", "停用规则": "已停用"}
NEGATIVE_ACTIONS = ["停用规则"]

DEFAULT_THRESHOLD = 60.0
SNAPSHOT_VALID = "有效"
SNAPSHOT_OBSOLETE = "已作废"

# 快照生成与聚合刷新都涉及「多个依赖同时提交只接纳首个通过校验」的顺序要求，
# 进程内加锁保证校验-落库的原子性；锁内重复键二次检查，防止并发穿透。
_SNAPSHOT_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    """把表单里的字符串/数字转成 float；空值与非法值返回 None 由调用方报错。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bump_version(version: Any) -> str:
    text = str(version or "v1").strip().lower()
    if text.startswith("v") and text[1:].isdigit():
        return f"v{int(text[1:]) + 1}"
    return "v2"


def parse_weights(values: dict[str, Any]) -> tuple[dict[str, float] | None, list[str]]:
    """校验四项权重：必须可转数值、非负、且总和为 1 或 100（允许浮点误差）。"""
    errors: list[str] = []
    weights: dict[str, float] = {}
    for field in WEIGHT_FIELDS:
        number = _to_float(values.get(field))
        if number is None:
            errors.append(f"{field}必须是数值")
            continue
        if number < 0:
            errors.append(f"{field}不能为负数")
            continue
        weights[field] = number
    if errors:
        return None, errors
    total = sum(weights.values())
    if total <= 0:
        return None, ["四项权重不能全部为 0"]
    if abs(total - 1.0) > 1e-6 and abs(total - 100.0) > 1e-6:
        return None, [f"四项权重之和必须为 1（或 100），当前为 {round(total, 4)}"]
    return weights, []


def parse_dimension_scores(values: dict[str, Any]) -> tuple[dict[str, float] | None, list[str]]:
    """校验四项维度得分：必填、数值、落在 0~100。"""
    errors: list[str] = []
    scores: dict[str, float] = {}
    for field in SCORE_FIELDS:
        number = _to_float(values.get(field))
        if number is None:
            errors.append(f"缺少{field}或不是数值")
            continue
        if number < 0 or number > 100:
            errors.append(f"{field}必须在 0~100 之间")
            continue
        scores[field] = number
    if errors:
        return None, errors
    return scores, []


def weighted_total(weights: dict[str, float], scores: dict[str, float]) -> float:
    """按权重计算数据质量加权总分；权重为 1 或 100 口径都能得到 0~100 的总分。"""
    numerator = sum(weights[w] * scores[s] for w, s in zip(WEIGHT_FIELDS, SCORE_FIELDS))
    denominator = sum(weights.values())
    return round(numerator / denominator, 2)


class QualityscoreService:
    # ---------- 规则列表与明细 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        dataset: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if dataset:
            rows = [row for row in rows if dataset in str(row.get("数据集名称", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_rule_by_code(self, rule_code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("规则编号", "")).strip() == str(rule_code).strip():
                return row
        return None

    # ---------- 规则登记 / 编辑 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, [f"缺少必填字段：{name}" for name in missing]

        weights, errors = parse_weights(values)
        if errors:
            return None, errors
        assert weights is not None

        threshold = _to_float(values.get("准入门槛"))
        if threshold is None:
            threshold = DEFAULT_THRESHOLD
        elif not 0 <= threshold <= 100:
            return None, ["准入门槛必须在 0~100 之间"]

        rows = store.rows(MODULE)
        if any(str(row.get("规则编号", "")).strip() == str(values["规则编号"]).strip() for row in rows):
            return None, [f"规则编号 {values['规则编号']} 已存在"]

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["规则编号"] = str(values["规则编号"]).strip()
        entry["数据集名称"] = str(values["数据集名称"]).strip()
        # 修复点：四项权重全部落库，而不是只保留完整性权重。
        entry.update(weights)
        entry["评分周期"] = str(values.get("评分周期") or "").strip()
        entry["准入门槛"] = threshold
        entry["规则版本"] = "v1"
        entry["版本说明"] = "初始版本"
        # 维度得分与总分初始为空，等待聚合数据集与快照链路写入。
        for field in SCORE_FIELDS:
            entry[field] = None
        entry["总分数"] = None
        entry["最近快照编号"] = None
        entry["最近评分周期"] = None
        entry["最近评分时间"] = None
        entry["最近重算时间"] = None
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, [f"评分规则 {entry_id} 不存在或已归档"]

        # 合并出完整权重后再做口径校验，支持只传部分字段的编辑。
        merged = {field: entry.get(field) for field in WEIGHT_FIELDS}
        merged.update({field: values[field] for field in WEIGHT_FIELDS if field in values})
        weights, errors = parse_weights(merged)
        if errors:
            return None, errors
        assert weights is not None

        threshold = entry["准入门槛"]
        if "准入门槛" in values and str(values.get("准入门槛") or "").strip():
            parsed = _to_float(values.get("准入门槛"))
            if parsed is None or not 0 <= parsed <= 100:
                return None, ["准入门槛必须是 0~100 之间的数值"]
            threshold = parsed

        version_changed = (
            any(abs(float(entry[field]) - weights[field]) > 1e-9 for field in WEIGHT_FIELDS)
            or abs(float(entry["准入门槛"]) - float(threshold)) > 1e-9
        )
        if "数据集名称" in values and str(values.get("数据集名称") or "").strip():
            new_name = str(values["数据集名称"]).strip()
            version_changed = version_changed or new_name != entry["数据集名称"]
            entry["数据集名称"] = new_name
        if "评分周期" in values and str(values.get("评分周期") or "").strip():
            new_period = str(values["评分周期"]).strip()
            version_changed = version_changed or new_period != entry.get("评分周期")
            entry["评分周期"] = new_period

        entry.update(weights)
        entry["准入门槛"] = threshold

        if version_changed:
            entry["规则版本"] = _bump_version(entry.get("规则版本"))
            entry["版本说明"] = f"{_now()} 规则内容变更，版本递增；旧快照作废保留"
            # 历史快照不删除、不覆盖，只翻转状态，保证评分周期仍可追溯。
            for snapshot in store.rows(SNAPSHOT_MODULE):
                if snapshot.get("规则编号") == entry["规则编号"] and snapshot.get("状态") == SNAPSHOT_VALID:
                    snapshot["状态"] = SNAPSHOT_OBSOLETE
                    snapshot["作废原因"] = f"规则升级至 {entry['规则版本']}，评分版本/门槛口径变化"
                    snapshot["作废时间"] = _now()
            entry["总分数"] = None
            entry["最近快照编号"] = None
            entry["最近评分周期"] = None
            entry["最近评分时间"] = None
        else:
            # 仅描述性信息变更时，若已有维度得分则按新权重即时重算总分。
            self._recompute_total(entry)
        return entry, []

    # ---------- 状态流转 ----------
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"评分规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据质量分可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"评分规则已{action}"

    # ---------- 上游聚合数据集 ----------
    def find_upstream_datasets(self, dataset_name: str) -> list[dict[str, Any]]:
        """上游聚合数据集：输出数据集与评分规则绑定同名、且聚合规则已生效。"""
        return [
            row for row in store.rows("aggregate")
            if str(row.get("输出数据集", "")).strip() == str(dataset_name).strip()
            and row.get("status") == "已生效"
        ]

    # ---------- 评分快照 ----------
    def list_snapshots(
        self,
        *,
        rule_code: str | None = None,
        period: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(SNAPSHOT_MODULE)
        if rule_code:
            rows = [row for row in rows if rule_code in str(row.get("规则编号", ""))]
        if period:
            rows = [row for row in rows if period in str(row.get("评分周期", ""))]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        return store.find(SNAPSHOT_MODULE, snapshot_id)

    def latest_valid_snapshot(self, rule_code: str) -> dict[str, Any] | None:
        candidates = [
            row for row in store.rows(SNAPSHOT_MODULE)
            if row.get("规则编号") == rule_code and row.get("状态") == SNAPSHOT_VALID
        ]
        return max(candidates, key=lambda row: int(row.get("id", 0)), default=None)

    def generate_snapshot(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """生成数据质量评分快照。

        前置条件：评分规则已启用、上游聚合数据集已生效、四项维度得分齐全。
        并发口径：同一规则同一评分周期只接纳首个通过全部校验的请求，
        后续请求（含并发到达）一律拒绝，保证处理顺序确定、快照不重复。
        """
        rule_code = str(values.get("规则编号") or "").strip()
        period = str(values.get("评分周期") or "").strip()
        if not rule_code:
            return None, "缺少规则编号，无法定位评分规则"
        if not period:
            return None, "缺少评分周期，快照必须可追溯到评分周期"

        with _SNAPSHOT_LOCK:
            rule = self.find_rule_by_code(rule_code)
            if rule is None:
                return None, f"评分规则 {rule_code} 不存在"
            if rule.get("status") != "已启用":
                return None, f"评分规则 {rule_code} 当前状态为「{rule.get('status')}」，未启用不能生成快照"

            upstream = self.find_upstream_datasets(rule["数据集名称"])
            if not upstream:
                return None, (
                    f"上游聚合数据集「{rule['数据集名称']}」尚未有已生效的聚合规则，"
                    "依赖未完成不能生成数据质量评分快照"
                )

            scores, score_errors = parse_dimension_scores(values)
            if score_errors:
                return None, "维度得分校验失败：" + "；".join(score_errors)
            assert scores is not None

            # 锁内二次检查：并发时首个通过校验的请求已落库，后续同周期请求拒绝。
            duplicated = any(
                row.get("规则编号") == rule_code
                and row.get("评分周期") == period
                and row.get("状态") == SNAPSHOT_VALID
                for row in store.rows(SNAPSHOT_MODULE)
            )
            if duplicated:
                return None, f"规则 {rule_code} 在评分周期 {period} 的快照已由首个通过校验的请求生成，请勿重复提交"

            weights = {field: float(rule[field]) for field in WEIGHT_FIELDS}
            total = weighted_total(weights, scores)
            threshold = float(rule["准入门槛"])
            passed = total >= threshold

            snapshots = store.rows(SNAPSHOT_MODULE)
            snapshot_id = max((int(row.get("id", 0)) for row in snapshots), default=0) + 1
            snapshot: dict[str, Any] = {
                "id": snapshot_id,
                "快照编号": f"SNAP-{snapshot_id:04d}",
                "规则编号": rule_code,
                "数据集名称": rule["数据集名称"],
                "评分周期": period,
                # 同时冻结规则配置的周期口径（如按月/按周），具体周期与口径都可追溯。
                "周期口径": rule.get("评分周期"),
                # 冻结版本与门槛：服务发布门禁据此核对口径一致性。
                "规则版本": rule["规则版本"],
                "准入门槛": threshold,
                "状态": SNAPSHOT_VALID,
                "是否合格": passed,
                "总分数": total,
                "评分时间": _now(),
                "来源聚合规则": [str(row.get("规则编号", "")) for row in upstream],
                "维度明细": {
                    dimension: {
                        "权重": weights[f"{dimension}权重"],
                        "得分": scores[f"{dimension}得分"],
                    }
                    for dimension in DIMENSIONS
                },
            }
            # 同时把权重与维度得分平铺，方便列表与下游模块直接消费。
            snapshot.update(weights)
            snapshot.update(scores)
            snapshots.append(snapshot)

            # 回写规则当前口径下的维度得分与总分（列表入口与服务详情共用这一份数据）。
            # 规则上的「评分周期」保留周期口径（按月/按周），具体周期只记录在快照里。
            rule.update(scores)
            rule["总分数"] = total
            rule["最近评分周期"] = period
            rule["最近快照编号"] = snapshot["快照编号"]
            rule["最近评分时间"] = snapshot["评分时间"]
            rule["最近重算时间"] = snapshot["评分时间"]
            return snapshot, "数据质量评分快照已生成"

    # ---------- 聚合更新后的总分重算 ----------
    def refresh_dataset_scores(
        self,
        dataset_name: str,
        incoming_scores: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """聚合数据集更新后重算关联评分规则的总分数。

        历史快照是评分周期的冻结凭证，不在此环节改写；只刷新规则上的
        当前维度得分与总分数，解决「聚合数据集更新后总分滞留」。
        """
        recomputed: list[dict[str, Any]] = []
        for rule in store.rows(MODULE):
            if str(rule.get("数据集名称", "")).strip() != str(dataset_name).strip():
                continue
            if rule.get("status") != "已启用":
                continue
            if incoming_scores:
                rule.update(incoming_scores)
            if self._recompute_total(rule):
                rule["最近重算时间"] = _now()
                recomputed.append({"规则编号": rule["规则编号"], "总分数": rule["总分数"]})
        return recomputed

    def _recompute_total(self, rule: dict[str, Any]) -> bool:
        if any(rule.get(field) is None for field in SCORE_FIELDS):
            return False
        weights = {field: float(rule[field]) for field in WEIGHT_FIELDS}
        scores = {field: float(rule[field]) for field in SCORE_FIELDS}
        rule["总分数"] = weighted_total(weights, scores)
        return True

    # ---------- 数据服务发布门禁 ----------
    def _rules_for_dataset(self, dataset_name: str) -> list[dict[str, Any]]:
        return [
            row for row in store.rows(MODULE)
            if str(row.get("数据集名称", "")).strip() == str(dataset_name).strip()
        ]

    def _check_rule_gate(
        self, rule: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """单条启用规则的门禁核对，返回（是否通过、说明、命中的有效快照）。"""
        snapshot = self.latest_valid_snapshot(str(rule["规则编号"]))
        if snapshot is None:
            return False, (
                f"规则 {rule['规则编号']} 缺少与当前版本 {rule.get('规则版本')} "
                "一致的有效评分快照（历史快照如已作废不可再用），请按新规则重新生成快照"
            ), None
        if snapshot.get("规则版本") != rule.get("规则版本"):
            return False, (
                f"规则 {rule['规则编号']} 的快照评分版本 {snapshot.get('规则版本')} "
                f"与当前规则版本 {rule.get('规则版本')} 不一致，请按新规则重新生成快照"
            ), snapshot
        if float(snapshot.get("准入门槛", -1)) != float(rule.get("准入门槛")):
            return False, (
                f"规则 {rule['规则编号']} 的快照准入门槛 {snapshot.get('准入门槛')} "
                f"与当前门槛 {rule.get('准入门槛')} 不一致，准入门槛与评分版本必须同时与当前规则一致"
            ), snapshot
        missing = [field for field in SCORE_FIELDS if snapshot.get(field) is None]
        if missing:
            return False, (
                f"规则 {rule['规则编号']} 的快照缺少维度得分：{'、'.join(missing)}，总分合格也不得放行"
            ), snapshot
        # 快照只能代表生成时刻的数据；上游聚合数据集更新后，规则当前维度得分
        # 与快照不一致即视为快照过期，避免服务详情继续显示旧总分。
        current_missing = [field for field in SCORE_FIELDS if rule.get(field) is None]
        if current_missing:
            return False, (
                f"规则 {rule['规则编号']} 当前维度得分缺失：{'、'.join(current_missing)}，"
                "请等待聚合数据集补齐后重新评分"
            ), snapshot
        stale_fields = [
            field for field in SCORE_FIELDS
            if float(rule[field]) != float(snapshot[field])
        ]
        if stale_fields:
            current_total = rule.get("总分数")
            tail = (
                f"，且当前总分 {current_total} 低于准入门槛 {rule['准入门槛']}"
                if current_total is not None and float(current_total) < float(rule["准入门槛"])
                else ""
            )
            return False, (
                f"规则 {rule['规则编号']} 的上游聚合数据集已更新，快照 {snapshot['快照编号']} "
                f"已不代表最新数据（偏离维度：{'、'.join(stale_fields)}）{tail}，"
                "请按新评分周期生成快照后再发布"
            ), snapshot
        if float(snapshot["总分数"]) < float(rule["准入门槛"]):
            return False, (
                f"规则 {rule['规则编号']} 的数据质量总分 {snapshot['总分数']} "
                f"低于准入门槛 {rule['准入门槛']}，服务发布被驳回"
            ), snapshot
        return True, (
            f"规则 {rule['规则编号']} 门禁通过：快照 {snapshot['快照编号']}，"
            f"版本 {snapshot['规则版本']}，总分 {snapshot['总分数']} ≥ 门槛 {rule['准入门槛']}"
        ), snapshot

    def evaluate_publish_gate(self, dataset_name: str) -> tuple[bool, str, dict[str, Any] | None]:
        """服务发布前的数据质量门禁，供数据服务模块调用。

        判定轴：
        1. 数据集上必须存在评分规则，且至少一条为「已启用」——停用规则不得被
           服务发布使用，全部停用时直接驳回；
        2. 每条启用规则都要有与当前规则版本、准入门槛同时一致的有效快照——
           版本冲突时旧快照即使总分达标也不放行；
        3. 快照四项维度得分齐全且总分达到门槛——杜绝维度缺失的矛盾状态。
        """
        if not str(dataset_name or "").strip():
            return False, "服务未关联数据集，无法执行数据质量准入校验", None

        rules = self._rules_for_dataset(dataset_name)
        if not rules:
            return False, f"数据集「{dataset_name}」未配置数据质量评分规则，不能发布服务", None
        enabled_rules = [rule for rule in rules if rule.get("status") == "已启用"]
        if not enabled_rules:
            names = "、".join(str(rule.get("规则编号")) for rule in rules)
            return False, (
                f"数据集「{dataset_name}」的评分规则 {names} 均未处于「已启用」状态，"
                "停用/未启用规则不得用于服务发布检查"
            ), None

        passed_snapshots: list[dict[str, Any]] = []
        for rule in enabled_rules:
            ok, message, snapshot = self._check_rule_gate(rule)
            if not ok:
                return False, message, snapshot
            assert snapshot is not None
            passed_snapshots.append(snapshot)
        return True, "；".join(
            f"快照 {snapshot['快照编号']}(版本 {snapshot['规则版本']}, 总分 {snapshot['总分数']})"
            for snapshot in passed_snapshots
        ) + " 全部通过数据质量门禁", passed_snapshots[-1]

    def describe_gate(self, dataset_name: str) -> dict[str, Any]:
        """给服务详情页提供可核对的质量门禁视图，两个入口联动核对同一份快照。"""
        rules = self._rules_for_dataset(dataset_name)
        if not rules:
            return {
                "关联数据集": dataset_name,
                "准入判定": "无评分规则",
                "判定说明": "该数据集尚未配置评分规则",
                "规则核对明细": [],
            }
        details: list[dict[str, Any]] = []
        for rule in rules:
            snapshot = self.latest_valid_snapshot(str(rule["规则编号"]))
            dimension_scores = (
                {field: snapshot.get(field) for field in SCORE_FIELDS}
                if snapshot else {field: None for field in SCORE_FIELDS}
            )
            snapshot_total = snapshot.get("总分数") if snapshot else None
            current_total = rule.get("总分数")
            has_missing_dimension = any(value is None for value in dimension_scores.values())
            version_mismatch = (
                snapshot is not None and (
                    snapshot.get("规则版本") != rule.get("规则版本")
                    or float(snapshot.get("准入门槛", -1)) != float(rule.get("准入门槛"))
                )
            )
            current_missing = [field for field in SCORE_FIELDS if rule.get(field) is None]
            stale = (
                snapshot is not None
                and not current_missing
                and not has_missing_dimension
                and any(float(rule[field]) != float(snapshot[field]) for field in SCORE_FIELDS)
            )
            if has_missing_dimension and snapshot_total is not None and float(snapshot_total) >= float(rule["准入门槛"]):
                verdict = "数据矛盾"
                note = "总分达到门槛但维度得分缺失，该状态不得作为合格依据"
            elif rule.get("status") != "已启用":
                verdict = "规则未启用"
                note = f"评分规则状态为「{rule.get('status')}」，发布门禁不会采纳"
            elif snapshot is None:
                verdict = "无有效快照"
                note = "当前规则版本下尚未生成有效评分快照"
            elif version_mismatch:
                verdict = "版本冲突"
                note = (
                    f"快照版本 {snapshot.get('规则版本')} 与当前版本 {rule.get('规则版本')} 不一致，"
                    f"或快照门槛 {snapshot.get('准入门槛')} 与当前门槛 {rule.get('准入门槛')} 不一致"
                )
            elif current_missing:
                verdict = "维度缺失"
                note = "规则当前维度得分不齐全，不得判定合格"
            elif stale:
                verdict = "快照已过期"
                note = "上游聚合数据集已更新，快照不再代表最新数据，需重新评分"
            elif has_missing_dimension:
                verdict = "维度缺失"
                note = "维度得分不齐全，不得判定合格"
            elif float(snapshot_total) < float(rule["准入门槛"]):
                verdict = "不合格"
                note = f"总分 {snapshot_total} 低于门槛 {rule['准入门槛']}"
            else:
                verdict = "合格"
                note = "维度得分齐全，总分达到准入门槛"
            details.append({
                "规则编号": rule.get("规则编号"),
                "规则状态": rule.get("status"),
                "规则版本": rule.get("规则版本"),
                "准入门槛": rule.get("准入门槛"),
                "快照编号": snapshot.get("快照编号") if snapshot else None,
                "快照状态": snapshot.get("状态") if snapshot else None,
                "维度得分": dimension_scores,
                "快照总分数": snapshot_total,
                "当前总分数": current_total,
                "准入判定": verdict,
                "判定说明": note,
            })

        priority = ["数据矛盾", "版本冲突", "无有效快照", "维度缺失", "快照已过期", "不合格", "规则未启用", "合格"]
        overall = next(
            (name for name in priority if any(item["准入判定"] == name for item in details)),
            "规则未启用",
        )
        return {
            "关联数据集": dataset_name,
            "准入判定": overall,
            "判定说明": f"共 {len(details)} 条评分规则，汇总判定：{overall}",
            "规则核对明细": details,
        }
