import { describe, expect, it } from 'vitest'
import { executableProcessGantt, executableScheduleKpi, executableProcessProgress, executableScheduleResult, executableUnscheduledResult, scheduleViewMode } from './scheduleView'
import type { ProcessGanttResult, ScheduleResult } from './types'

const baseResult = {
  schedule_start: '2026-04-01T00:00:00',
  assignments: [{
    task_id: 'T1', part_index: 0, loom_id: '#101', product_id: 'P1', beam_id: 'OLD-BEAM',
    start: '2026-04-01T00:00:00', end: '2026-04-03T00:00:00', start_minute: 0, end_minute: 2880,
    scheduled_quantity: 1000, locked: false, lock_reason: null, changeover_type: 'same', lateness_minutes: 0,
  }],
  execution_preview: {
    validation: { ok: true, errors: [] },
    kpi: { required_quantity: 1000, solver_scheduled_quantity: 1000, simulated_quantity: 600, reduced_quantity: 400, threading_task_count: 1, total_lateness_minutes: 0, setup_type_counts: { change_style_setup: 1 } },
    warping_plan: [{ event_id: 'warp-1', event_type: 'warping', task_id: 'W1', product_id: 'P1', resource_id: 'WAR-POOL-01', beam_id: 'BEAM-1', quantity: 800, start: '2026-04-01T00:00:00', end: '2026-04-01T04:00:00' }],
    threading_plan: [{ event_id: 'thread-1', event_type: 'threading', task_id: 'T1', product_id: 'P1', resource_id: 'THREAD-01', loom_id: '#101', beam_id: 'BEAM-1', quantity: 600, start: '2026-04-01T04:00:00', end: '2026-04-01T08:00:00' }],
    loom_setup_plan: [{ event_id: 'setup-1', event_type: 'loom_setup', task_id: 'T1', product_id: 'P1', resource_id: '#101', loom_id: '#101', beam_id: 'BEAM-1', setup_label: '改品番仕挂', quantity: 600, start: '2026-04-01T08:00:00', end: '2026-04-01T09:30:00' }],
    weaving_plan: [{ event_id: 'weave-1', event_type: 'weaving', task_id: 'T1', product_id: 'P1', loom_id: '#101', beam_id: 'BEAM-1', quantity: 600, start: '2026-04-01T09:30:00', end: '2026-04-02T09:30:00', start_minute: 570, end_minute: 2010, beam_segment_index: 1 }],
    events: [],
    planning_trace: { decisions: [{ task_id: 'T1', loom_id: '#101', warp_beam_sku: 'WP1', beam_ids: ['BEAM-1'], requested_quantity: 1000, executable_quantity: 600, reduced_quantity: 400, reason: '七天内剩余时间不足' }] },
  },
  kpi: { horizon_days: 7, horizon_minutes: 10080, required_quantity: 1000, scheduled_quantity: 1000, unscheduled_quantity: 0, available_machine_minutes: 20160 },
  unscheduled: [{ task_id: 'T1', required_quantity: 1000, scheduled_quantity: 1000, unscheduled_quantity: 0, reason_codes: [], primary_reason: '', secondary_reasons: [], business_text: '', candidate_loom_count: 1, theoretical_capacity: 1000, missing_material: { material_code: null, missing_kg: null } }],
  diagnostics: { task_diagnostics: [], fully_unscheduled_task_count: 0, partially_unscheduled_task_count: 0, unscheduled_reason_summary: [] },
} as unknown as ScheduleResult

const processData = {
  process_order: ['整经', '织造', '水洗'],
  groups: [
    { process: '整经', bars: [{ bar_id: 'W1', process: '整经', label: 'WP1', warp_beam_sku: 'WP1', plan_meters: 1000, plan_count: 1, beam_instance_ids: ['BEAM-1'], start: '2026-04-01T00:00:00', end: '2026-04-01T04:00:00', derived: true, data_source: '初排' }] },
    { process: '织造', bars: [{ bar_id: 'T1', process: '织造', label: '#101', loom_id: '#101', product_id: 'P1', weaving_sku: 'RP1', start: '2026-04-01T00:00:00', end: '2026-04-03T00:00:00', quantity: 1000, derived: true, data_source: 'CP-SAT初排' }] },
    { process: '水洗', bars: [{ bar_id: 'SOURCE-WASH', process: '水洗', label: '来源表水洗', start: '2026-04-03T00:00:00', end: '2026-04-03T04:00:00', derived: true, data_source: '来源表' }] },
  ],
  stats: { warp_task_count: 1, weave_task_count: 1 }, chain_broken_reasons: {}, order_warnings: [], chains: [], beam_instances_count: 1, note: '初排',
} as ProcessGanttResult

describe('最终可执行看板口径', () => {
  it('后端已给出最终计划时直接使用，不再由浏览器二次推断', () => {
    const canonical = {
      ...baseResult,
      result_scope: 'final_executable',
      final_schedule: { result_scope: 'final_executable' },
      assignments: [{ ...baseResult.assignments[0], scheduled_quantity: 480, beam_id: 'FINAL-BEAM' }],
      kpi: { ...baseResult.kpi, scheduled_quantity: 480, unscheduled_quantity: 520 },
    } as unknown as ScheduleResult
    expect(executableScheduleResult(canonical)).toBe(canonical)
    expect(executableScheduleKpi(canonical)).toBe(canonical.kpi)
    expect(executableUnscheduledResult(canonical)).toBe(canonical)
    expect(executableProcessGantt(processData, canonical)).toBe(processData)
  })

  it('按织机视图使用执行事件的时间、数量和具体经轴', () => {
    const view = executableScheduleResult(baseResult)!
    expect(scheduleViewMode(baseResult)).toBe('executable')
    expect(view.assignments).toHaveLength(1)
    expect(view.assignments[0]).toMatchObject({ beam_id: 'BEAM-1', scheduled_quantity: 600, start_minute: 570, end_minute: 2010 })
  })

  it('主看板 KPI 和工艺进度按最终可执行数量重算', () => {
    const kpi = executableScheduleKpi(baseResult)!
    expect(kpi).toMatchObject({
      scheduled_quantity: 600,
      unscheduled_quantity: 400,
      demand_coverage_rate: 0.6,
      used_loom_count: 1,
      scheduled_machine_minutes: 1440,
      used_loom_available_minutes: 10080,
      threading_count: 1,
      changeover_count: 1,
    })
    expect(executableProcessProgress({ material_ready_qty: 1000, beam_ready_qty: 1000, weave_scheduled_qty: 1000 }, baseResult))
      .toMatchObject({ material_ready_qty: 600, beam_ready_qty: 600, weave_scheduled_qty: 600 })
    const finalResult = executableUnscheduledResult(baseResult)!
    expect(finalResult.kpi.unscheduled_quantity).toBe(400)
    expect(finalResult.unscheduled[0]).toMatchObject({ task_id: 'T1', scheduled_quantity: 600, unscheduled_quantity: 400, primary_reason: 'OUTSIDE_HORIZON' })
    expect(finalResult.diagnostics.unscheduled_reason_summary).toEqual([{ reason_code: 'OUTSIDE_HORIZON', task_count: 1, quantity: 400 }])
  })

  it('按工艺流程视图替换初排织造并保留执行整经', () => {
    const view = executableProcessGantt(processData, baseResult)!
    expect(view.view_mode).toBe('executable')
    expect(view.groups.find(g => g.process === '织造')?.bars[0]).toMatchObject({ beam_id: 'BEAM-1', quantity: 600, data_source: '最终可执行计划' })
    expect(view.groups.find(g => g.process === '整经')?.bars[0]).toMatchObject({ plan_meters: 800 })
    expect(view.process_order).toEqual(['整经', '穿综穿筘', '织造准备', '织造', '水洗'])
    expect(view.groups.find(g => g.process === '穿综穿筘')?.bars).toHaveLength(1)
    expect(view.groups.find(g => g.process === '织造准备')?.bars[0]).toMatchObject({ setup_label: '改品番仕挂', beam_id: 'BEAM-1' })
    expect(view.groups.find(g => g.process === '水洗')?.bars).toEqual([])
    expect(view.note).toContain('最终可执行计划')
  })

  it('执行校验失败时不展示未经验证的织造段', () => {
    const invalid = { ...baseResult, execution_preview: { ...baseResult.execution_preview, validation: { ok: false, errors: ['经轴超额消耗'] } } }
    expect(scheduleViewMode(invalid)).toBe('invalid')
    expect(executableScheduleResult(invalid)?.assignments).toEqual([])
    expect(executableProcessGantt(processData, invalid)?.groups.find(g => g.process === '织造')?.bars).toEqual([])
  })
})
