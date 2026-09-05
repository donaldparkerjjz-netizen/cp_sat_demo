import type { Assignment, Kpi, ProcessBar, ProcessGanttResult, ScheduleResult } from './types'

export type ScheduleViewMode = 'executable' | 'invalid' | 'initial'

function isCanonicalFinal(result: ScheduleResult | null): boolean {
  return result?.result_scope === 'final_executable' && Boolean(result.final_schedule)
}

export function scheduleViewMode(result: ScheduleResult | null): ScheduleViewMode {
  if (isCanonicalFinal(result)) return result?.validation?.ok === true ? 'executable' : 'invalid'
  if (!result?.execution_preview) return 'initial'
  return result.execution_preview.validation?.ok === true ? 'executable' : 'invalid'
}

/** 将按织机甘特图切换到逐轴联动校验后的实际织造区段。 */
export function executableScheduleResult(result: ScheduleResult | null): ScheduleResult | null {
  if (isCanonicalFinal(result)) return result
  if (!result?.execution_preview) return result
  const valid = result.execution_preview.validation?.ok === true
  const events = valid && Array.isArray(result.execution_preview.weaving_plan)
    ? result.execution_preview.weaving_plan : []
  const assignments: Assignment[] = events.map((event: any, index: number) => {
    const source = result.assignments.find(a => a.task_id === event.task_id && a.loom_id === event.loom_id)
      || result.assignments.find(a => a.task_id === event.task_id)
    return {
      task_id: String(event.task_id || source?.task_id || `EXEC-${index + 1}`),
      part_index: Number(event.assignment_part_index ?? event.beam_segment_index ?? source?.part_index ?? index),
      loom_id: String(event.loom_id || event.resource_id || source?.loom_id || '待定织机'),
      product_id: String(event.product_id || source?.product_id || '待确认产品'),
      source_target_loom_ids: source?.source_target_loom_ids,
      target_mapping_status: source?.target_mapping_status,
      source_target_match: source?.source_target_match,
      beam_id: event.beam_id || source?.beam_id || null,
      start: String(event.start || source?.start || ''),
      end: String(event.end || source?.end || ''),
      start_minute: Number(event.start_minute ?? source?.start_minute ?? 0),
      end_minute: Number(event.end_minute ?? source?.end_minute ?? 0),
      scheduled_quantity: Number(event.quantity ?? source?.scheduled_quantity ?? 0),
      locked: Boolean(source?.locked),
      lock_reason: source?.lock_reason ?? null,
      changeover_type: String(event.setup_type || source?.changeover_type || 'same'),
      lateness_minutes: Number(source?.lateness_minutes || 0),
    }
  })
  return { ...result, assignments }
}

/** 主看板按逐轴校验后的可执行事件重算业务 KPI。 */
export function executableScheduleKpi(result: ScheduleResult | null): Kpi | null {
  if (!result) return null
  if (isCanonicalFinal(result)) return result.kpi
  if (!result.execution_preview) return result.kpi
  const executable = executableScheduleResult(result)
  const assignments = executable?.assignments ?? []
  const previewKpi = result.execution_preview.kpi ?? {}
  const required = Number(previewKpi.required_quantity ?? result.kpi.required_quantity ?? 0)
  const scheduled = Number(previewKpi.simulated_quantity ?? assignments.reduce((sum, a) => sum + Number(a.scheduled_quantity || 0), 0))
  const usedLooms = new Set(assignments.map(a => a.loom_id))
  const scheduledMinutes = assignments.reduce((sum, a) => sum + Math.max(0, Number(a.end_minute) - Number(a.start_minute)), 0)
  const usedAvailableMinutes = usedLooms.size * Number(result.kpi.horizon_minutes || 0)
  const lateAssignments = assignments.filter(a => Number(a.lateness_minutes || 0) > 0)
  const lateQuantity = lateAssignments.reduce((sum, a) => sum + Number(a.scheduled_quantity || 0), 0)
  const loomCounts = assignments.reduce((counts, a) => counts.set(a.loom_id, (counts.get(a.loom_id) || 0) + 1), new Map<string, number>())
  const beamChanges = Array.from(loomCounts.values()).reduce((sum, count) => sum + Math.max(0, count - 1), 0)
  const maxLate = assignments.reduce((max, a) => Math.max(max, Number(a.lateness_minutes || 0)), 0)
  const maxLateTask = assignments.find(a => Number(a.lateness_minutes || 0) === maxLate && maxLate > 0)?.task_id ?? null
  const setupCounts = previewKpi.setup_type_counts ?? {}

  return {
    ...result.kpi,
    required_quantity: required,
    scheduled_quantity: round3(scheduled),
    unscheduled_quantity: round3(Math.max(0, required - scheduled)),
    on_time_quantity: round3(Math.max(0, scheduled - lateQuantity)),
    late_quantity: round3(lateQuantity),
    demand_coverage_rate: required ? scheduled / required : 0,
    on_time_rate: scheduled ? (scheduled - lateQuantity) / scheduled : 0,
    on_time_demand_rate: required ? (scheduled - lateQuantity) / required : 0,
    scheduled_machine_minutes: scheduledMinutes,
    used_loom_available_minutes: usedAvailableMinutes,
    used_loom_utilization: usedAvailableMinutes ? scheduledMinutes / usedAvailableMinutes : 0,
    utilization: result.kpi.available_machine_minutes ? scheduledMinutes / result.kpi.available_machine_minutes : 0,
    fleet_utilization: result.kpi.available_machine_minutes ? scheduledMinutes / result.kpi.available_machine_minutes : 0,
    used_loom_count: usedLooms.size,
    task_fragment_count: assignments.length,
    single_task_loom_count: Array.from(loomCounts.values()).filter(count => count === 1).length,
    average_tasks_per_used_loom: usedLooms.size ? assignments.length / usedLooms.size : 0,
    changeover_count: Number(setupCounts.change_style_setup || 0),
    beam_change_count: beamChanges,
    threading_count: Number(previewKpi.threading_task_count || 0),
    total_lateness_minutes: Number(previewKpi.total_lateness_minutes || 0),
    total_delay_minutes: Number(previewKpi.total_lateness_minutes || 0),
    max_lateness_minutes: maxLate,
    max_delay_task_id: maxLateTask,
  }
}

export function executableProcessProgress(progress: any, result: ScheduleResult | null): any {
  if (isCanonicalFinal(result)) return progress
  if (!progress || !result?.execution_preview) return progress
  const kpi = executableScheduleKpi(result)
  if (!kpi) return progress
  return {
    ...progress,
    material_ready_qty: kpi.scheduled_quantity,
    beam_ready_qty: kpi.scheduled_quantity,
    weave_scheduled_qty: kpi.scheduled_quantity,
    note: '主看板已按逐轴校验后的最终可执行数量统一口径。',
  }
}

/** 把主看板未排明细同步到最终可执行数量；原始初排诊断仍保留在 result 中。 */
export function executableUnscheduledResult(result: ScheduleResult | null): ScheduleResult | null {
  if (isCanonicalFinal(result)) return result
  if (!result?.execution_preview) return result
  const executable = executableScheduleResult(result)
  const kpi = executableScheduleKpi(result)
  if (!executable || !kpi) return result
  const finalByTask = executable.assignments.reduce((totals, assignment) => {
    totals.set(assignment.task_id, (totals.get(assignment.task_id) || 0) + Number(assignment.scheduled_quantity || 0))
    return totals
  }, new Map<string, number>())
  const decisions: any[] = result.execution_preview.planning_trace?.decisions ?? []
  const decisionsByTask: Map<string, any[]> = decisions.reduce((groups: Map<string, any[]>, decision: any) => {
    const taskId = String(decision.task_id || '')
    if (taskId) groups.set(taskId, [...(groups.get(taskId) || []), decision])
    return groups
  }, new Map<string, any[]>())
  const sourceRows = [...result.unscheduled]
  for (const [taskId, taskDecisions] of decisionsByTask) {
    if (sourceRows.some(row => row.task_id === taskId)) continue
    const reduced = taskDecisions.reduce((sum: number, row: any) => sum + Number(row.reduced_quantity || 0), 0)
    if (reduced <= 0) continue
    const diagnostic = result.diagnostics.task_diagnostics?.find(row => row.task_id === taskId)
    const required = Number(diagnostic?.required_quantity || taskDecisions.reduce((sum: number, row: any) => sum + Number(row.requested_quantity || 0), 0))
    sourceRows.push({
      task_id: taskId,
      required_quantity: required,
      scheduled_quantity: Number(diagnostic?.scheduled_quantity || required),
      unscheduled_quantity: Number(diagnostic?.unscheduled_quantity || 0),
      reason_codes: [], primary_reason: '', secondary_reasons: [],
      business_text: '', candidate_loom_count: Number(diagnostic?.candidate_loom_count || 0),
      theoretical_capacity: Number(diagnostic?.theoretical_capacity || 0),
      missing_material: diagnostic?.missing_material || { material_code: null, missing_kg: null },
    })
  }

  const rows = sourceRows.map(row => {
    const scheduled = round3(finalByTask.get(row.task_id) || 0)
    const unscheduled = round3(Math.max(0, Number(row.required_quantity || 0) - scheduled))
    const taskDecisions = decisionsByTask.get(row.task_id) || []
    const simulationCodes: string[] = taskDecisions.filter((d: any) => Number(d.reduced_quantity || 0) > 0).map(simulationReasonCode)
    const fullyRemovedBySimulation = scheduled === 0 && Number(row.scheduled_quantity || 0) > 0 && simulationCodes.length > 0
    const primaryReason = fullyRemovedBySimulation ? simulationCodes[0] : row.primary_reason || simulationCodes[0] || 'UNKNOWN'
    const reasonCodes = Array.from(new Set([primaryReason, ...(row.reason_codes || []), ...simulationCodes].filter(Boolean)))
    const simulationReasons = taskDecisions.filter(d => Number(d.reduced_quantity || 0) > 0).map((d: any) => String(d.reason || '')).filter(Boolean)
    return {
      ...row,
      scheduled_quantity: scheduled,
      unscheduled_quantity: unscheduled,
      primary_reason: primaryReason,
      reason_codes: reasonCodes,
      secondary_reasons: Array.from(new Set([...(row.secondary_reasons || []), ...simulationCodes.filter((code: string) => code !== primaryReason)])),
      business_text: [row.business_text, ...simulationReasons].filter(Boolean).join('；'),
    }
  }).filter(row => row.unscheduled_quantity > 0)

  const grouped = rows.reduce((totals, row) => {
    const current = totals.get(row.primary_reason) || { reason_code: row.primary_reason, task_count: 0, quantity: 0 }
    current.task_count += 1
    current.quantity = round3(current.quantity + row.unscheduled_quantity)
    totals.set(row.primary_reason, current)
    return totals
  }, new Map<string, { reason_code: string; task_count: number; quantity: number }>())

  return {
    ...result,
    assignments: executable.assignments,
    kpi,
    unscheduled: rows,
    diagnostics: {
      ...result.diagnostics,
      demand_coverage_rate: kpi.demand_coverage_rate,
      used_loom_count: kpi.used_loom_count,
      fully_unscheduled_task_count: rows.filter(row => row.scheduled_quantity <= 0).length,
      partially_unscheduled_task_count: rows.filter(row => row.scheduled_quantity > 0).length,
      unscheduled_reason_summary: Array.from(grouped.values()).sort((a, b) => b.quantity - a.quantity),
      unscheduled_reason_quantity_reconcile: round3(Array.from(grouped.values()).reduce((sum, group) => sum + group.quantity, 0)) === kpi.unscheduled_quantity,
    },
  }
}

function simulationReasonCode(decision: any): string {
  const reason = String(decision?.reason || '')
  if (/经轴|缺轴|无可用/.test(reason)) return 'NO_AVAILABLE_BEAM'
  if (/七天|时间不足|周期/.test(reason)) return 'OUTSIDE_HORIZON'
  return 'CAPACITY_SHORTAGE'
}

function round3(value: number): number { return Math.round(value * 1000) / 1000 }

/** 将按工艺流程甘特图中的整经/织造条替换成同一份最终执行事件。 */
export function executableProcessGantt(data: ProcessGanttResult | null, result: ScheduleResult | null): ProcessGanttResult | null {
  if (isCanonicalFinal(result)) return data
  if (!data || !result?.execution_preview) return data
  const preview = result.execution_preview
  const valid = preview.validation?.ok === true
  const sourceWarps = data.groups.find(g => g.process === '整经')?.bars ?? []
  const sourceWeaves = data.groups.find(g => g.process === '织造')?.bars ?? []
  const sourceWashes = data.groups.find(g => g.process === '水洗')?.bars ?? []
  const decisions = preview.planning_trace?.decisions ?? []

  const beamSku = (beamId: any): string | undefined => {
    const decision = decisions.find((d: any) => (d.beam_ids ?? []).includes(beamId))
    return decision?.warp_beam_sku
  }
  const sourceWeave = (event: any): ProcessBar | undefined => sourceWeaves.find(b =>
    b.bar_id === event.task_id && (!event.loom_id || b.loom_id === event.loom_id),
  ) || sourceWeaves.find(b => b.bar_id === event.task_id)

  const warpBars: ProcessBar[] = (Array.isArray(preview.warping_plan) ? preview.warping_plan : []).map((event: any, index: number) => {
    const source = sourceWarps.find(b => b.bar_id === event.task_id)
      || sourceWarps.find(b => b.beam_instance_ids?.includes(event.beam_id))
    const sku = source?.warp_beam_sku || beamSku(event.beam_id) || String(event.product_id || '待确认')
    return {
      ...source,
      bar_id: String(event.event_id || `EXEC-WARP-${index + 1}`), process: '整经', label: sku,
      product_id: String(event.product_id || source?.product_id || ''),
      resource_id: String(event.resource_id || source?.machine_display || '整经计划池'),
      beam_id: event.beam_id || null, warp_beam_sku: sku,
      plan_meters: Number(event.quantity || 0), plan_count: 1,
      target_loom_ids: event.target_loom_ids || (event.loom_id ? [event.loom_id] : source?.target_loom_ids || []),
      beam_instance_ids: event.beam_id ? [event.beam_id] : source?.beam_instance_ids,
      machine_display: String(event.resource_id || source?.machine_display || '整经计划池'),
      start: event.start || null, end: event.end || null, derived: true,
      time_source: '最终执行事件', data_source: String(event.data_source || '逐轴联动校验'),
    }
  })
  const executionBars = (events: any[], process: ProcessBar['process'], prefix: string): ProcessBar[] =>
    events.map((event: any, index: number) => ({
      bar_id: String(event.event_id || `${prefix}-${index + 1}`),
      process,
      label: String(event.label || event.product_id || event.beam_id || ''),
      product_id: String(event.product_id || ''),
      resource_id: String(event.resource_id || event.loom_id || ''),
      loom_id: event.loom_id || undefined,
      beam_id: event.beam_id || undefined,
      beam_instance_id: event.beam_id || undefined,
      quantity: Number(event.quantity || 0),
      setup_type: event.setup_type || undefined,
      setup_label: event.setup_label || undefined,
      start: event.start || null,
      end: event.end || null,
      derived: true,
      time_source: '工况模拟最终事件',
      data_source: '最终可执行计划',
    }))
  const threadingBars = valid ? executionBars(preview.threading_plan ?? [], '穿综穿筘', 'EXEC-THREAD') : []
  const setupBars = valid ? executionBars(preview.loom_setup_plan ?? [], '织造准备', 'EXEC-SETUP') : []
  const weaveBars: ProcessBar[] = valid
    ? (Array.isArray(preview.weaving_plan) ? preview.weaving_plan : []).map((event: any, index: number) => {
      const source = sourceWeave(event)
      const sku = source?.warp_beam_sku || beamSku(event.beam_id)
      return {
        ...source,
        bar_id: String(event.event_id || `EXEC-WEAVE-${index + 1}`), process: '织造',
        label: String(event.loom_id || event.resource_id || source?.loom_id || ''),
        loom_id: String(event.loom_id || event.resource_id || source?.loom_id || ''),
        product_id: String(event.product_id || source?.product_id || ''), warp_beam_sku: sku,
        beam_id: event.beam_id || null, beam_instance_id: event.beam_id || null,
        quantity: Number(event.quantity || 0), start: event.start || null, end: event.end || null,
        derived: true, time_source: '逐轴联动校验通过', data_source: '最终可执行计划',
      }
    }) : []
  const washingEvents = (preview.events ?? []).filter((event: any) => event.event_type === 'washing')
  const washBars = valid ? washingEvents.map((event: any, index: number) => ({
    ...sourceWashes.find(b => b.bar_id === event.task_id),
    ...executionBars([event], '水洗', `EXEC-WASH-${index + 1}`)[0],
    machine_id: String(event.resource_id || event.machine_id || ''),
    washing_sku: event.washing_sku || undefined,
    plan_length: Number(event.quantity || 0),
  })) : []

  const finalGroups = [
    { process: '整经' as const, bars: warpBars },
    { process: '穿综穿筘' as const, bars: threadingBars },
    { process: '织造准备' as const, bars: setupBars },
    { process: '织造' as const, bars: weaveBars },
    { process: '水洗' as const, bars: washBars },
  ]

  const validationErrors = (preview.validation?.errors ?? []).map((x: any) => String(x))
  return {
    ...data,
    process_order: ['整经', '穿综穿筘', '织造准备', '织造', '水洗'],
    groups: finalGroups,
    stats: {
      ...data.stats,
      warp_task_count: warpBars.length,
      threading_task_count: threadingBars.length,
      setup_task_count: setupBars.length,
      weave_task_count: weaveBars.length,
      wash_task_count: washBars.length,
    },
    order_warnings: valid ? [] : validationErrors.length ? validationErrors : ['执行校验未通过，织造计划暂不展示'],
    note: valid
      ? '当前甘特图与工况模拟共用同一份最终可执行计划事件；跨天任务按日显示续产。'
      : '执行校验未通过，当前不展示未经验证的织造计划。',
    view_mode: valid ? 'executable' : 'invalid',
  }
}
