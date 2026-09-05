import React, { useMemo, useState } from 'react'
import type { Assignment, BusinessStatus, ScheduleResult, SolverStatus } from '../types'

export function StatusBadges({ solver, business }: { solver: SolverStatus; business: BusinessStatus }) {
  return (
    <div className="status-badges" data-testid="status">
      <span className={`badge solver s-${solver}`}>算法状态：{solver}</span>
      <span className={`badge business b-${business}`}>业务状态：{business}</span>
    </div>
  )
}

const KPI_DEFS: { key: string; label: string; tip: string; fmt: (v: any) => string; prominent?: boolean }[] = [
  { key: 'demand_coverage_rate', label: '需求覆盖率', tip: '已排 / 需求（业务第一优先指标）', fmt: v => pct(v), prominent: true },
  { key: 'unscheduled_quantity', label: '未排数量', tip: '未排米数（越低越好）', fmt: v => fmtNum(v), prominent: true },
  { key: 'scheduled_quantity', label: '已排数量', tip: '已排米数', fmt: v => fmtNum(v) },
  { key: 'required_quantity', label: '需求总量', tip: '全部生产任务需求米数', fmt: v => fmtNum(v) },
  { key: 'on_time_demand_rate', label: '全部需求准交率', tip: '准时 / 需求（更贴近业务整体）', fmt: v => pct(v), prominent: true },
  { key: 'on_time_rate', label: '已排任务准交率', tip: '准时 / 已排（分母仅为已排数量，易偏高）', fmt: v => pct(v) },
  { key: 'used_loom_utilization', label: '已启用织机利用率', tip: '计划占用分钟 / 实际启用织机可用分钟', fmt: v => pct(v) },
  { key: 'used_loom_count', label: '使用织机数', tip: '有排程任务的织机数', fmt: v => v },
  { key: 'changeover_count', label: '换款次数', tip: '换产品/工艺次数', fmt: v => v },
  { key: 'beam_change_count', label: '换轴次数', tip: '换经轴次数', fmt: v => v },
  { key: 'threading_count', label: '穿综穿筘次数', tip: '穿综穿筘次数', fmt: v => v },
  { key: 'total_delay_minutes', label: '总延误', tip: 'Σ max(0, 完成-交期) 分钟', fmt: v => fmtNum(v) },
  { key: 'max_lateness_minutes', label: '最大延误', tip: '所有任务延误最大值(可点击定位任务)', fmt: v => fmtNum(v) + ' 分钟' },
]

export function KpiCards({ kpi, onMaxDelay, scope = 'solver' }: { kpi: any; onMaxDelay: () => void; scope?: 'solver' | 'executable' }) {
  // 兼容历史排程结果：新结果优先采用已启用织机口径；旧结果回退到全厂口径。
  const displayKpi = {
    ...kpi,
    used_loom_utilization: kpi.used_loom_utilization ?? kpi.utilization,
    used_loom_available_minutes: kpi.used_loom_available_minutes ?? kpi.available_machine_minutes,
    fleet_utilization: kpi.fleet_utilization ?? kpi.utilization,
  }
  const labels: Record<string, string> = scope === 'executable' ? {
    demand_coverage_rate: '最终需求覆盖率',
    unscheduled_quantity: '最终未排数量',
    scheduled_quantity: '最终可执行数量',
    on_time_demand_rate: '最终需求准交率',
    on_time_rate: '可执行计划准交率',
    used_loom_utilization: '可执行织机利用率',
    used_loom_count: '最终使用织机数',
    beam_change_count: '最终换轴次数',
  } : {}
  return (
    <div className="kpi-grid" data-testid="kpi">
      {scope === 'executable' && <div className="kpi-scope-note" data-testid="kpi-scope">主业务口径：逐轴校验后的最终可执行计划</div>}
      {KPI_DEFS.map(d => (
        <div className={'kpi-card' + (d.prominent ? ' prominent' : '')} key={d.key} title={d.tip}>
          <div className="kpi-label">{labels[d.key] || d.label}</div>
          <div className="kpi-value">{d.fmt(displayKpi[d.key])}</div>
          {d.key === 'max_lateness_minutes' ? (
            <button className="kpi-link" onClick={onMaxDelay}>点击定位任务</button>
          ) : null}
        </div>
      ))}
      <div className="kpi-card kpi-wide" title={scope === 'executable' ? '可执行织造占用/最终使用织机周期总时间' : '计划占用/实际启用织机可用时间'}>
        <div className="kpi-label">利用率口径</div>
        <div className="kpi-sub">{scope === 'executable' ? '可执行织造占用' : '计划占用'} {fmtNum(displayKpi.scheduled_machine_minutes)} 分钟 / {scope === 'executable' ? '最终使用织机周期' : '已启用织机可用'} {fmtNum(displayKpi.used_loom_available_minutes)} 分钟；全厂织机利用率 {pct(displayKpi.fleet_utilization)}</div>
      </div>
    </div>
  )
}

const REASON_LABEL: Record<string, string> = {
  NO_COMPATIBLE_LOOM: '无兼容织机', TOOLING_MISMATCH: '工装不匹配', NO_AVAILABLE_BEAM: '经轴不足',
  MATERIAL_SHORTAGE: '物料不足', OUTSIDE_HORIZON: '排程周期不足', LOCK_CONFLICT: '锁定冲突',
  MIN_BATCH_NOT_MET: '最小批量不足', CAPACITY_SHORTAGE: '产能不足', INVALID_DUE_DATE: '非法交期',
  MISSING_MASTER_DATA: '主数据缺失', UNKNOWN: '其他',
}

export function UnscheduledPanel({ result, onSelectReason }: { result: ScheduleResult; onSelectReason: (code?: string) => void }) {
  const total = result.kpi.unscheduled_quantity
  const groups = result.diagnostics.unscheduled_reason_summary || []
  const fullCount = result.diagnostics.fully_unscheduled_task_count
  const partCount = result.diagnostics.partially_unscheduled_task_count
  return (
    <div className="unscheduled-panel" data-testid="unscheduled">
      <h4>未排任务（共 {total} 米，完全未排 {fullCount}，部分未排 {partCount}）</h4>
      <p className="muted">点击原因可筛选；完全未排与部分未排状态不同。</p>
      <div className="unscheduled-groups">
        {groups.map(g => (
          <button key={g.reason_code} className="unscheduled-group" onClick={() => onSelectReason(g.reason_code)}>
            <span className="ug-label">{REASON_LABEL[g.reason_code] || g.reason_code}</span>
            <span className="ug-count">{g.task_count} 个任务</span>
            <span className="ug-qty">{fmtNum(g.quantity)} 米</span>
            <span className="ug-pct">{total ? Math.round((g.quantity / total) * 100) : 0}%</span>
          </button>
        ))}
        {groups.length === 0 && <div className="muted">暂无未排任务</div>}
      </div>
      <div className="unscheduled-list">
        {result.unscheduled.filter(u => u.unscheduled_quantity > 0).map(u => (
          <div key={u.task_id} className={'us-item ' + (u.scheduled_quantity > 0 ? 'partial' : 'full')}>
            <span className="us-task">{u.task_id}（{REASON_CN[u.primary_reason] || u.primary_reason || '—'}）</span>
            <span>需 {fmtNum(u.required_quantity)} 米，已排 {fmtNum(u.scheduled_quantity)} 米，未排 {fmtNum(u.unscheduled_quantity)} 米{assignUnit(u)}</span>
            <span className="muted">候选织机 {u.candidate_loom_count ?? 0} 台，窗口内理论可用产能 {fmtNum(u.theoretical_capacity)} 米</span>
            {u.primary_reason && <span className="muted">{u.business_text}</span>}
            <details className="tech-info"><summary>技术信息</summary>
              <span>{u.reason_codes?.join('，')}</span>
            </details>
          </div>
        ))}
      </div>
    </div>
  )
}

export function DiagnosticsPanel({ result }: { result: ScheduleResult }) {
  const [compare, setCompare] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const runCompare = async () => {
    setBusy(true)
    try {
      const { diagnosticCompare } = await import('../api')
      const r = await diagnosticCompare({ max_time_s: 8, compatibility_mode: result.diagnostics.compatibility_mode })
      setCompare(r)
    } finally { setBusy(false) }
  }
  return (
    <div className="diagnostics-panel" data-testid="diagnostics">
      <h4>求解诊断</h4>
      <div className="model-stats">变量 {result.model_stats.num_variables}，约束 {result.model_stats.num_constraints}，线程 {result.model_stats.num_workers}，每层 {result.model_stats.per_layer_time_s}s</div>
      <table className="diagnostics-table">
        <thead><tr><th>层</th><th>目标</th><th>best_value</th><th>best_bound</th><th>gap</th><th>状态</th></tr></thead>
        <tbody>
          {result.objective_levels.map(l => (
            <tr key={l.level} data-testid={`level-${l.name}`}>
              <td>L{l.level}</td><td>{l.name}</td><td>{l.best_value}</td><td>{l.best_bound}</td>
              <td>{l.gap}</td><td className={l.status === 'OPTIMAL' ? 'ok' : 'warn'}>{l.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={runCompare} disabled={busy}>运行动态 A/B/C/D 对照（仅供诊断，不可发布）</button>
      {compare && (
        <div data-testid="compare" className={'compare ' + (compare.all_comparable ? 'ok' : 'warn')}>
          <p>{compare.note}</p>
          <p>{compare.conclusion}</p>
          <table><thead><tr><th>方案</th><th>已排</th><th>未排</th><th>覆盖</th><th>使用机台</th><th>利用率</th><th>solver</th><th>gap</th><th>comparison</th></tr></thead>
            <tbody>{compare.schemes.map((s: any) => (
              <tr key={s.scheme}><td>{s.scheme}</td><td>{s.scheduled_quantity}</td><td>{s.unscheduled_quantity}</td>
                <td>{pct(s.demand_coverage_rate)}</td><td>{s.used_loom_count}</td><td>{pct(s.utilization)}</td>
                <td>{s.solver_status}</td><td>{s.gap}</td><td>{s.comparison_status}</td></tr>
            ))}</tbody></table>
        </div>
      )}
    </div>
  )
}

export function WarningsPanel({ scenario, onOpenQuality }: { scenario: any; onOpenQuality: () => void }) {
  const blocked = scenario?.data_errors?.length ?? 0
  const warnings = scenario?.data_warnings?.length ?? 0
  const info = scenario?.data_info?.length ?? 0
  return (
    <div className={'warnings-panel compact ' + (blocked ? 'blocked' : '')} data-testid="warnings">
      <span><b>当前输入数据质量：</b>{blocked} 阻断、{warnings} 警告、{info} 提示</span>
      {(blocked > 0 || warnings > 0) && <small>包含待确认、推导或模拟数据，仅用于原型验证。</small>}
      <button onClick={onOpenQuality}>查看数据质量</button>
    </div>
  )
}

export function TaskDrawer({ assignment, result, onClose }: { assignment: Assignment | null; result: ScheduleResult; onClose: () => void }) {
  const diag = useMemo(() => {
    if (!assignment) return null
    return result.diagnostics.task_diagnostics.find(d => d.task_id === assignment.task_id) || null
  }, [assignment, result])
  return (
    <div className={'drawer' + (assignment ? ' open' : '')} data-testid="drawer">
      <div className="drawer-head">
        <h4>任务详情{assignment ? ` / ${assignment.task_id}` : ''}</h4>
        <button onClick={onClose}>×</button>
      </div>
      {assignment && (
        <div className="drawer-body">
          <div className="kv"><span>产品</span><b>{assignment.product_id}</b></div>
          <div className="kv"><span>当前选择织机</span><b>{assignment.loom_id}</b></div>
          <div className="kv"><span>经轴</span><b>{assignment.beam_id || '—'}</b></div>
          <div className="kv"><span>份序号</span><b>{assignment.part_index}</b></div>
          <div className="kv"><span>已排/未排</span><b>{fmtNum(assignment.scheduled_quantity)} / {fmtNum(diag?.unscheduled_quantity || 0)}</b></div>
          <div className="kv"><span>起止</span><b>{assignment.start} → {assignment.end}</b></div>
          <div className="kv"><span>逾期</span><b>{assignment.lateness_minutes} 分钟</b></div>
          <div className="kv"><span>锁定</span><b>{assignment.locked ? assignment.lock_reason : '否'}</b></div>
          <div className="kv"><span>换款</span><b>{diag?.is_style_change ? '是' : '否'}</b></div>
          <div className="kv"><span>换轴</span><b>{diag?.is_beam_change ? '是' : '否'}</b></div>
          <div className="kv"><span>穿综穿筘</span><b>{diag?.is_threading ? '是' : '否'}</b></div>
          <div className="kv"><span>候选织机数量</span><b>{diag?.candidate_loom_count ?? 0} 台</b></div>
          <div className="kv"><span>前10台候选</span><b>{((diag?.top10_candidate_looms || []) as string[]).slice(0, 10).join('，') || '—'}</b></div>
          <div className="kv"><span>排除织机数量</span><b>{diag?.excluded_loom_count ?? 0} 台</b></div>
          <div className="kv"><span>被排除原因</span><b>{renderExclusion(diag)}</b></div>
          <div className="kv"><span>主因/次因</span><b>{diag?.primary_reason ? REASON_CN[diag.primary_reason] : '—'} / {(diag?.secondary_reasons || []).map(r => REASON_CN[r]).join('，') || '—'}</b></div>
          <div className="kv"><span>数据来源</span><b>推导（月度预测/样例）</b></div>
          <div className="kv"><span>临时参数</span><b>是（上轴330/穿筘480等）</b></div>
          <h5>排程解释</h5>
          <ul className="explain">
            <li>选择该织机：{assignment.loom_id} 在候选清单内且满足适配。</li>
            <li>候选织机 {diag?.candidate_loom_count ?? 0} 台（共 {diag?.all_loom_count ?? 0} 台可用），已排除 {diag?.excluded_loom_count ?? 0} 台。</li>
            <li>是否受物料限制：{diag?.secondary_reasons?.includes('MATERIAL_SHORTAGE') || diag?.missing_material?.missing_kg ? '是' : '否'}</li>
            <li>是否受经轴限制：{diag?.secondary_reasons?.includes('NO_AVAILABLE_BEAM') ? '是' : '否'}</li>
            <li>是否换款：{diag?.is_style_change ? '是' : '否'}；换轴：{diag?.is_beam_change ? '是' : '否'}；穿综穿筘：{diag?.is_threading ? '是' : '否'}</li>
          </ul>
        </div>
      )}
    </div>
  )
}

function fmtNum(v: any): string { return v == null ? '—' : Number(v).toLocaleString() }
function pct(v: any): string { return v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%` }

const REASON_CN: Record<string, string> = {
  NO_COMPATIBLE_LOOM: '无兼容织机', TOOLING_MISMATCH: '工装不匹配', NO_AVAILABLE_BEAM: '经轴不足',
  MATERIAL_SHORTAGE: '物料不足', OUTSIDE_HORIZON: '排程周期不足', LOCK_CONFLICT: '锁定冲突',
  MIN_BATCH_NOT_MET: '最小批量不足', CAPACITY_SHORTAGE: '产能不足', INVALID_DUE_DATE: '非法交期',
  MISSING_MASTER_DATA: '主数据缺失', UNKNOWN: '其他',
}

function renderExclusion(diag: any): string {
  const c = diag?.exclusion_reason_categories || {}
  const parts: string[] = []
  if (c.product_rule) parts.push(`产品规则 ${c.product_rule}`)
  if (c.tooling_rule) parts.push(`工装 ${c.tooling_rule}`)
  if (c.calendar) parts.push(`日历 ${c.calendar}`)
  if (c.lock) parts.push(`锁定 ${c.lock}`)
  if (c.beam) parts.push(`经轴 ${c.beam}`)
  if (c.material) parts.push(`物料 ${c.material}`)
  if (c.horizon) parts.push(`周期 ${c.horizon}`)
  return parts.length ? parts.join('，') : '—'
}

function assignUnit(u: any): string {
  const mm = u.missing_material || {}
  if (mm.missing_kg != null && mm.missing_kg > 0) {
    return `，缺料 ${mm.material_code} ${fmtNum(mm.missing_kg)} kg`
  }
  return ''
}
