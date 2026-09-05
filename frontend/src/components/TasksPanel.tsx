import React, { useEffect, useMemo, useState } from 'react'
import { getTaskPool } from '../api'
import type { TaskPoolResult, TaskPoolRow } from '../types'

const STATUS_LABEL: Record<string, string> = {
  已排程: '已排程',
  部分排程: '部分排程',
  未排程: '未排程',
  锁定: '锁定',
}

/** 任务池：生产任务主档 + 排程结果 + 流程状态。 */
export default function TasksPanel() {
  const [data, setData] = useState<TaskPoolResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [productFilter, setProductFilter] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    setLoading(true)
    getTaskPool()
      .then(d => { setData(d); setError(null) })
      .catch(e => setError(String(e?.message || e)))
      .finally(() => setLoading(false))
  }, [])

  const products = useMemo(() =>
    Array.from(new Set((data?.tasks ?? []).map(t => t.product_id))), [data])

  const rows = useMemo(() => (data?.tasks ?? []).filter(t =>
    (!statusFilter || t.status === statusFilter) &&
    (!productFilter || t.product_id === productFilter) &&
    (!search || `${t.task_id} ${t.product_id} ${t.machine_id ?? ''} ${t.warp_beam_sku ?? ''} ${t.beam_instance_id ?? ''} ${t.weaving_sku ?? ''}`.toLowerCase().includes(search.toLowerCase()))
  ), [data, statusFilter, productFilter, search])

  if (loading) return <div className="empty-state">正在加载任务池</div>
  if (error) return <div className="error-banner" data-testid="tasks-error">加载失败：{error}</div>
  if (!data) return <div className="empty-state">任务池为空</div>

  const byStatus = (s: string) => data.by_status[s] ?? 0

  return (
    <div className="tasks-page" data-testid="tasks-page">
      <div className="tasks-stats">
        <span className="pg-stat" data-testid="task-stat-total"><b>{data.count}</b> 任务</span>
        <span className="pg-stat" data-testid="task-stat-required"><b>{fmt(data.sum_required)}</b> 需求(米)</span>
        <span className="pg-stat" data-testid="task-stat-scheduled"><b>{fmt(data.sum_scheduled)}</b> 已排(米)</span>
        <span className="pg-stat" data-testid="task-stat-unscheduled"><b>{fmt(data.sum_unscheduled)}</b> 未排(米)</span>
        <span className="pg-stat"><b>{byStatus('已排程')}</b> 已排程</span>
        <span className="pg-stat"><b>{byStatus('部分排程')}</b> 部分排程</span>
        <span className="pg-stat"><b>{byStatus('未排程')}</b> 未排程</span>
        <span className="pg-stat"><b>{data.locked_count}</b> 锁定</span>
        <span className="pg-stat"><b>{data.split_count}</b> 可拆分</span>
      </div>

      <div className="tasks-filters">
        <label>状态
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">全部</option>
            {Object.keys(data.by_status).map(s => <option key={s} value={s}>{STATUS_LABEL[s] ?? s}</option>)}
          </select>
        </label>
        <label>产品
          <select value={productFilter} onChange={e => setProductFilter(e.target.value)}>
            <option value="">全部</option>
            {products.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label>搜索
          <input value={search} placeholder="任务/产品/织机/经轴"
            onChange={e => setSearch(e.target.value)} />
        </label>
      </div>

      <div className="tasks-table-wrap">
        <table className="summary-table tasks-table">
          <thead>
            <tr>
              <th>任务</th><th>产品</th><th>需求(米)</th><th>已排(米)</th><th>未排(米)</th>
              <th>交期</th><th>优先级</th><th>经轴品番</th><th>虚拟经轴</th><th>工艺链</th>
              <th>兼容织机</th><th>分配织机</th><th>起止</th><th>状态</th><th>说明</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(t => (
              <tr key={t.task_id} data-testid="task-row">
                <td>{t.task_id}</td>
                <td>{t.product_id}</td>
                <td>{fmt(t.required_quantity)}</td>
                <td>{fmt(t.scheduled_quantity)}</td>
                <td className={t.unscheduled_quantity > 1e-6 ? 'warn-cell' : ''}>{fmt(t.unscheduled_quantity)}</td>
                <td>{t.due_date ?? '—'}</td>
                <td>{t.priority}</td>
                <td>{t.warp_beam_sku ?? '待建档'}</td>
                <td>{t.beam_instance_id ?? '—'}</td>
                <td title={t.chain_reason}>{t.chain_status || '待建档'}</td>
                <td>{t.compatible_loom_count ?? '—'}</td>
                <td>{t.machine_id ?? '—'}</td>
                <td>{t.assign_start ? `${t.assign_start} ~ ${t.assign_end ?? ''}` : '—'}</td>
                <td><StatusBadge t={t} /></td>
                <td className="muted-cell">{explain(t)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StatusBadge({ t }: { t: TaskPoolRow }) {
  const cls = t.status === '已排程' ? 'ok' : t.status === '锁定' ? 'b' : t.status === '部分排程' ? 'orange' : 'g'
  return <span className={`tt-status ${cls}`}>{t.status}</span>
}

function explain(t: TaskPoolRow): string {
  if (t.chain_status && t.chain_status !== '完整串联') return t.chain_reason || '工艺链待补充'
  if (t.locked) return t.lock_reason || '人工锁定'
  if (t.blocked_reason) return t.blocked_reason
  if (t.primary_reason) return t.primary_reason
  if (t.lateness_minutes > 0) return `延误 ${t.lateness_minutes} 分钟`
  if (t.split_allowed) return '允许拆分'
  return ''
}

function fmt(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toLocaleString()
}
