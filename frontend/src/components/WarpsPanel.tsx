import React, { useEffect, useMemo, useState } from 'react'
import { getWarpingBeams, getWarpingInstances, getWarpingInventory, getWeeklyWarpingPlan } from '../api'
import type { WarpBeamsResult, WarpInstancesResult, WarpInventoryResult, WeeklyWarpingPlan } from '../types'

/** 经轴与整经数据页：只负责整经计划、经轴主档、实例与库存。 */
export default function WarpsPanel({ executionPreview, onOpenSimulation = () => {} }: { executionPreview?: any; onOpenSimulation?: () => void }) {
  const [beams, setBeams] = useState<WarpBeamsResult | null>(null)
  const [instances, setInstances] = useState<WarpInstancesResult | null>(null)
  const [inventory, setInventory] = useState<WarpInventoryResult | null>(null)
  const [weekly, setWeekly] = useState<WeeklyWarpingPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([getWarpingBeams(), getWarpingInstances(), getWarpingInventory(), getWeeklyWarpingPlan()])
      .then(([b, i, v, w]) => { setBeams(b); setInstances(i); setInventory(v); setWeekly(w); setError(null) })
      .catch(e => setError(String(e?.message || e)))
      .finally(() => setLoading(false))
  }, [])

  // 统计(纯计算，钩子须在 early return 之前以保持钩子顺序一致)
  const beamSkuCount = beams?.count ?? 0
  const realCount = instances?.real_count ?? 0
  const virtualCount = instances?.virtual_count ?? 0
  const sourceTaskCount = useMemo(() => {
    // 整经任务数：从经轴品番的 plan_dates 汇总
    return (beams?.beams ?? []).reduce((s, b) => s + b.plan_dates.length, 0)
  }, [beams])
  const taskCount = weekly?.stats.task_count ?? sourceTaskCount
  const targetLoomCount = useMemo(() => {
    const set = new Set<string>()
    for (const b of beams?.beams ?? []) b.target_loom_ids.forEach(l => set.add(l))
    return set.size
  }, [beams])
  if (loading) return <div className="empty-state">正在加载经轴与整经数据</div>
  if (error) return <div className="error-banner" data-testid="warps-error">加载失败：{error}</div>

  return (
    <div className="warps-page" data-testid="warps-page">
      <div className="warps-stats">
        <Stat label="经轴品番" value={`${beamSkuCount} 类`} />
        <Stat label="实体经轴" value={`${realCount} 根`} />
        <Stat label="虚拟经轴" value={`${virtualCount} 根`} />
        <Stat label="整经任务" value={`${taskCount} 个`} />
        <Stat label="相关目标织机" value={`${targetLoomCount} 台`} />
        <Stat label="整经资源" value="计划池" />
      </div>
      {instances?.note && <p className="muted">{instances.note}</p>}

      <Section title={`本周整经计划（${shortDate(weekly?.schedule_start)}—${shortDate(weekly?.schedule_end, true)}）`} testid="warps-weekly-plan">
        <div className="warping-week-summary">
          <Stat label="计划经轴" value={`${weekly?.stats.plan_count ?? 0} 根`} />
          <Stat label="计划米数" value={`${fmt(weekly?.stats.plan_meters)} 米`} />
          <Stat label="经轴品番" value={`${weekly?.stats.beam_sku_count ?? 0} 类`} />
          <Stat label="计划池利用率" value={`${Math.round((weekly?.stats.utilization ?? 0) * 100)}%`} />
          <Stat label="单轴模拟工时" value={`${weekly?.minutes_per_beam ?? 0} 分钟`} />
        </div>
        <div className="warping-week-days" aria-label="一周整经日计划">
          {(weekly?.daily ?? []).map(d => (
            <div className={'warping-day' + (d.task_count ? ' active' : '')} key={d.date} data-testid="warping-day">
              <b>{weekday(d.date)}</b><span>{d.date.slice(5)}</span>
              <strong>{d.plan_count} 根</strong><small>{fmt(d.plan_meters)} 米</small>
            </div>
          ))}
        </div>
        <p className="process-sequence-note">执行顺序：整经完成 → 经轴上轴 → 织造；本表的“完成时间”已作为后续织造最早开始约束。</p>
        <table className="summary-table weekly-warping-table">
          <thead><tr><th>顺序</th><th>订单交期/优先级</th><th>日期</th><th>时间</th><th>经轴品番</th><th>经轴实例</th><th>对应产品</th><th>计划</th><th>完成时间</th><th>相关目标织机</th><th>排产依据</th><th>资源</th></tr></thead>
          <tbody>
            {(weekly?.tasks ?? []).map(t => (
              <tr key={t.task_id} data-testid="weekly-warping-row">
                <td>{t.sequence}</td><td>{t.order_due_date ? t.order_due_date.slice(0, 10) : '待确认'} / {fmt(t.order_priority)}</td><td>{t.plan_date}</td><td>{clock(t.start)}—{clock(t.end)}</td>
                <td><b>{t.warp_beam_sku}</b></td><td>{t.beam_instance_id ?? '—'}</td><td>{t.product_ids.join('、') || '—'}</td>
                <td>{fmt(t.plan_meters)} 米 / {t.plan_count} 根</td><td>{dateTime(t.complete_at)}</td>
                <td>{t.target_loom_id.join('、') || '—'}</td><td>{t.planning_basis || '订单需求反推'}</td><td>{t.machine_placeholder}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(weekly?.unscheduled.length ?? 0) > 0 && <p className="error-banner">本周计划池容量不足：还有 {weekly?.unscheduled.length} 类经轴未排完。</p>}
        {(weekly?.blocked_products.length ?? 0) > 0 && <p className="muted">缺少经轴品番映射、暂不能进入整经计划：{weekly?.blocked_products.join('、')}</p>}
        <p className="muted">模拟口径：{weekly?.assumptions.join('；')}</p>
      </Section>

      <Section title="织造衔接摘要" testid="weaving-handoff-summary">
        {executionPreview?.planning_trace ? <>
          <div className="warping-week-summary">
            <Stat label="初排织造" value={`${fmt(executionPreview.kpi?.solver_scheduled_quantity)} 米`} />
            <Stat label="可执行织造" value={`${fmt(executionPreview.kpi?.simulated_quantity)} 米`} />
            <Stat label="本周缩减" value={`${fmt(executionPreview.kpi?.reduced_quantity)} 米`} />
            <Stat label="绑定经轴段" value={`${executionPreview.kpi?.beam_bound_segment_count ?? 0} 段`} />
            <Stat label="补排整经" value={`${executionPreview.kpi?.supplemental_warping_count ?? 0} 根`} />
          </div>
          <p className="process-sequence-note">本页只确认整经和经轴准备情况。最终织造时间、实际轴号、缩减原因及七天工艺事件统一在“工况模拟”查看。</p>
        </> : <p className="muted">尚无本次排程的织造衔接结果，请先运行一周排程。</p>}
        <button className="primary" onClick={onOpenSimulation}>查看执行仿真</button>
      </Section>

      <Section title="经轴品番主档" testid="warps-sku">
        <table className="summary-table">
          <thead>
            <tr><th>品番</th><th>设定米数</th><th>整经根数</th><th>钢筘</th><th>使用纱线</th><th>单耗(KG)</th></tr>
          </thead>
          <tbody>
            {(beams?.beams ?? []).map(b => (
              <tr key={b.warp_beam_sku}>
                <td>{b.warp_beam_sku}</td>
                <td>{fmt(b.set_length)}</td>
                <td>{fmt(b.warp_threads)}</td>
                <td>{b.reed ?? '—'}</td>
                <td>{b.yarn_code ?? '—'}</td>
                <td>{fmt(b.unit_consumption_kg)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="经轴实例" testid="warps-instances">
        <table className="summary-table">
          <thead>
            <tr><th>虚拟经轴编号</th><th>品番</th><th>计划日期</th><th>米数</th><th>状态</th><th>相关目标织机</th><th>数据来源</th></tr>
          </thead>
          <tbody>
            {(instances?.instances ?? []).map(i => (
              <tr key={i.beam_instance_id}>
                <td>{i.beam_instance_id}</td>
                <td>{i.warp_beam_sku}</td>
                <td>{i.plan_date}</td>
                <td>{fmt(i.instance_meters)}</td>
                <td>{i.status}</td>
                <td>{(i.target_loom_id ?? []).join('、') || '—'}</td>
                <td>{i.data_source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="经轴库存" testid="warps-inventory">
        {(inventory?.inventory ?? []).map(row => (
          <div key={row.warp_beam_sku} className="warp-inv">
            <div className="warp-inv-head">
              <b>{row.warp_beam_sku}</b>
              <span className="muted">初始库存 {fmt(row.initial_inventory)}</span>
              {row.anomaly_dates.length > 0 && (
                <span className="warp-inv-anomaly" data-testid="inv-anomaly">
                  异常日期 {row.anomaly_dates.join('、')}
                </span>
              )}
            </div>
            <div className="warp-inv-strip">
              {row.daily.length === 0
                ? <span className="muted">无整经计划/织造上轴需求记录</span>
                : row.daily.map(d => (
                  <span key={d.date} className={'warp-inv-day' + (d.stock_m < 0 ? ' neg' : '')} title={`${d.date} 整经${d.warp_complete_m} 上轴需求${d.weave_mount_demand_m} 结存${d.stock_m}`}>
                    <i>{d.date.slice(5)}</i>
                    <b>{d.stock_m}</b>
                  </span>
                ))}
            </div>
          </div>
        ))}
      </Section>
    </div>
  )
}

function Section({ title, children, testid }: { title: string; children: React.ReactNode; testid?: string }) {
  return (
    <section className="warps-section" data-testid={testid}>
      <h4>{title}</h4>
      {children}
    </section>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return <span className="pg-stat" data-testid={`warps-stat-${label}`}><b>{value}</b> {label}</span>
}

function fmt(v: number | null | undefined): string {
  return v == null ? '—' : Number(v).toLocaleString()
}

function shortDate(value?: string, exclusiveEnd = false): string {
  if (!value) return '—'
  const d = new Date(`${value.slice(0, 10)}T00:00:00`)
  if (exclusiveEnd) d.setDate(d.getDate() - 1)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function weekday(value: string): string {
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(`${value}T00:00:00`).getDay()]
}

function clock(value: string): string { return value.slice(11, 16) }
function dateTime(value: string): string { return `${value.slice(5, 10)} ${clock(value)}` }
