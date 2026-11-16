import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/qualityscore'
const columns = [
  "规则编号",
  "数据集名称",
  "完整性权重",
  "准确性权重",
  "时效性权重",
  "一致性权重",
  "准入门槛",
  "评分周期",
  "规则版本",
  "完整性得分",
  "准确性得分",
  "时效性得分",
  "一致性得分",
  "总分数",
  "最近快照编号"
]
const snapshotColumns = [
  "快照编号",
  "规则编号",
  "数据集名称",
  "评分周期",
  "周期口径",
  "规则版本",
  "准入门槛",
  "完整性得分",
  "准确性得分",
  "时效性得分",
  "一致性得分",
  "总分数",
  "状态",
  "评分时间"
]
const weightFields = ["完整性权重", "准确性权重", "时效性权重", "一致性权重"]
const scoreFields = ["完整性得分", "准确性得分", "时效性得分", "一致性得分"]
const actions = [
  "提交规则评审",
  "启用规则",
  "停用规则"
]

type Row = Record<string, string | number | null>
type SnapshotRow = Record<string, string | number | null>
type FormState = Record<string, string>

const emptyRuleForm: FormState = {
  规则编号: '',
  数据集名称: '',
  完整性权重: '0.4',
  准确性权重: '0.3',
  时效性权重: '0.2',
  一致性权重: '0.1',
  评分周期: '',
  准入门槛: '60'
}

function verdictBadge(status: unknown): string {
  const text = String(status ?? '')
  if (text === '有效' || text === '合格') return 'badge ok'
  if (text === '已作废') return 'badge muted'
  if (text.includes('冲突') || text.includes('矛盾') || text.includes('过期') || text.includes('驳回')) return 'badge err'
  return 'badge warn'
}

function Modal(props: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-overlay" onClick={props.onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <strong>{props.title}</strong>
          <button className="link" type="button" onClick={props.onClose}>关闭</button>
        </div>
        {props.children}
      </div>
    </div>
  )
}

export default function QualityscoreView() {
  const [rows, setRows] = useState<Row[]>([])
  const [snapshots, setSnapshots] = useState<SnapshotRow[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => [
    { label: "规则编号", param: "keyword" },
    { label: "数据集名称", param: "dataset" },
    { label: "状态", param: "status" }
  ], [])

  const [ruleModal, setRuleModal] = useState<null | { mode: 'create' | 'edit'; id?: number; values: FormState }>(null)
  const [snapshotModal, setSnapshotModal] = useState<null | { rule: Row; values: FormState }>(null)

  const reload = useCallback(async () => {
    setErrorMessage('')
    const params = new URLSearchParams()
    filterFields.forEach(({ label, param }) => {
      const value = filters[label]?.trim()
      if (value) params.set(param, value)
    })
    try {
      const response = await request(`${ENDPOINT}?${params.toString()}`)
      if (!response.ok) {
        throw new Error('评分规则列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据质量分列表读取失败')
    }
  }, [filters])

  const reloadSnapshots = useCallback(async () => {
    try {
      const response = await request(`${ENDPOINT}/snapshots?size=200`)
      if (response.ok) {
        const payload = await response.json()
        setSnapshots(payload.items ?? [])
      }
    } catch {
      // 快照面板失败不阻塞规则列表
    }
  }, [])

  useEffect(() => {
    void reload()
    void reloadSnapshots()
  }, [reload, reloadSnapshots])

  const stats = useMemo(() => [
    { label: "评分规则总数", value: total },
    { label: "已启用规则", value: rows.filter((row) => row.status === '已启用').length },
    { label: "评审中规则", value: rows.filter((row) => row.status === '规则评审中').length },
    { label: "有效评分快照", value: snapshots.filter((row) => row.状态 === '有效').length }
  ], [rows, snapshots, total])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || '数据质量分动作未生效，请稍后重试')
      }
      setNotice(payload.message)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据质量分操作失败')
    }
  }

  function openCreate() {
    setRuleModal({ mode: 'create', values: { ...emptyRuleForm } })
  }

  function openEdit(row: Row) {
    setRuleModal({
      mode: 'edit',
      id: Number(row.id),
      values: {
        规则编号: String(row.规则编号 ?? ''),
        数据集名称: String(row.数据集名称 ?? ''),
        完整性权重: String(row.完整性权重 ?? ''),
        准确性权重: String(row.准确性权重 ?? ''),
        时效性权重: String(row.时效性权重 ?? ''),
        一致性权重: String(row.一致性权重 ?? ''),
        评分周期: String(row.评分周期 ?? ''),
        准入门槛: String(row.准入门槛 ?? '')
      }
    })
  }

  async function submitRule() {
    if (!ruleModal) return
    setErrorMessage('')
    try {
      const url = ruleModal.mode === 'create' ? ENDPOINT : `${ENDPOINT}/${ruleModal.id}`
      const response = await request(url, {
        method: ruleModal.mode === 'create' ? 'POST' : 'PUT',
        body: JSON.stringify({ values: ruleModal.values }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || '评分规则保存失败')
      }
      setNotice(payload.message)
      setRuleModal(null)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '评分规则保存失败')
    }
  }

  function openSnapshot(row: Row) {
    setSnapshotModal({
      rule: row,
      values: {
        评分周期: '',
        完整性得分: '',
        准确性得分: '',
        时效性得分: '',
        一致性得分: ''
      }
    })
  }

  async function submitSnapshot() {
    if (!snapshotModal) return
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/snapshots`, {
        method: 'POST',
        body: JSON.stringify({
          values: { 规则编号: snapshotModal.rule.规则编号, ...snapshotModal.values }
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || '评分快照生成失败')
      }
      setNotice(payload.message)
      setSnapshotModal(null)
      await Promise.all([reload(), reloadSnapshots()])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '评分快照生成失败')
    }
  }

  return (
    <section className="page" data-module="qualityscore">
      <header className="page-head">
        <div>
          <h2>数据质量分管理</h2>
          <p className="page-desc">四项权重（完整性/准确性/时效性/一致性）全部落库，按权重计算质量总分并生成可追溯的评分快照。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={openCreate}>
            登记评分规则
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出数据质量分清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map(({ label }) => (
          <label key={label} className="filter-item">
            <span>{label}</span>
            <input
              value={filters[label] ?? ''}
              placeholder={`按${label}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [label]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      {notice && <p className="notice-text">{notice}</p>}
      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                <button className="link" type="button" onClick={() => openEdit(row)}>编辑规则</button>
                <button className="link" type="button" onClick={() => openSnapshot(row)}>生成快照</button>
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无数据质量分数据，可先登记评分规则</td>
            </tr>
          )}
        </tbody>
      </table>

      <section className="sub-panel">
        <h3>数据质量评分快照（维度得分与评分周期可追溯）</h3>
        <table className="data-table">
          <thead>
            <tr>
              {snapshotColumns.map((column) => <th key={column}>{column}</th>)}
            </tr>
          </thead>
          <tbody>
            {snapshots.map((row) => (
              <tr key={String(row.id)}>
                {snapshotColumns.map((column) => (
                  <td key={column}>
                    {column === '状态'
                      ? <span className={verdictBadge(row[column])}>{String(row[column] ?? '—')}</span>
                      : (row[column] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
            {snapshots.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={snapshotColumns.length}>暂无评分快照，请在规则启用且上游聚合数据集生效后生成</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <footer className="page-foot">
        <span>共 {total} 条数据质量分记录</span>
      </footer>

      {ruleModal && (
        <Modal title={ruleModal.mode === 'create' ? '登记评分规则' : `编辑评分规则（${ruleModal.values.规则编号 || ''}）`} onClose={() => setRuleModal(null)}>
          <div className="form-grid">
            <label className="form-field">
              <span>规则编号</span>
              <input
                disabled={ruleModal.mode === 'edit'}
                value={ruleModal.values.规则编号 ?? ''}
                onChange={(event) => setRuleModal({ ...ruleModal, values: { ...ruleModal.values, 规则编号: event.target.value } })}
              />
            </label>
            <label className="form-field">
              <span>数据集名称</span>
              <input
                value={ruleModal.values.数据集名称 ?? ''}
                onChange={(event) => setRuleModal({ ...ruleModal, values: { ...ruleModal.values, 数据集名称: event.target.value } })}
              />
            </label>
            {weightFields.map((field) => (
              <label key={field} className="form-field">
                <span>{field}（四项之和须为 1 或 100）</span>
                <input
                  value={ruleModal.values[field] ?? ''}
                  onChange={(event) => setRuleModal({ ...ruleModal, values: { ...ruleModal.values, [field]: event.target.value } })}
                />
              </label>
            ))}
            <label className="form-field">
              <span>评分周期口径（如按月/按周）</span>
              <input
                value={ruleModal.values.评分周期 ?? ''}
                onChange={(event) => setRuleModal({ ...ruleModal, values: { ...ruleModal.values, 评分周期: event.target.value } })}
              />
            </label>
            <label className="form-field">
              <span>准入门槛（0~100）</span>
              <input
                value={ruleModal.values.准入门槛 ?? ''}
                onChange={(event) => setRuleModal({ ...ruleModal, values: { ...ruleModal.values, 准入门槛: event.target.value } })}
              />
            </label>
          </div>
          <p className="form-hint">修改权重、门槛、数据集或周期会递增规则版本，历史评分快照将标记为「已作废」并保留明细。</p>
          <div className="modal-actions">
            <button className="btn ghost" type="button" onClick={() => setRuleModal(null)}>取消</button>
            <button className="btn primary" type="button" onClick={() => void submitRule()}>保存</button>
          </div>
        </Modal>
      )}

      {snapshotModal && (
        <Modal title={`生成评分快照 · ${String(snapshotModal.rule.规则编号)}（当前版本 ${String(snapshotModal.rule.规则版本)}）`} onClose={() => setSnapshotModal(null)}>
          <div className="form-grid">
            <label className="form-field">
              <span>评分周期（如 2026-W47 / 2026-11）</span>
              <input
                value={snapshotModal.values.评分周期 ?? ''}
                onChange={(event) => setSnapshotModal({ ...snapshotModal, values: { ...snapshotModal.values, 评分周期: event.target.value } })}
              />
            </label>
            {scoreFields.map((field) => (
              <label key={field} className="form-field">
                <span>{field}（0~100）</span>
                <input
                  value={snapshotModal.values[field] ?? ''}
                  onChange={(event) => setSnapshotModal({ ...snapshotModal, values: { ...snapshotModal.values, [field]: event.target.value } })}
                />
              </label>
            ))}
          </div>
          <p className="form-hint">
            前置条件：规则已启用、上游聚合数据集已有生效规则、四项维度得分齐全；同一规则同一评分周期只接纳首个通过校验的提交。
          </p>
          <div className="modal-actions">
            <button className="btn ghost" type="button" onClick={() => setSnapshotModal(null)}>取消</button>
            <button className="btn primary" type="button" onClick={() => void submitSnapshot()}>生成快照</button>
          </div>
        </Modal>
      )}
    </section>
  )
}
