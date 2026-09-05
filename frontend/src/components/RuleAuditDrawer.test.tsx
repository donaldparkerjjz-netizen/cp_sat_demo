import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScheduleResult } from '../types'
import { RuleAuditDrawer, buildRuleAudit } from './RuleAuditDrawer'

function currentLikeResult(): ScheduleResult {
  const assignments = [
    { task_id: 'T1', product_id: 'P1', loom_id: '#101', beam_id: 'B1', changeover_type: 'change_style_setup', source_target_match: true },
    { task_id: 'T2', product_id: 'P2', loom_id: '#102', beam_id: 'B2', changeover_type: 'change_style_setup', target_mapping_status: 'missing_trial' },
    { task_id: 'T3', product_id: 'P3', loom_id: '#103', beam_id: 'B3', changeover_type: 'change_style_setup', target_mapping_status: 'missing_trial' },
  ]
  const events = assignments.flatMap((a, index) => {
    const base = index * 2000
    return [
      { event_type: 'threading', task_id: a.task_id, beam_id: a.beam_id, start_minute: base, end_minute: base + 480 },
      { event_type: 'loom_setup', task_id: a.task_id, beam_id: a.beam_id, start_minute: base + 600, end_minute: base + 940 },
      { event_type: 'weaving', task_id: a.task_id, beam_id: a.beam_id, start_minute: base + 940, end_minute: base + 1800 },
    ]
  })
  return {
    schedule_id: 'sch-current', status: 'FEASIBLE', solver_status: 'FEASIBLE', business_status: 'HIGH_RISK',
    schedule_start: '2026-04-01T00:00:00', schedule_end: '2026-04-08T00:00:00',
    assignments: assignments as any,
    unscheduled: [{ task_id: 'M1', required_quantity: 35695, scheduled_quantity: 0, unscheduled_quantity: 35695, reason_codes: ['MATERIAL_SHORTAGE'], primary_reason: 'MATERIAL_SHORTAGE', reason_breakdown: [{ reason_code: 'MATERIAL_SHORTAGE', quantity: 35695 }] }] as any,
    objective_levels: [{ level: 1, name: 'unscheduled_quantity', best_value: 0, best_bound: 0, gap: 0, status: 'FEASIBLE', solve_time_s: 1 }],
    kpi: { required_quantity: 164120, scheduled_quantity: 4037.444, unscheduled_quantity: 160082.556, horizon_days: 7, on_time_rate: 1, on_time_demand_rate: 0.0246 } as any,
    validation: { ok: true, checks: [] },
    execution_preview: {
      events,
      forecasts: [{ cutoff_minutes: 1440 }, { cutoff_minutes: 2880 }],
      planning_trace: { decisions: assignments.map(a => ({ task_id: a.task_id, due_at: '2026-05-31T00:00:00' })) },
      validation: { ok: true, checks: ['loom_no_overlap', 'warping_no_overlap', 'threading_no_overlap', 'beam_quantity_capacity', 'beam_source_traceability', 'beam_ready_lead_time'].map(check => ({ check, pass: true })) },
      simulation_config: { lead_time_minutes: 120, edge_support_use_limit: 5, warping_minutes_per_beam: 240, threading_minutes: 480 },
    },
    final_schedule: {
      assignments,
      warping_plan: { tasks: Array.from({ length: 26 }, (_, i) => ({ beam_instance_id: `B${i + 1}`, plan_meters: i === 25 ? 5320 : 4000 })) },
      weaving_plan: { simulation_basis: { publishable: false, target_loom_missing_count: 2 } },
      input_shopfloor_snapshot: { captured_at: '2026-05-18T08:00:00', loom_with_remaining_beam_count: 23, unavailable_loom_count: 2 },
      simulation_config: { lead_time_minutes: 120, edge_support_use_limit: 5, warping_minutes_per_beam: 240, threading_minutes: 480 },
      final_runtime_states: [],
    } as any,
    params: { enable_material_constraint: true, enable_beam_constraint: true } as any,
    target_loom_audit: { matched_assignment_count: 1, missing_target_assignment_count: 2, publishable: false } as any,
    provenance: { horizon_days: 7, material_enabled: true, beam_enabled: true } as any,
    diagnostics: {} as any, issues: [], risk_reasons: [], comparison_status: 'COMPARABLE', model_stats: {} as any,
  } as ScheduleResult
}

describe('规则自查', () => {
  it('按当前排程动态识别上游过量、原料口径和落布缺失', () => {
    const audit = buildRuleAudit(currentLikeResult())
    expect(audit.items).toHaveLength(24)
    expect(audit.items.find(x => x.id === 'R02')?.status).toBe('不符合')
    expect(audit.items.find(x => x.id === 'R05')?.status).toBe('部分符合')
    expect(audit.items.find(x => x.id === 'R13')?.status).toBe('不符合')
    expect(audit.items.find(x => x.id === 'R11')?.status).toBe('符合')
    expect(audit.items.find(x => x.id === 'R15')?.status).toBe('符合')
    expect(audit.criticalNotice).toMatch(/现场快照晚于排程开始日/)
  })

  it('规则优化结果把织造拉动、换型目标和匹级计划计为符合', () => {
    const result = currentLikeResult() as any
    result.rule_optimization = { enabled: true, note: '已执行规则优化', warping_alignment: { optimized: true } }
    result.objective_levels.push({ level: 2, name: 'changeover_count', status: 'OPTIMAL' })
    result.final_schedule.warping_plan = {
      planning_mode: 'weaving_pull', alignment: { optimized: true },
      tasks: result.assignments.map((a: any, i: number) => ({ beam_instance_id: a.beam_id, plan_meters: i ? 4500 : 4800 })),
    }
    result.final_schedule.roll_plan = result.assignments.map((a: any, i: number) => ({
      beam_instance_id: a.beam_id,
      rolls: Array.from({ length: 5 }, (_, j) => ({ roll_id: `${a.beam_id}-${j}`, planned_meters: i ? 900 : 960 })),
    }))

    const audit = buildRuleAudit(result)
    expect(audit.items.find(x => x.id === 'R02')?.status).toBe('符合')
    expect(audit.items.find(x => x.id === 'R08')?.status).toBe('符合')
    expect(audit.items.find(x => x.id === 'R13')?.status).toBe('符合')
    expect(audit.optimizationNote).toBe('已执行规则优化')
  })

  it('抽屉可按判定筛选并查看规则证据', () => {
    const audit = buildRuleAudit(currentLikeResult())
    render(<RuleAuditDrawer audit={audit} open onClose={() => {}} />)
    expect(screen.getByRole('dialog', { name: '规则自查明细' })).toBeInTheDocument()
    expect(screen.getByText('工艺顺序')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /不符合/ }))
    expect(screen.getByText('织造拉动整经和穿综')).toBeInTheDocument()
    expect(screen.getByText('落布4—5匹、每匹800—1000米')).toBeInTheDocument()
    expect(screen.queryByText('工艺顺序')).not.toBeInTheDocument()
  })
})
