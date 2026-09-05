import React, { useEffect, useMemo, useState } from 'react'
import { runWeeklySimulation } from '../api'
import type { ExecutionPreview } from '../types'

const SETUP_LABELS: Record<string, string> = {
  direct_continue: '线边余轴直接续产',
  beam_joining: '同品番接经',
  original_style_setup: '原品番仕挂',
  change_style_setup: '改品番仕挂',
}

export default function SimulationPanel({ scheduleId, initialData }: { scheduleId?: string; initialData?: ExecutionPreview }) {
  const [data, setData] = useState<any>(initialData ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = () => {
    setLoading(true); setError(null)
    runWeeklySimulation({ schedule_id: scheduleId })
      .then(setData).catch(e => setError(String(e?.message || e))).finally(() => setLoading(false))
  }
  useEffect(() => {
    if (initialData) {
      setData(initialData)
      setError(null)
      return
    }
    run()
  }, [scheduleId, initialData])

  const days = useMemo(() => {
    if (!data?.schedule_start) return []
    // 只处理日历日，避免浏览器所在时区把 04-01 00:00 换算成前一天。
    const startDate = String(data.schedule_start).slice(0, 10)
    const start = new Date(`${startDate}T00:00:00Z`)
    return Array.from({ length: 7 }, (_, offset) => {
      const d = new Date(start); d.setUTCDate(start.getUTCDate() + offset)
      const date = d.toISOString().slice(0, 10)
      const dayStart = offset * 1440
      const dayEnd = dayStart + 1440
      // 跨天事件必须在占用到的每个日历日显示，而不是只落在开始日。
      const events = (data.events ?? [])
        .filter((e: any) => Number(e.start_minute) < dayEnd && Number(e.end_minute) > dayStart)
        .map((e: any) => ({
          ...e,
          display_start: Number(e.start_minute) < dayStart ? '00:00' : clock(e.start),
          display_end: Number(e.end_minute) >= dayEnd ? '24:00' : clock(e.end),
          continues_before: Number(e.start_minute) < dayStart,
          continues_after: Number(e.end_minute) > dayEnd,
        }))
      return { date, events, weaving: events.filter((e: any) => e.event_type === 'weaving') }
    })
  }, [data])

  if (loading && !data) return <div className="empty-state">正在展开整经—穿综穿筘—仕挂—织造事件…</div>
  if (error && !data) return <div className="error-banner">模拟失败：{error}</div>
  if (!data) return <div className="empty-state">请先运行一周排程。</div>

  const kpi = data.kpi ?? {}
  const counts = kpi.setup_type_counts ?? {}
  return <div className="simulation-page" data-testid="simulation-page">
    <div className="simulation-head">
      <div><h3>一周滚动工况模拟</h3><p className="muted">基于排程 {data.solver_summary?.schedule_id}，按工艺顺序展开可执行事件。</p></div>
      <button className="primary" onClick={run} disabled={loading}>{loading ? '正在刷新…' : '刷新已保存结果'}</button>
    </div>
    {error && <div className="error-banner">刷新失败：{error}</div>}
    <div className={`simulation-audit ${Number(kpi.reduced_quantity || 0) > 0 ? 'adjusted' : 'ok'}`} data-testid="simulation-audit">
      <b>可执行性对账：</b>整经来源为本次一周整经计划，织造共绑定 {kpi.beam_bound_segment_count ?? 0} 个逐轴区段；
      所有事件限制在七天内。{Number(kpi.reduced_quantity || 0) > 0
        ? ` 因经轴或时间不足，已明确缩减 ${fmt(kpi.reduced_quantity)} 米。`
        : ' 经轴数量、提前期和周期边界均已通过。'}
    </div>
    <div className="warps-stats">
      <Stat label="模拟状态" value={data.status} />
      <Stat label="求解已排" value={`${fmt(kpi.solver_scheduled_quantity)} 米`} />
      <Stat label="模拟产量" value={`${fmt(kpi.simulated_quantity)} 米`} />
      <Stat label="安全缩减" value={`${fmt(kpi.reduced_quantity)} 米`} />
      <Stat label="整经事件" value={`${kpi.warping_task_count ?? 0} 个`} />
      <Stat label="补排整经" value={`${kpi.supplemental_warping_count ?? 0} 个`} />
      <Stat label="穿综穿筘" value={`${kpi.threading_task_count ?? 0} 个`} />
      <Stat label="织造准备" value={`${kpi.setup_segment_count ?? 0} 个`} />
      <Stat label="校验" value={data.validation?.ok ? '通过' : '异常'} />
    </div>

    {data.planning_trace && <PlanningTrace trace={data.planning_trace} />}

    <section className="warps-section"><h4>时间为竖轴，工艺流程为横轴（一周7天）</h4>
      <div className="simulation-flow-wrap">
        <div className="simulation-flow-grid">
          <div className="simulation-flow-corner">时间 ↓ / 工艺 →</div>
          {SIM_STAGES.map(stage => <div className="simulation-flow-head" key={stage.key}>{stage.label}</div>)}
          {days.map((d: any) => <React.Fragment key={d.date}>
            <div className="simulation-flow-date"><b>{weekday(d.date)}</b><span>{d.date.slice(5)}</span></div>
            {SIM_STAGES.map(stage => {
              const events = d.events.filter((e: any) => stage.types.includes(e.event_type))
              return <div className="simulation-flow-cell" key={`${d.date}-${stage.key}`}>
                {events.map((e: any, index: number) => <div className={`simulation-event event-${e.event_type}`} key={`${e.event_id || e.event_type}-${d.date}-${index}`}>
                  <span>{e.continues_before ? '续 ' : ''}{e.display_start}—{e.display_end}{e.continues_after ? ' 续' : ''}</span><b>{e.product_id || e.label}</b><small>{e.resource_id}</small>
                </div>)}
                {events.length === 0 && <span className="pg-cell-empty">—</span>}
              </div>
            })}
          </React.Fragment>)}
        </div>
      </div>
    </section>

    <section className="warps-section"><h4>四种仕挂判定</h4>
      <div className="setup-grid">{Object.entries(SETUP_LABELS).map(([key, label]) =>
        <div className="setup-card" key={key}><span>{label}</span><b>{counts[key] ?? 0} 段</b></div>)}</div>
    </section>

    <section className="warps-section"><h4>24 / 48 小时工况预测</h4>
      <div className="forecast-grid">{(data.forecasts ?? []).map((f: any) =>
        <div className="forecast-card" key={f.cutoff_minutes}><b>{f.cutoff_minutes / 60} 小时</b>
          <strong>{fmt(f.produced_meters)} 米</strong>
          <span>织造 {f.loom_state_count?.['织造'] ?? 0} 台 / 准备 {f.loom_state_count?.['准备'] ?? 0} 台 / 停机 {f.loom_state_count?.['停机'] ?? 0} 台</span>
        </div>)}</div>
    </section>

    <section className="warps-section"><h4>上游准备计划</h4>
      <div className="simulation-table-wrap"><table className="summary-table simulation-table">
        <thead><tr><th>工序</th><th>产品</th><th>经轴</th><th>经轴来源</th><th>资源</th><th>开始</th><th>结束</th><th>对应织机</th></tr></thead>
        <tbody>{[...(data.warping_plan ?? []), ...(data.threading_plan ?? []), ...(data.loom_setup_plan ?? [])]
          .sort((a: any, b: any) => a.start_minute - b.start_minute).map((e: any, i: number) =>
          <tr key={`${e.event_type}-${i}`}><td>{e.process}</td><td>{e.product_id}</td><td>{e.beam_id}</td><td>{beamOrigin(e.beam_origin)}</td><td>{e.resource_id}</td>
            <td>{dateTime(e.start)}</td><td>{dateTime(e.end)}</td><td>{e.loom_id || '—'}</td></tr>)}</tbody>
      </table></div>
    </section>
    <p className="process-sequence-note">{(data.assumptions ?? []).join('；')}</p>
  </div>
}

function PlanningTrace({ trace }: { trace: any }) {
  return <section className="warps-section planning-trace" data-testid="planning-trace">
    <h4>订单驱动的整经—织造联动决策</h4>
    <p className="process-sequence-note">计划逻辑：先按订单要求形成织造初排，再拆分逐轴需求并反推整经；生产现场仍严格按整经→穿综/上轴→织造执行。</p>
    <div className="planning-pipeline">
      {(trace.stages ?? []).map((stage: any, index: number) => <React.Fragment key={stage.key}>
        <div className={`planning-stage stage-${stage.key}`}>
          <span>{index + 1}</span><b>{stage.label}</b><strong>{stage.value}</strong><small>{stage.detail}</small>
        </div>
        {index < (trace.stages?.length ?? 0) - 1 && <i className="planning-arrow">→</i>}
      </React.Fragment>)}
    </div>
    <div className="planning-rules">{(trace.rules ?? []).map((rule: string, index: number) =>
      <span key={rule}><b>{index + 1}</b>{rule}</span>)}</div>
    <h5>订单逐段执行明细</h5>
    <div className="simulation-table-wrap"><table className="summary-table planning-decision-table">
      <thead><tr><th>订单/产品</th><th>交期/优先级</th><th>织造初排</th><th>经轴需求</th><th>实际轴号</th><th>织机</th><th>到位/最晚到位</th><th>实际织造</th><th>可执行/缩减</th><th>结论</th></tr></thead>
      <tbody>{(trace.decisions ?? []).map((row: any, index: number) => <tr key={`${row.task_id}-${row.loom_id}-${index}`}>
        <td><b>{row.order_id}</b><br/><small>{row.product_id}</small></td>
        <td>{fullDate(row.due_at)}<br/><small>优先级 {fmt(row.priority)}</small></td>
        <td>{fmt(row.requested_quantity)} 米<br/><small>{row.split_allowed ? '允许拆单' : '不可拆单'}</small></td>
        <td>{row.warp_beam_sku || '未建档'}<br/><small>{row.required_beam_count == null ? '根数待确认' : `${row.required_beam_count} 根`}</small></td>
        <td>{row.beam_ids?.join('、') || '—'}<br/><small>{(row.beam_origins ?? []).map(beamOrigin).join('、') || '—'}</small></td>
        <td>{row.loom_id || '—'}</td>
        <td className={row.lead_time_ok ? 'status-ok' : 'status-bad'}>{dateTime(row.beam_ready_at)}<br/><small>最晚 {dateTime(row.required_ready_by)}</small></td>
        <td>{dateTime(row.first_weave_start)}<br/><small>至 {dateTime(row.last_weave_end)}</small></td>
        <td>{fmt(row.executable_quantity)} 米<br/><small>缩减 {fmt(row.reduced_quantity)} 米</small></td>
        <td className={row.status === '可执行' ? 'status-ok' : 'status-bad'}><b>{row.status}</b><br/><small>{row.reason}</small></td>
      </tr>)}</tbody>
    </table></div>
  </section>
}

function Stat({ label, value }: { label: string; value: any }) { return <span className="pg-stat"><b>{value}</b> {label}</span> }
function fmt(value: any) { return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 1 }) }
function dateTime(value: any) { return value ? String(value).replace('T', ' ').slice(5, 16) : '—' }
function fullDate(value: any) { return value ? String(value).replace('T', ' ').slice(0, 16) : '待确认' }
function weekday(date: string) { return ['周日','周一','周二','周三','周四','周五','周六'][new Date(`${date}T00:00:00Z`).getUTCDay()] }
function clock(value: any) { const text = String(value || ''); return text.includes('T') ? text.slice(11, 16) : '—' }
function beamOrigin(value: any) { return ({ weekly_warping_plan: '一周整经计划', supplemental_warping: '补排整经', shopfloor_snapshot: '期初车间台账', initial_inventory: '期初库存' } as Record<string,string>)[String(value || '')] || '—' }

const SIM_STAGES = [
  { key: 'warping', label: '整经', types: ['warping'] },
  { key: 'threading', label: '穿综穿筘', types: ['threading'] },
  { key: 'setup', label: '织造准备', types: ['loom_setup'] },
  { key: 'weaving', label: '织造', types: ['weaving'] },
  { key: 'washing', label: '水洗', types: ['washing'] },
]
