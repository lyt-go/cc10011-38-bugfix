import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/dataservice'
const columns = [
  "服务编号",
  "服务名称",
  "接口路径",
  "关联数据集",
  "质量快照编号",
  "质量规则版本",
  "质量总分",
  "质量准入判定",
  "状态"
]
const actions = [
  "提交服务评审",
  "上线服务",
  "下线服务"
]

type GateDetail = {
  规则编号: string
  规则状态: string
  规则版本: string
  准入门槛: number
  快照编号: string | null
  维度得分: Record<string, number | null>
  快照总分数: number | null
  当前总分数: number | null
  准入判定: string
  判定说明: string
}
type ServiceDetail = Record<string, string | number | null> & {
  质量门禁?: {
    关联数据集: string
    准入判定: string
    判定说明: string
    规则核对明细: GateDetail[]
  }
}
type Row = Record<string, string | number | null>

function verdictClass(text: unknown): string {
  const value = String(text ?? '')
  if (value === '合格' || value === '通过') return 'badge ok'
  if (value.includes('矛盾') || value.includes('冲突') || value.includes('驳回') || value.includes('过期') || value.includes('缺失') || value.includes('不合格')) return 'badge err'
  if (value === '规则未启用') return 'badge muted'
  return 'badge warn'
}

function GateModal(props: { detail: ServiceDetail; onClose: () => void }) {
  const gate = props.detail.质量门禁
  return (
    <div className="modal-overlay" onClick={props.onClose}>
      <div className="modal modal-wide" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <strong>服务发布质量门禁核对 · {String(props.detail.服务编号)}</strong>
          <button className="link" type="button" onClick={props.onClose}>关闭</button>
        </div>
        {!gate ? (
          <p className="form-hint">该服务暂无质量门禁信息。</p>
        ) : (
          <>
            <p className="form-hint">
              关联数据集：{gate.关联数据集 || '未关联'} ｜ 汇总判定：
              <span className={verdictClass(gate.准入判定)}>{gate.准入判定}</span>
              ｜ {gate.判定说明}
            </p>
            <table className="data-table">
              <thead>
                <tr>
                  <th>规则编号</th>
                  <th>规则状态</th>
                  <th>规则版本</th>
                  <th>快照编号</th>
                  <th>准入门槛</th>
                  <th>完整性</th>
                  <th>准确性</th>
                  <th>时效性</th>
                  <th>一致性</th>
                  <th>快照总分</th>
                  <th>当前总分</th>
                  <th>判定</th>
                </tr>
              </thead>
              <tbody>
                {gate.规则核对明细.map((item) => (
                  <tr key={item.规则编号}>
                    <td>{item.规则编号}</td>
                    <td>{item.规则状态}</td>
                    <td>{item.规则版本}</td>
                    <td>{item.快照编号 ?? '—'}</td>
                    <td>{item.准入门槛}</td>
                    {['完整性得分', '准确性得分', '时效性得分', '一致性得分'].map((field) => (
                      <td key={field} className={item.维度得分[field] === null ? 'cell-warn' : ''}>
                        {item.维度得分[field] ?? '缺失'}
                      </td>
                    ))}
                    <td>{item.快照总分数 ?? '—'}</td>
                    <td>{item.当前总分数 ?? '—'}</td>
                    <td><span className={verdictClass(item.准入判定)}>{item.准入判定}</span></td>
                  </tr>
                ))}
                {gate.规则核对明细.length === 0 && (
                  <tr><td className="empty-state" colSpan={12}>该数据集尚未配置评分规则</td></tr>
                )}
              </tbody>
            </table>
            <p className="form-hint">落库凭证：快照 {String(props.detail.质量快照编号 ?? '—')} ｜ 规则版本 {String(props.detail.质量规则版本 ?? '—')} ｜ 发布校验时间 {String(props.detail.发布校验时间 ?? '—')}</p>
            <p className="form-hint">{String(props.detail.发布校验说明 ?? '')}</p>
          </>
        )}
      </div>
    </div>
  )
}

export default function DataserviceView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [gateDetail, setGateDetail] = useState<ServiceDetail | null>(null)
  const filterFields = useMemo(() => [
    { label: "服务编号", param: "keyword" },
    { label: "服务名称", param: "name" },
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
        throw new Error('服务接口列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据服务列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  const stats = useMemo(() => [
    { label: "服务接口总数", value: total },
    { label: "已上线服务", value: rows.filter((row) => row.status === '已上线').length },
    { label: "评审中服务", value: rows.filter((row) => row.status === '服务评审中').length },
    { label: "质量门禁驳回", value: rows.filter((row) => row.质量准入判定 === '驳回').length }
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
        // 发布被质量门禁拦截时，错误原因必须在页面上可见而不是静默成功。
        throw new Error(payload.message || '数据服务动作未生效，请稍后重试')
      }
      setNotice(payload.message)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据服务操作失败')
    }
  }

  async function openGate(row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}`)
      if (!response.ok) {
        throw new Error('服务详情读取失败')
      }
      setGateDetail(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '服务详情读取失败')
    }
  }

  return (
    <section className="page" data-module="dataservice">
      <header className="page-head">
        <div>
          <h2>数据服务管理</h2>
          <p className="page-desc">服务上线前消费数据质量评分快照：停用规则不参与发布检查，版本/门槛不一致或维度缺失一律驳回。</p>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出数据服务清单
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
              {columns.map((column) => (
                <td key={column} className={column === '质量准入判定' && row[column] === '驳回' ? 'cell-warn' : ''}>
                  {column === '质量准入判定' && row[column]
                    ? <span className={verdictClass(row[column])}>{String(row[column])}</span>
                    : (row[column] ?? '—')}
                </td>
              ))}
              <td className="row-actions">
                <button className="link" type="button" onClick={() => void openGate(row)}>质量门禁核对</button>
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
              <td className="empty-state" colSpan={columns.length + 1}>暂无数据服务数据</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条数据服务记录</span>
      </footer>

      {gateDetail && <GateModal detail={gateDetail} onClose={() => setGateDetail(null)} />}
    </section>
  )
}
