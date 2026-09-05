import React, { useEffect, useMemo, useState } from 'react'
import { getLoomResources } from '../api'
import type { LoomResourcesResult, LoomResourceRow } from '../types'

const CAP_LABELS: { key: 'waste_edge_disc' | 'edge_cut' | 'big_package' | 'water_filter' | 'yarn_frame'; label: string }[] = [
  { key: 'waste_edge_disc', label: '废边盘' },
  { key: 'edge_cut', label: '切边' },
  { key: 'big_package', label: '大卷装' },
  { key: 'water_filter', label: '水过滤' },
  { key: 'yarn_frame', label: '纱架' },
]

/** 织机资源：能力(工装)/状态/当前产品/产能/排程占用。 */
export default function LoomsPanel() {
  const [data, setData] = useState<LoomResourcesResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [regionFilter, setRegionFilter] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    setLoading(true)
    getLoomResources()
      .then(d => { setData(d); setError(null) })
      .catch(e => setError(String(e?.message || e)))
      .finally(() => setLoading(false))
  }, [])

  const regions = useMemo(() => Object.keys(data?.by_region ?? {}), [data])
  const statuses = useMemo(() => Object.keys(data?.by_status ?? {}), [data])

  const rows = useMemo(() => (data?.looms ?? []).filter(l =>
    (!statusFilter || l.status === statusFilter) &&
    (!regionFilter || l.region === regionFilter) &&
    (!search || `${l.loom_id} ${l.status} ${l.current_product ?? ''} ${l.region ?? ''}`.toLowerCase().includes(search.toLowerCase()))
  ), [data, statusFilter, regionFilter, search])

  if (loading) return <div className="empty-state">正在加载织机资源</div>
  if (error) return <div className="error-banner" data-testid="looms-error">加载失败：{error}</div>
  if (!data) return <div className="empty-state">织机资源为空</div>

  return (
    <div className="looms-page" data-testid="looms-page">
      <div className="looms-stats">
        <span className="pg-stat" data-testid="loom-stat-total"><b>{data.count}</b> 织机</span>
        <span className="pg-stat" data-testid="loom-stat-avail"><b>{data.available_count}</b> 可用</span>
        <span className="pg-stat"><b>{data.unavailable_count}</b> 不可用</span>
        <span className="pg-stat" data-testid="loom-stat-used"><b>{data.used_count}</b> 已排占用</span>
        <span className="pg-stat"><b>{data.idle_count}</b> 空闲</span>
        <span className="pg-stat"><b>{data.capability_summary?.waste_edge_disc ?? 0}</b> 废边盘</span>
        <span className="pg-stat"><b>{data.capability_summary?.edge_cut ?? 0}</b> 切边</span>
        <span className="pg-stat"><b>{data.capability_summary?.big_package ?? 0}</b> 大卷装</span>
        <span className="pg-stat"><b>{data.capability_summary?.water_filter ?? 0}</b> 水过滤</span>
        <span className="pg-stat"><b>{data.capability_summary?.yarn_frame ?? 0}</b> 纱架</span>
      </div>
      <p className="muted">{data.note}</p>

      <div className="looms-filters">
        <label>状态
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">全部</option>
            {statuses.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>区域
          <select value={regionFilter} onChange={e => setRegionFilter(e.target.value)}>
            <option value="">全部</option>
            {regions.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label>搜索
          <input value={search} placeholder="机号/状态/产品/区域"
            onChange={e => setSearch(e.target.value)} />
        </label>
      </div>

      <div className="looms-table-wrap">
        <table className="summary-table looms-table">
          <thead>
            <tr>
              <th>织机</th><th>区域</th><th>状态</th><th>可用</th><th>当前产品</th>
              <th>产能(米/天)</th><th>钢筘</th><th>边撑</th><th>工装(废边盘/切边/大卷装/水过滤/纱架)</th>
              <th>排程</th><th>计划产品</th><th>起止</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(l => (
              <tr key={l.loom_id} data-testid="loom-row">
                <td>{l.loom_id}</td>
                <td>{l.region ?? '—'}</td>
                <td><span className={`tt-status ${l.available ? 'ok' : 'g'}`}>{l.status}</span></td>
                <td>{l.available ? '是' : '否'}</td>
                <td>{l.current_product ?? '—'}</td>
                <td>{fmt(l.capacity_m_per_day)}</td>
                <td>{l.reed ?? '—'}</td>
                <td>{l.full_width_edge_support ?? '—'}</td>
                <td>
                  <span className="cap-chips">
                    {CAP_LABELS.map(c => (
                      <span key={c.key} className={`cap-chip ${l[c.key] ? 'on' : 'off'}`} title={c.label}>
                        {c.label[0]}
                      </span>
                    ))}
                  </span>
                  <span className="muted-cap">{l.tooling_note}</span>
                </td>
                <td>{l.used ? `${l.assigned_task_count} 任务` : '空闲'}</td>
                <td>{l.products_scheduled.join('、') || '—'}</td>
                <td>{l.assign_starts.length ? `${l.assign_starts[0]} ~ ${l.assign_ends[l.assign_ends.length - 1] ?? ''}` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function fmt(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toLocaleString()
}
