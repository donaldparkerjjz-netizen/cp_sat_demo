import { useMemo, useState } from 'react'
import type { ScheduleResult } from '../types'

export type RuleAuditStatus = '符合' | '部分符合' | '不符合' | '无法验证'

export interface RuleAuditItem {
  id: string
  group: '核心规则' | '可选滚动规则'
  title: string
  requirement: string
  status: RuleAuditStatus
  risk: '高' | '中' | '低'
  evidence: string
  action: string
}

export interface RuleAuditSummary {
  scheduleId: string
  items: RuleAuditItem[]
  counts: Record<RuleAuditStatus, number>
  criticalNotice: string | null
  optimizationNote: string | null
}

const STATUSES: RuleAuditStatus[] = ['符合', '部分符合', '不符合', '无法验证']

export function buildRuleAudit(result: ScheduleResult): RuleAuditSummary {
  const raw = result as any
  const finalSchedule = raw.final_schedule || {}
  const execution = result.execution_preview || finalSchedule.execution || {}
  const assignments: any[] = finalSchedule.assignments || result.assignments || []
  const warpingPlan = finalSchedule.warping_plan || raw.warping_plan || {}
  const warpingTasks: any[] = warpingPlan.tasks || (Array.isArray(execution.warping_plan) ? execution.warping_plan : [])
  const events: any[] = execution.events || []
  const checks: any[] = execution.validation?.checks || result.validation?.checks || []
  const decisions: any[] = execution.planning_trace?.decisions || []
  const forecasts: any[] = execution.forecasts || []
  const kpi: any = finalSchedule.kpi || result.kpi || {}
  const params = raw.params || {}
  const snapshot = finalSchedule.input_shopfloor_snapshot || raw.input_shopfloor_snapshot || execution.shopfloor_snapshot || {}
  const targetAudit = raw.target_loom_audit || finalSchedule.target_loom_audit || {}
  const unscheduled: any[] = finalSchedule.unscheduled || result.unscheduled || []
  const simulationBasis = finalSchedule.weaving_plan?.simulation_basis || {}
  const simulationConfig = finalSchedule.simulation_config || execution.simulation_config || {}
  const ruleOptimization = raw.rule_optimization || finalSchedule.rule_optimization || {}
  const rollPlan: any[] = finalSchedule.roll_plan || raw.roll_plan || []

  const sum = (rows: any[], key: string) => rows.reduce((total, row) => total + Number(row?.[key] || 0), 0)
  const n = (value: unknown, digits = 1) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
  const passed = (name: string) => checks.some(check => check.check === name && check.pass === true)
  const required = Number(kpi.required_quantity || 0)
  const scheduled = Number(kpi.scheduled_quantity || 0)
  const coverage = required > 0 ? scheduled / required : 0
  const warpMeters = sum(warpingTasks, 'plan_meters')
  const boundCount = assignments.filter(a => a.beam_id).length
  const materialEnabled = params.enable_material_constraint ?? result.provenance?.material_enabled ?? false
  const beamEnabled = params.enable_beam_constraint ?? result.provenance?.beam_enabled ?? false
  const materialRows = unscheduled.filter(row => (row.reason_codes || []).includes('MATERIAL_SHORTAGE'))
  const materialMeters = materialRows.reduce((total, row) => {
    const part = (row.reason_breakdown || []).find((x: any) => x.reason_code === 'MATERIAL_SHORTAGE')
    return total + Number(part?.quantity ?? (row.primary_reason === 'MATERIAL_SHORTAGE' ? row.unscheduled_quantity : 0) ?? 0)
  }, 0)
  const matchedTargets = Number(targetAudit.matched_assignment_count ?? assignments.filter(a => a.source_target_match === true).length)
  const missingTargets = Number(targetAudit.missing_target_assignment_count ?? simulationBasis.target_loom_missing_count ?? assignments.filter(a => a.target_mapping_status === 'missing_trial').length)
  const publishable = simulationBasis.publishable ?? targetAudit.publishable
  const horizonDays = Number(kpi.horizon_days || result.provenance?.horizon_days || 0)
  const dueDates = decisions.map(row => String(row.due_at || '').slice(0, 10)).filter(Boolean)
  const dueInsideWindow = dueDates.some(date => date >= result.schedule_start.slice(0, 10) && date < result.schedule_end.slice(0, 10))
  const changeStyleCount = assignments.filter(a => a.changeover_type === 'change_style_setup').length
  const continuityCount = assignments.filter(a => ['direct_continue', 'beam_joining', 'original_style_setup'].includes(a.changeover_type)).length
  const objectiveNames = (result.objective_levels || []).map(x => String(x.name || '').toLowerCase())
  const hasChangeoverObjective = objectiveNames.some(name => name.includes('change') || name.includes('setup'))
  const styleAssignments = assignments.filter(a => a.changeover_type === 'change_style_setup')
  const styleChainsOk = styleAssignments.length > 0 && styleAssignments.every(a => {
    const threading = events.find(e => e.event_type === 'threading' && e.task_id === a.task_id && e.beam_id === a.beam_id)
    const setup = events.find(e => e.event_type === 'loom_setup' && e.task_id === a.task_id && e.beam_id === a.beam_id)
    const weaving = events.find(e => e.event_type === 'weaving' && e.task_id === a.task_id && e.beam_id === a.beam_id)
    return threading && setup && weaving && Number(threading.end_minute) <= Number(setup.start_minute) && Number(setup.end_minute) <= Number(weaving.start_minute)
  })
  const hasThreading = events.some(e => e.event_type === 'threading')
  const hasDowntime = events.some(e => e.event_type === 'downtime') || Number(snapshot.unavailable_loom_count || 0) > 0 || Number(snapshot.delayed_loom_count || 0) > 0
  const hasQualityEvent = events.some(e => String(e.event_type || '').includes('quality'))
  const hasOrderChangeEvent = events.some(e => ['rush_order', 'order_cancelled', 'order_changed'].includes(e.event_type))
  const allThreePlans = warpingTasks.length > 0 && hasThreading && assignments.length > 0
  const hasFixedParams = Number(simulationConfig.warping_minutes_per_beam || 0) > 0 && Number(simulationConfig.threading_minutes || 0) > 0
  const rollRows = rollPlan.length ? rollPlan : assignments.filter(a => Array.isArray(a.rolls) && a.rolls.length > 0)
  const hasRollPlan = rollRows.length > 0 && rollRows.every(row => {
    const rolls = row.rolls || []
    return rolls.length >= 4 && rolls.length <= 5 && rolls.every((roll: any) => Number(roll.planned_meters || 0) >= 800 && Number(roll.planned_meters || 0) <= 1000)
  })
  const usedBeamIds = new Set(assignments.map(a => String(a.beam_id || '')).filter(Boolean))
  const plannedBeamIds = warpingTasks.map(row => String(row.beam_instance_id || row.beam_id || '')).filter(Boolean)
  const unreferencedBeamCount = plannedBeamIds.filter(id => !usedBeamIds.has(id)).length
  const warpingAligned = Boolean(warpingPlan.alignment?.optimized || ruleOptimization.warping_alignment?.optimized)
  const hasWarehouseEvents = events.some(e => ['threaded_beam_inbound', 'threaded_beam_outbound'].includes(e.event_type))
  const hasFinalRemainingBeam = Boolean(finalSchedule.final_runtime_states || execution.final_runtime_states)

  const items: RuleAuditItem[] = [
    item('R01', '核心规则', '工艺顺序', '最终计划遵循整经→穿综穿筘→仕挂→织造的先后顺序。',
      passed('warping_no_overlap') && passed('threading_no_overlap') && passed('loom_no_overlap') ? '符合' : events.length ? '不符合' : '无法验证', '高',
      events.length ? `当前有${warpingTasks.length}段整经、${events.filter(e => e.event_type === 'threading').length}段穿综、${assignments.length}段织造；三类资源不重叠校验${passed('loom_no_overlap') && passed('warping_no_overlap') && passed('threading_no_overlap') ? '通过' : '未全部通过'}。` : '当前结果没有完整执行事件，无法核验工艺顺序。',
      '任一工艺链断裂或资源重叠时阻断发布。'),
    item('R02', '核心规则', '织造拉动整经和穿综', '上游计划应由最终可执行织造量向前拉动，避免脱离织造大量备轴。',
      !warpingTasks.length || !assignments.length ? '无法验证' : warpingAligned && unreferencedBeamCount === 0 ? '符合' : unreferencedBeamCount === 0 ? '部分符合' : '不符合', '高',
      warpingTasks.length ? `一周整经${n(warpMeters)}米/${warpingTasks.length}轴，最终织造${n(scheduled)}米/${assignments.length}段；${unreferencedBeamCount}根计划轴未被本周最终织造引用。整根经轴未织完的米数计入期末余轴。` : '没有可对账的一周整经计划。',
      '最终织造确定后反推整经；安全库存和额外备轴必须单独说明原因。'),
    item('R03', '核心规则', '月计划拆分到周计划', '月度主计划按周交期形成周生产计划，再配置织机台数。',
      horizonDays !== 7 ? '不符合' : dueInsideWindow ? '符合' : '部分符合', '高',
      `当前窗口${horizonDays || '—'}天，需求${n(required)}米、最终排入${n(scheduled)}米，需求覆盖率${(coverage * 100).toFixed(2)}%；${dueInsideWindow ? '存在本周交期任务' : '未看到落在本周窗口内的订单交期'}。`,
      '增加本周应交量、期初欠交和下周预排字段，周覆盖率只使用本周应交需求。'),
    item('R04', '核心规则', '订单、库存和安全库存形成净需求', '客户订单、库存和安全库存应共同决定主计划。',
      '无法验证', '高', '当前结果未提供订单→成品库存→安全库存→净需求的逐品番来源链。', '补齐订单号、交期、成品库存、安全库存、净需求及来源字段。'),
    item('R05', '核心规则', '原材料默认充足', '按原文件的简化计算口径，默认原材料充足。',
      !materialEnabled ? '符合' : '部分符合', '高',
      materialEnabled ? `本次物料约束已开启，${materialRows.length}个任务约${n(materialMeters)}米受到物料不足影响；这是比原文件“默认充足”更严格的扩展口径，不作为算法违规。` : '本次物料约束关闭，符合文件的简化假设。',
      '若采用真实物料约束，应明确标记为扩展口径；否则关闭物料约束后重新求解。'),
    item('R06', '核心规则', '产品—织机候选与工艺适配', '根据订单量分配织机，并满足产品试织机台和工装适配要求。',
      assignments.length === 0 ? '无法验证' : missingTargets === 0 && matchedTargets === assignments.length ? '符合' : matchedTargets === 0 ? '不符合' : '部分符合', '高',
      `最终${assignments.length}段中${matchedTargets}段命中来源目标机台，${missingTargets}段缺少试织映射；可发布=${publishable == null ? '未判定' : String(publishable)}。`,
      '补齐产品—可用织机—工装矩阵；缺失映射时阻断发布或走人工例外审批。'),
    item('R07', '核心规则', '按周交期完成', '优先满足每周交货期，并保证数量。',
      coverage >= 0.999 && dueInsideWindow ? '符合' : scheduled > 0 ? '部分符合' : '不符合', '高',
      `已排部分按期率${((Number(kpi.on_time_rate || 0)) * 100).toFixed(1)}%，按全部需求计算的按期率${((Number(kpi.on_time_demand_rate || 0)) * 100).toFixed(2)}%。`,
      '同时展示“已排段按期率”和“本周应交满足率”，不能用前者替代后者。'),
    item('R08', '核心规则', '减少换机和仕挂停机', '在交期和产能约束下尽量减少换机、调整和停机。',
      hasChangeoverObjective ? '符合' : '部分符合', '中',
      `最终${assignments.length}段中改品番仕挂${changeStyleCount}次；${hasChangeoverObjective ? '目标层包含换型/仕挂优化' : '求解目标清单未明确展示换型优化层'}。`,
      '把换型次数和停机分钟作为可解释目标，并显示相对基线的改善量。'),
    item('R09', '核心规则', '同品番连续生产', '织机已有固定品番时，应尽量延续同品番生产。',
      continuityCount > 0 ? '符合' : '无法验证', '中', `本次最终结果出现${continuityCount}段连续/接经/原品番仕挂场景。`, '补充“当前品番与待排品番相同”的验收场景。'),
    item('R10', '核心规则', '边撑次数决定接经或原品番仕挂', '同品番边撑次数小于5时接经；达到5次时原品番仕挂。',
      assignments.some(a => ['beam_joining', 'original_style_setup'].includes(a.changeover_type)) ? '部分符合' : '无法验证', '中',
      `边撑上限=${simulationConfig.edge_support_use_limit ?? 5}；本次接经${assignments.filter(a => a.changeover_type === 'beam_joining').length}段、原品番仕挂${assignments.filter(a => a.changeover_type === 'original_style_setup').length}段。`,
      '用边撑次数4和5两组场景验证边界行为。'),
    item('R11', '核心规则', '改品番完整准备链', '改品番必须经过穿综穿筘、仕挂，再开始织造。',
      styleAssignments.length === 0 ? '无法验证' : styleChainsOk ? '符合' : '不符合', '高',
      styleAssignments.length ? `${styleAssignments.length}/${styleAssignments.length}段改品番任务${styleChainsOk ? '具有完整且顺序正确的穿综→仕挂→织造事件' : '未形成完整顺序事件'}。` : '本次没有改品番任务。',
      '把改品番事件链完整性作为发布硬约束。'),
    item('R12', '核心规则', '经轴长度与数量容量', '按产品设置经轴长度，织造数量不得超过绑定经轴容量。',
      boundCount === assignments.length && passed('beam_quantity_capacity') ? '符合' : assignments.length ? '不符合' : '无法验证', '高',
      `${boundCount}/${assignments.length}段绑定具体经轴；经轴容量校验${passed('beam_quantity_capacity') ? '通过' : '未通过或无证据'}。`,
      '缺少产品经轴设定长度时禁止使用默认值发布。'),
    item('R13', '核心规则', '落布4—5匹、每匹800—1000米', '通常每轴落布4—5次，每匹约800—1000米。',
      hasRollPlan ? '符合' : '不符合', '中', hasRollPlan ? `当前已为${rollRows.length}根投用经轴生成4—5匹、每匹800—1000米的匹级计划；本周未织完部分保留为后续待织。` : '当前只输出任务/经轴级米数，没有匹号、落布次数和每匹米数。', '增加落布子任务和匹级质量追溯。'),
    item('R14', '核心规则', '经轴FIFO领用', '经轴入库后按先进先出顺序领用上机。',
      passed('beam_fifo') ? '符合' : passed('beam_source_traceability') ? '部分符合' : '无法验证', '中',
      passed('beam_source_traceability') ? '经轴来源可追溯，但当前校验清单没有显式FIFO顺序检查。' : '没有足够证据核验FIFO。',
      '增加同SKU经轴候选排序、FIFO校验和人工例外原因。'),
    item('R15', '核心规则', '织轴提前2小时到位', '织轴在上机/了机前至少2小时准备完成。',
      passed('beam_ready_lead_time') ? '符合' : assignments.length ? '不符合' : '无法验证', '高',
      `提前期参数=${simulationConfig.lead_time_minutes ?? 120}分钟；校验${passed('beam_ready_lead_time') ? '通过' : '未通过或无证据'}。`,
      '页面区分整经完成、穿综完成、最晚准备时间和上机时间。'),
    item('R16', '核心规则', '织轴库入库与领用', '常规经轴穿综穿筘后进入织轴库，再等待领用上机。',
      hasWarehouseEvents ? '符合' : hasThreading ? '部分符合' : '无法验证', '中',
      hasWarehouseEvents ? '当前已有织轴库入库/出库事件。' : '已排穿综穿筘，但没有独立的织轴库入库、库位和出库状态。',
      '新增织轴库台账和入库/领用事件。'),
    item('R17', '核心规则', '余轴作为线边库存继承', '未织完经轴留在织机上，供下次同品番继续生产。',
      hasFinalRemainingBeam ? '部分符合' : Number(snapshot.loom_with_remaining_beam_count || 0) > 0 ? '部分符合' : '无法验证', '中',
      `输入快照记录${snapshot.loom_with_remaining_beam_count ?? '—'}台织机有余轴；${hasFinalRemainingBeam ? '系统保存了期末运行状态，但页面未逐轴展示' : '当前未见可核验的期末余轴继承明细'}。`,
      '最终排程显示期末余轴、所在织机和下周期继承状态。'),
    item('R18', '核心规则', '固定产能、效率和日生产时间', '织机、整经和穿综穿筘采用固定产能参数进行模拟。',
      hasFixedParams ? '符合' : '部分符合', '中',
      hasFixedParams ? `整经${simulationConfig.warping_minutes_per_beam}分钟/轴、穿综${simulationConfig.threading_minutes}分钟/轴。` : '当前未完整展示整经和穿综的固定工时参数。',
      '客户确认真实速度、效率、班次和停机日历后替换模拟参数。'),
    item('R19', '核心规则', '同步输出三类计划', '同时形成整经、穿综穿筘和织造计划。',
      allThreePlans ? '符合' : '不符合', '高', `整经${warpingTasks.length}段、穿综${events.filter(e => e.event_type === 'threading').length}段、织造${assignments.length}段。`, '三类计划必须使用同一排程编号并一起冻结发布。'),
    item('R20', '核心规则', '未来1天、2天预测', '输出未来1天和2天的产量、资源、交期与备轴预测。',
      forecasts.length >= 2 ? '符合' : forecasts.length ? '部分符合' : '不符合', '中', `当前生成${forecasts.length}个预测窗口：${forecasts.map(x => `${Number(x.cutoff_minutes || 0) / 60}小时`).join('、') || '无'}。`, '补充交期风险和经轴缺口预测。'),
    item('R21', '可选滚动规则', '故障和维修触发重排', '设备故障或维修时更新状态并调整后续计划。',
      hasDowntime ? '部分符合' : '无法验证', '中', hasDowntime ? `停机/不可用信息已进入当前结果，但本次未展示事件发生前后的滚动重排版本差异。` : '本次没有故障或维修场景。', '增加故障注入→冻结已开工→重排未开工任务测试。'),
    item('R22', '可选滚动规则', '工装和物料就绪触发重排', '盘头、综筘、原料等未到位时更新状态并重排。',
      materialEnabled || beamEnabled ? '部分符合' : '无法验证', '中', `物料约束${materialEnabled ? '开启' : '关闭'}，经轴约束${beamEnabled ? '开启' : '关闭'}；异常后的自动重排闭环尚无本次证据。`, '记录资源预计到位时间，并在状态变化后自动重排。'),
    item('R23', '可选滚动规则', '插单、退单和订单变更', '插单、退单、数量或交期变化后更新主计划并重排。',
      hasOrderChangeEvent ? '部分符合' : '无法验证', '中', hasOrderChangeEvent ? '当前存在订单变更事件，但尚需对比重排前后影响。' : '当前结果没有订单变更事件。', '增加插单、退单、数量和交期变更回归场景。'),
    item('R24', '可选滚动规则', '质量异常影响排程', '质量异常时更新状态并处理隔离、返工、报废或放行。',
      hasQualityEvent ? '部分符合' : '无法验证', '中', hasQualityEvent ? '当前存在质量事件，但闭环处理仍需核验。' : '当前结果没有质量异常进入排程。', '建立质量状态机和数量处置规则。'),
  ]

  const counts = Object.fromEntries(STATUSES.map(status => [status, items.filter(item => item.status === status).length])) as Record<RuleAuditStatus, number>
  const snapshotDate = String(snapshot.captured_at || '').slice(0, 10)
  const criticalNotice = snapshotDate && snapshotDate > result.schedule_start.slice(0, 10)
    ? `数据时点提醒：${snapshotDate}的现场快照晚于排程开始日${result.schedule_start.slice(0, 10)}，当前结果只能作为模拟，不应直接发布。`
    : null
  return { scheduleId: result.schedule_id, items, counts, criticalNotice, optimizationNote: ruleOptimization.enabled ? String(ruleOptimization.note || '本次排程已执行规则优化。') : null }
}

function item(id: string, group: RuleAuditItem['group'], title: string, requirement: string, status: RuleAuditStatus, risk: RuleAuditItem['risk'], evidence: string, action: string): RuleAuditItem {
  return { id, group, title, requirement, status, risk, evidence, action }
}

export function RuleAuditDrawer({ audit, open, onClose }: { audit: RuleAuditSummary | null; open: boolean; onClose: () => void }) {
  const [filter, setFilter] = useState<'全部' | RuleAuditStatus>('全部')
  const visible = useMemo(() => audit?.items.filter(item => filter === '全部' || item.status === filter) || [], [audit, filter])
  if (!audit || !open) return null

  return (
    <>
      <button className="rule-audit-backdrop" aria-label="关闭规则自查" onClick={onClose} />
      <aside className="rule-audit-drawer" role="dialog" aria-modal="true" aria-label="规则自查明细" data-testid="rule-audit-drawer">
        <header className="rule-audit-head">
          <div><h3>规则自查</h3><p>排程 {audit.scheduleId} · 依据《织造排产问题求解》逐条核验</p></div>
          <button className="rule-audit-close" onClick={onClose} aria-label="关闭">×</button>
        </header>
        <div className="rule-audit-body">
          {audit.criticalNotice && <div className="rule-audit-notice">{audit.criticalNotice}</div>}
          {audit.optimizationNote && <div className="rule-audit-optimized">{audit.optimizationNote}</div>}
          <div className="rule-audit-counts">
            {STATUSES.map(status => <button key={status} className={`rule-count status-${status} ${filter === status ? 'active' : ''}`} onClick={() => setFilter(filter === status ? '全部' : status)}>
              <b>{audit.counts[status]}</b><span>{status}</span>
            </button>)}
          </div>
          <div className="rule-audit-filter">
            <span>当前显示：{filter}</span>
            {filter !== '全部' && <button onClick={() => setFilter('全部')}>显示全部24条</button>}
          </div>
          {(['核心规则', '可选滚动规则'] as const).map(group => {
            const rows = visible.filter(item => item.group === group)
            if (!rows.length) return null
            return <section key={group} className="rule-audit-group"><h4>{group}</h4>
              {rows.map(row => <details key={row.id} className={`rule-audit-item audit-${row.status}`} open={row.status === '不符合'}>
                <summary>
                  <span className="rule-id">{row.id}</span>
                  <span className="rule-title">{row.title}</span>
                  <span className={`rule-risk risk-${row.risk}`}>{row.risk}风险</span>
                  <span className="rule-status">{row.status}</span>
                </summary>
                <div className="rule-audit-detail">
                  <p><b>规则要求</b>{row.requirement}</p>
                  <p><b>当前证据</b>{row.evidence}</p>
                  <p><b>建议动作</b>{row.action}</p>
                </div>
              </details>)}
            </section>
          })}
        </div>
      </aside>
    </>
  )
}
