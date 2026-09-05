import React, { useMemo, useState } from 'react'
import type { ProcessBar, ProcessGanttResult, ProcessName } from '../types'

const PROC_COLOR: Record<ProcessName, string> = {
  整经: '#8064a2',
  穿综穿筘: '#5b8def',
  织造准备: '#f79646',
  织造: '#4f81bd',
  水洗: '#9bbb59',
}

const PROC_LABEL: Record<ProcessName, string> = {
  整经: '整经生成经轴',
  穿综穿筘: '经轴穿综穿筘',
  织造准备: '上轴与仕挂',
  织造: '织造生成织造品番',
  水洗: '水洗',
}

interface Props {
  data: ProcessGanttResult
  scheduleStart?: string
  horizonDays?: number
}

/** 工艺视图甘特图：整经 / 织造 / 水洗 三组，按 整经完成才能上轴织造、织造完成才能水洗 串联。 */
export default function ProcessGantt({ data, scheduleStart, horizonDays = 7 }: Props) {
  const [filter, setFilter] = useState('')
  const [selected, setSelected] = useState<ProcessBar | null>(null)
  const { base, days } = useMemo(
    () => computeRange(data, scheduleStart, horizonDays),
    [data, scheduleStart, horizonDays],
  )
  const stats = data.stats || {}

  const describeEquip = (b: ProcessBar): string => {
    if (b.process === '整经') return b.machine_display || '整经计划池'
    if (b.process === '穿综穿筘') return b.resource_id || '待定穿综资源'
    if (b.process === '织造准备') return b.loom_id || b.resource_id || '待定织机'
    if (b.process === '织造') return b.loom_id || '待定织机'
    return b.machine_id || '待定水洗机'
  }

  const barText = (b: ProcessBar): string => {
    if (b.process === '整经') return `${b.product_id || b.warp_beam_sku || ''} ${fmt(b.plan_meters)}米/${fmt(b.plan_count)}轴`
    if (b.process === '穿综穿筘') return `${b.product_id || ''} ${b.beam_id || ''}`
    if (b.process === '织造准备') return `${b.product_id || ''} ${b.setup_label || '织造准备'}`
    if (b.process === '织造') return `${b.loom_id || ''} ${b.product_id || b.weaving_sku || ''} ${fmt(b.quantity)}米`
    return `${b.machine_id || ''} ${b.washing_sku || ''} ${fmt(b.plan_length)}米`
  }

  const barMeta = (b: ProcessBar): string => {
    const parts: string[] = []
    if (b.process === '整经') {
      if (b.target_loom_ids?.length) parts.push(`相关目标织机 ${b.target_loom_ids.join('、')}`)
      if (b.warp_beam_sku) parts.push(`经轴品番 ${b.warp_beam_sku}`)
    }
    if (b.derived) parts.push('推导数据')
    if (b.chain_incomplete) parts.push(b.chain_status || '工艺链待补充')
    if (b.process === '整经') parts.push(b.machine_display || '整经计划池')
    if (b.time_source) {
      if (data.view_mode === 'executable') {
        const sourceLabel: Record<ProcessName, string> = {
          整经: '最终整经计划', 穿综穿筘: '最终穿综事件', 织造准备: '最终准备事件',
          织造: '逐轴校验通过', 水洗: '最终水洗事件',
        }
        parts.push(sourceLabel[b.process])
      } else {
        parts.push(b.process === '整经' || b.process === '水洗' ? '推导(非CP-SAT)' : 'CP-SAT初排')
      }
    }
    return parts.join(' ')
  }

  const processes = data.process_order?.length ? data.process_order : data.groups.map(g => g.process)
  const allBars = data.groups.flatMap(group => group.bars)
  const filteredBars = allBars.filter(b => !filter || JSON.stringify(b).toLowerCase().includes(filter.toLowerCase()))
  const dateAt = (index: number) => {
    const d = new Date(base); d.setUTCDate(base.getUTCDate() + index)
    return d.toISOString().slice(0, 10)
  }
  const cellBars = (date: string, process: ProcessName) => dailySlices(filteredBars, date)
    .filter(slice => slice.bar.process === process)
    .sort((a, b) => String(a.bar.start).localeCompare(String(b.bar.start)))

  const openDrawer = (b: ProcessBar) => setSelected(b)

  return (
    <div className="process-gantt" data-testid="process-gantt">
      <div className="pg-toolbar">
        <span className="pg-title">工艺流程排程矩阵</span>
        <span className="pg-note">时间为竖轴，工艺流程为横轴</span>
        <span className="pg-note">时间单位：天（共 {days} 天）</span>
        <span className="pg-note">{data.note}</span>
      </div>
      <div className="pg-sequence" data-testid="process-sequence">
        工艺顺序：整经完成 → 穿综穿筘 → 织造准备/上轴 → 织造完成 → 水洗
      </div>
      {data.order_warnings?.length > 0 && (
        <div className="pg-warn" data-testid="process-order-warning">
          工艺顺序异常：{data.order_warnings.join('；')}
        </div>
      )}
      <div className="pg-stats">
        <Stat label="产品主档" value={stats.master_product_count} />
        <Stat label="整经任务" value={stats.warp_task_count} />
        <Stat label="穿综穿筘" value={stats.threading_task_count} />
        <Stat label="织造准备" value={stats.setup_task_count} />
        <Stat label="经轴品番" value={stats.warp_beam_sku_count} />
        <Stat label="相关目标织机" value={stats.target_loom_count} />
        <Stat label="织造任务" value={stats.weave_task_count} />
        <Stat label="水洗任务" value={stats.wash_task_count} />
        <Stat label="虚拟经轴" value={stats.virtual_beam_count} />
        <Stat label="整经资源模式" value="计划池" />
        <Stat label="完整串联" value={stats.chain_full_count} />
        <Stat label="待补链路" value={stats.chain_broken_count} />
      </div>
      {data.chain_broken_reasons && Object.keys(data.chain_broken_reasons).length > 0 && (
        <div className="pg-warn">
          无法串联 共 {stats.chain_broken_count ?? 0} 条：
          {Object.entries(data.chain_broken_reasons).map(([k, v]) => `${k} ${v} 条`).join('，')}。
          下列产品存在缺失映射，页面保留产品与织造任务，不自动猜值：{' '}
          {data.product_reconciliation?.filter((r: any) => r.status !== '完整串联').map((r: any) => `${r.product_id}（${r.status}）`).join('、') || '无'}
        </div>
      )}
      <div className="pg-legend">
        <span className="pg-legend-item"><i className="dot" style={{ background: PROC_COLOR['整经'] }} /> 整经：{data.view_mode === 'executable' ? '最终执行计划（含明确补排）' : '来源表计划（推导，非CP-SAT约束）'}</span>
        {data.view_mode === 'executable' && <span className="pg-legend-item"><i className="dot" style={{ background: PROC_COLOR['穿综穿筘'] }} /> 穿综/准备：工况模拟的最终执行事件</span>}
        <span className="pg-legend-item"><i className="dot" style={{ background: PROC_COLOR['织造'] }} /> 织造：{data.view_mode === 'executable' ? '逐轴联动校验后的可执行区段' : data.view_mode === 'invalid' ? '执行校验未通过，暂不展示' : 'CP-SAT初排（尚未逐轴校验）'}</span>
        <span className="pg-legend-item"><i className="dot" style={{ background: PROC_COLOR['水洗'] }} /> 水洗：{data.view_mode === 'executable' ? '仅展示工况模拟实际生成的事件' : '来源表参考计划'}</span>
        <span className="pg-legend-item"><b>推导</b> 表示虚拟经轴或推导数据</span>
      </div>
      {(data.unmatched_washing_rows?.length ?? 0) > 0 && (
        <div className="pg-warn">
          水洗计划中有 {data.unmatched_washing_rows!.length} 条记录未匹配正式水洗品番，已放入待核对区，未作为正式甘特条展示。
        </div>
      )}
      <div className="pg-search">
        <label>筛选
          <input value={filter} placeholder="品番 / 织机 / 经轴 / 批号"
            onChange={e => setFilter(e.target.value)} />
        </label>
      </div>

      <div className="pg-process-matrix-wrap" data-testid="pg-timeline">
        <div className="pg-process-matrix" style={{ gridTemplateColumns: `112px repeat(${processes.length}, minmax(210px, 1fr))` }}>
          <div className="pg-matrix-corner">时间 ↓ / 工艺 →</div>
          {processes.map(process => (
            <div className="pg-matrix-head" key={process} style={{ background: PROC_COLOR[process] }}>
              <b>{process}</b><span>{PROC_LABEL[process]}</span>
            </div>
          ))}
          {Array.from({ length: days }, (_, index) => {
            const date = dateAt(index)
            return <React.Fragment key={date}>
              <div className="pg-matrix-date" data-testid="pg-tick">
                <b>{weekday(date)}</b><span>{date.slice(5)}</span>
              </div>
              {processes.map(process => {
                const bars = cellBars(date, process)
                return <div className="pg-matrix-cell" key={`${date}-${process}`} data-testid={`pg-cell-${date}-${process}`}>
                  {bars.map((slice, i) => (
                    <button key={`${slice.bar.bar_id}-${i}`} className={'pg-flow-card' + (slice.bar.derived ? ' derived' : '')}
                      style={{ borderLeftColor: PROC_COLOR[slice.bar.process] }} title={`${barText(slice.bar)} ${barMeta(slice.bar)}`}
                      onClick={() => openDrawer(slice.bar)} data-testid="pg-bar">
                      <span className="pg-flow-time">{slice.continuesBefore ? '续 ' : ''}{slice.displayStart}—{slice.displayEnd}{slice.continuesAfter ? ' 续' : ''}</span>
                      <b>{barText(slice.bar)}</b><small>{describeEquip(slice.bar)} {barMeta(slice.bar)}</small>
                    </button>
                  ))}
                  {bars.length === 0 && <span className="pg-cell-empty">—</span>}
                </div>
              })}
            </React.Fragment>
          })}
        </div>
      </div>

      <ProductChainTable rows={data.product_reconciliation || []} />

      {selected && (
        <div className="pg-drawer" data-testid="pg-drawer">
          <div className="pg-drawer-head">
            <b>{barText(selected)}</b>
            <button className="pg-drawer-close" onClick={() => setSelected(null)}>×</button>
          </div>
          <div className="pg-drawer-body">
            {selected.process === '整经' && <WarpDetail b={selected} />}
            {(selected.process === '穿综穿筘' || selected.process === '织造准备') && <ExecutionDetail b={selected} />}
            {selected.process === '织造' && <WeaveDetail b={selected} />}
            {selected.process === '水洗' && <WashDetail b={selected} />}
          </div>
        </div>
      )}
    </div>
  )
}

interface DaySlice {
  bar: ProcessBar
  displayStart: string
  displayEnd: string
  continuesBefore: boolean
  continuesAfter: boolean
}

/** 与工况模拟一致：跨天事件在每个实际占用的日历日显示。 */
export function dailySlices(bars: ProcessBar[], date: string): DaySlice[] {
  const dayStart = Date.parse(`${date}T00:00:00Z`)
  const dayEnd = dayStart + 1440 * 60_000
  return bars.flatMap(bar => {
    const start = parseUtc(bar.start)
    const end = parseUtc(bar.end, true)
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= dayEnd || end <= dayStart) return []
    return [{
      bar,
      displayStart: start < dayStart ? '00:00' : clock(bar.start),
      displayEnd: end >= dayEnd ? '24:00' : clock(bar.end),
      continuesBefore: start < dayStart,
      continuesAfter: end > dayEnd,
    }]
  })
}

function parseUtc(value: string | null | undefined, endBoundary = false): number {
  if (!value) return Number.NaN
  const text = String(value)
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(text)
  const normalized = dateOnly ? `${text}T00:00:00Z`
    : /[zZ]|[+-]\d\d:\d\d$/.test(text) ? text : `${text}Z`
  const parsed = Date.parse(normalized)
  return endBoundary && dateOnly ? parsed + 1440 * 60_000 : parsed
}

function Row({ k, v }: { k: string; v: any }) {
  return <div className="pg-detail-row"><span>{k}</span><b>{v ?? '—'}</b></div>
}

function WarpDetail({ b }: { b: ProcessBar }) {
  return (
    <div className="pg-detail">
      <Row k="经轴品番" v={b.warp_beam_sku} />
      <Row k="计划米数" v={fmt(b.plan_meters)} />
      <Row k="计划轴数" v={fmt(b.plan_count)} />
      <Row k="经轴编号" v={b.beam_instance_ids?.join('、') || b.beam_id} />
      <Row k="经轴规格" v={b.warp_spec} />
      <Row k="相关目标织机" v={b.target_loom_ids?.join('、')} />
      <Row k="整经资源" v={b.machine_display || '整经计划池'} />
      <Row k="来源单元格" v={b.source_cell} />
      <Row k="数据来源" v={b.data_source} />
    </div>
  )
}

function ExecutionDetail({ b }: { b: ProcessBar }) {
  return <div className="pg-detail">
    <Row k="工序" v={b.process} />
    <Row k="产品" v={b.product_id} />
    <Row k="经轴" v={b.beam_id} />
    <Row k="资源/织机" v={b.resource_id || b.loom_id} />
    <Row k="仕挂类型" v={b.setup_label} />
    <Row k="起止" v={`${b.start} ~ ${b.end}`} />
    <Row k="数据来源" v={b.data_source} />
  </div>
}

function WeaveDetail({ b }: { b: ProcessBar }) {
  return (
    <div className="pg-detail">
      <Row k="织机编号" v={b.loom_id} />
      <Row k="流程编号" v={b.flow_id} />
      <Row k="产品" v={b.product_id} />
      <Row k="产品背番号" v={b.product_back_sku || '待建档'} />
      <Row k="织造品番" v={b.weaving_sku} />
      <Row k="经轴品番" v={b.warp_beam_sku || '待建档'} />
      <Row k="经轴实例" v={b.beam_instance_id || b.beam_id} />
      <Row k="水洗品番" v={b.washing_sku || '待建档'} />
      <Row k="工艺链状态" v={b.chain_status} />
      <Row k="缺失字段" v={b.chain_missing_fields?.join('、') || '无'} />
      <Row k="映射说明" v={b.chain_reason} />
      <Row k="数量(米)" v={fmt(b.quantity)} />
      <Row k="起止" v={`${b.start} ~ ${b.end}`} />
      <Row k="数据来源" v={b.data_source} />
    </div>
  )
}

function ProductChainTable({ rows }: { rows: NonNullable<ProcessGanttResult['product_reconciliation']> }) {
  return (
    <details className="section-card" data-testid="product-chain-audit" open>
      <summary>产品工艺链对账（{rows.length} 个基础产品）</summary>
      <div className="tasks-table-wrap">
        <table className="summary-table">
          <thead><tr>
            <th>产品</th><th>流程编号</th><th>产品背番号</th><th>经轴品番</th>
            <th>织造品番</th><th>水洗品番</th><th>目标织机</th><th>状态</th><th>说明</th>
          </tr></thead>
          <tbody>{rows.map(r => (
            <tr key={r.flow_id} className={r.publishable ? '' : 'warn-cell'}>
              <td>{r.product_id}</td><td>{r.flow_id}</td>
              <td>{r.product_back_sku || '待建档'}</td>
              <td>{r.warp_beam_sku || '待建档'}</td>
              <td>{r.weaving_sku || '待建档'}</td>
              <td>{r.washing_sku || '待建档'}</td>
              <td>{r.target_loom_ids?.join('、') || '—'}</td>
              <td>{r.status}</td><td>{r.reason}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </details>
  )
}

function WashDetail({ b }: { b: ProcessBar }) {
  return (
    <div className="pg-detail">
      <Row k="水洗设备编号" v={b.machine_id} />
      <Row k="水洗品番" v={b.washing_sku} />
      <Row k="批号" v={b.batch_code} />
      <Row k="计划长度(米)" v={fmt(b.plan_length)} />
      <Row k="投入长度(米)" v={fmt(b.input_length)} />
      <Row k="起止" v={`${b.start} ~ ${b.end}`} />
      <Row k="数据来源" v={b.data_source} />
    </div>
  )
}

function computeRange(data: ProcessGanttResult, scheduleStart?: string, horizonDays = 7): { base: Date; days: number } {
  const requestedDays = Math.max(1, Math.floor(horizonDays || 7))
  if (isFullDate(scheduleStart)) {
    return { base: new Date(`${scheduleStart!.slice(0, 10)}T00:00:00Z`), days: requestedDays }
  }
  const starts: string[] = []
  const ends: string[] = []
  for (const g of data.groups) {
    for (const b of g.bars) {
      if (isFullDate(b.start)) starts.push(b.start!)
      if (isFullDate(b.end)) ends.push(b.end!)
    }
  }
  if (!starts.length) {
    return { base: new Date('2026-04-01T00:00:00Z'), days: requestedDays }
  }
  starts.sort()
  ends.sort()
  const base = new Date(`${starts[0].slice(0, 10)}T00:00:00Z`)
  return { base, days: requestedDays }
}

function isFullDate(s: string | null | undefined): boolean {
  return !!s && /^\d{4}-\d{2}-\d{2}/.test(s)
}

function clock(value: string | null | undefined): string {
  if (!value) return '—'
  const text = String(value)
  return text.includes('T') ? text.slice(11, 16) : text.slice(5, 10)
}

function weekday(date: string): string {
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(`${date}T00:00:00Z`).getUTCDay()]
}

function Stat({ label, value }: { label: string; value: number | string | undefined }) {
  return <span className="pg-stat"><b>{value ?? '—'}</b> {label}</span>
}

function fmt(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toLocaleString()
}
