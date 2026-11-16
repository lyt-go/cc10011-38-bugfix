import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/aggregate'
const columns = [
  "规则编号",
  "源数据粒度",
  "目标粒度",
  "聚合函数集",
  "数据偏移分钟",
  "补全策略",
  "空值处理",
  "输出数据集",
  "状态",
  "数据集更新时间"
]
const scoreFields = ["完整性得分", "准确性得分", "时效性得分", "一致性得分"]
const actions = [
  "提交规则评审",
  "生效规则",
  "废弃规则"
]

type Row = Record<string, string | number | null>
type FormState = Record<string, string>

function RefreshModal(props: { row: Row; onClose: () => void; onDone: (message: string) => void }) {
  const [values, setValues] = useState<FormState>({
    更新时间: '',
    完整性得分: '',
    准确性得分: '',
    时效性得分: '',
    一致性得分: ''
  })
  const [errorMessage, setErrorMessage] = useState('')

  async function submit() {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${props.row.id}/refresh`, {
        method: 'POST',
        body: JSON.stringify({ values }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || '聚合数据集更新失败')
      }
      props.onDone(payload.message)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合数据集更新失败')
    }
  }

  return (
    <div className="modal-overlay" onClick={props.onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <strong>更新聚合数据集 · {String(props.row.规则编号)}（{String(props.row.输出数据集 ?? '未配置数据集')}）</strong>
          <button className="link" type="button" onClick={props.onClose}>关闭</button>
        </div>
        <div className="form-grid">
          <label className="form-field">
            <span>更新时间（可留空）</span>
            <input value={values.更新时间} placeholder="2026-11-16 10:00:00"
              onChange={(event) => setValues({ ...values, 更新时间: event.target.value })} />
          </label>
          {scoreFields.map((field) => (
            <label key={field} className="form-field">
              <span>{field}（0~100）</span>
              <input value={values[field]}
                onChange={(event) => setValues({ ...values, [field]: event.target.value })} />
            </label>
          ))}
        </div>
        <p className="form-hint">
          仅「已生效」聚合规则可更新；提交后按评分规则当前权重重算关联数据集的质量总分，历史评分快照保持冻结。
        </p>
        {errorMessage && <p className="error-text">{errorMessage}</p>}
        <div className="modal-actions">
          <button className="btn ghost" type="button" onClick={props.onClose}>取消</button>
          <button className="btn primary" type="button" onClick={() => void submit()}>更新并重算总分</button>
        </div>
      </div>
    </div>
  )
}

export default function AggregateView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [refreshRow, setRefreshRow] = useState<Row | null>(null)
  const filterFields = useMemo(() => [
    { label: "规则编号", param: "keyword" },
    { label: "输出数据集", param: "dataset" },
    { label: "状态", param: "status" }
  ], [])

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
        throw new Error('聚合规则列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合配置列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  const stats = useMemo(() => [
    { label: "聚合规则总数", value: total },
    { label: "已生效规则", value: rows.filter((row) => row.status === '已生效').length },
    { label: "评审中规则", value: rows.filter((row) => row.status === '规则评审中').length }
  ], [rows, total])

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
        throw new Error(payload.message || '聚合配置动作未生效，请稍后重试')
      }
      setNotice(payload.message)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合配置操作失败')
    }
  }

  return (
    <section className="page" data-module="aggregate">
      <header className="page-head">
        <div>
          <h2>聚合配置管理</h2>
          <p className="page-desc">聚合数据集更新后联动重算数据质量总分，修复「上游已更新、总分滞留」的问题。</p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出聚合配置清单
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
                <button className="link" type="button" onClick={() => setRefreshRow(row)}>更新数据集并重算</button>
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
              <td className="empty-state" colSpan={columns.length + 1}>暂无聚合配置数据</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条聚合配置记录</span>
      </footer>

      {refreshRow && (
        <RefreshModal
          row={refreshRow}
          onClose={() => setRefreshRow(null)}
          onDone={(message) => {
            setNotice(message)
            setRefreshRow(null)
            void reload()
          }}
        />
      )}
    </section>
  )
}
