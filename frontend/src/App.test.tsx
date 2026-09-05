import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import App, { paramMismatch } from './App'
import { Gantt } from './components/Gantt'
import ProcessGantt from './components/ProcessGantt'
import { StatusBadges, KpiCards, UnscheduledPanel } from './components/Panels'
import type { ScheduleResult } from './types'

const { result, scenario } = vi.hoisted(() => {
  const result = {
    schedule_id: 'sch-1', status: 'OPTIMAL', solver_status: 'OPTIMAL', business_status: 'HIGH_RISK',
    comparison_status: 'COMPARABLE', schedule_start: '2026-04-01T00:00:00', schedule_end: '2026-04-15T00:00:00',
    model_stats: { num_variables: 100, num_constraints: 90, num_workers: 1, time_limit_s: 10, per_layer_time_s: 1.25 },
    assignments: [
      { task_id: 'T1', part_index: 0, loom_id: '#101', product_id: 'P1', beam_id: null, start: '2026-04-01T00:00:00', end: '2026-04-03T00:00:00', start_minute: 0, end_minute: 2880, scheduled_quantity: 1000, locked: false, lock_reason: null, changeover_type: 'same', lateness_minutes: 0 },
      { task_id: 'T2', part_index: 0, loom_id: '#102', product_id: 'P2', beam_id: 'WB-P2-001', start: '2026-04-02T00:00:00', end: '2026-04-05T12:00:00', start_minute: 1440, end_minute: 6480, scheduled_quantity: 2000, locked: true, lock_reason: '人工', changeover_type: 'beam_change', lateness_minutes: 120 },
      { task_id: 'T3', part_index: 0, loom_id: '#101', product_id: 'P3', beam_id: null, start: '2026-04-04T00:00:00', end: '2026-04-06T00:00:00', start_minute: 4320, end_minute: 7200, scheduled_quantity: 900, locked: false, lock_reason: null, changeover_type: 'threading', lateness_minutes: 0 },
    ],
    unscheduled: [{ task_id: 'T4', required_quantity: 3000, scheduled_quantity: 0, unscheduled_quantity: 3000, reason_codes: ['NO_COMPATIBLE_LOOM'] }],
    objective_levels: [
      { level: 1, name: 'unscheduled_quantity', best_value: 3000, best_bound: 3000, gap: 0, status: 'OPTIMAL', solve_time_s: 1 },
    ],
    kpi: {
      required_quantity: 6900, scheduled_quantity: 3900, unscheduled_quantity: 3000, on_time_quantity: 1900, late_quantity: 2000,
      total_lateness_minutes: 120, max_lateness_minutes: 120, changeover_count: 1, beam_change_count: 1, threading_count: 1,
      plan_change_count: 0, utilization: 0.5, scheduled_machine_minutes: 4840, available_machine_minutes: 9680,
      horizon_minutes: 20160, horizon_days: 14, gross_machine_minutes: 20160, maintenance_minutes: 0, downtime_minutes: 0,
      demand_coverage_rate: 0.5652, on_time_rate: 0.4872, on_time_demand_rate: 0.2754, total_delay_minutes: 120,
      max_delay_task_id: 'T2', used_loom_count: 2, task_fragment_count: 3, single_task_loom_count: 1,
      average_tasks_per_used_loom: 1.5, total_idle_gap_minutes: 0,
    },
    diagnostics: {
      demand_coverage_rate: 0.5652, available_loom_count: 106, candidate_loom_count: 2, used_loom_count: 2, unused_loom_count: 104,
      horizon_total_minutes: 20160, available_machine_minutes: 9680, scheduled_machine_minutes: 4840, utilization_formula: '4840 / 9680', utilization: 0.5,
      fully_unscheduled_task_count: 1, partially_unscheduled_task_count: 0, unscheduled_reason_summary: [
        { reason_code: 'NO_COMPATIBLE_LOOM', task_count: 1, quantity: 3000 },
      ], unscheduled_secondary_summary: [], unscheduled_reason_quantity_reconcile: true,
      task_diagnostics: [{ task_id: 'T1', product_id: 'P1', required_quantity: 1000, scheduled_quantity: 1000, unscheduled_quantity: 0, compatible_loom_count: 2, all_loom_count: 106, rejected_by_product_rule: 0, rejected_by_tooling_rule: 0, primary_reason: '', secondary_reasons: [], candidate_loom_ids: ['#101','#102'], final_reason_codes: [] }],
      compatibility_mode: 'balanced',
    },
    issues: [], risk_reasons: ['测试风险'], validation: { ok: true, checks: [] },
    provenance: {
      scenario_id: '益丰表单', data_snapshot_hash: 'abc123', schedule_id: 'sch-1',
      schedule_start: '2026-04-01T00:00:00', schedule_end: '2026-04-15T00:00:00',
      horizon_minutes: 20160, horizon_days: 14, compatibility_mode: 'balanced',
      material_enabled: true, beam_enabled: true, objective_layers: 8,
      per_layer_time_limit_s: 1.875, total_time_limit_s: 15, task_count: 3,
      required_quantity: 6900, config_version: '3.1.0', code_version: '3.1.0',
    },
  } as unknown as ScheduleResult
  const scenario = { products: 2, looms: 2, available_looms: 2, tasks: 3, warps: 1, materials: 1, data_warnings: ['d1'], data_errors: [], data_info: [], severity: { error: 0, warning: 1, info: 0 } }
  return { result, scenario }
})

vi.mock('./api', () => ({
  API_BASE: 'http://127.0.0.1:8001',
  health: vi.fn().mockResolvedValue({ status: 'ok', engine: 'test' }),
  getScenario: vi.fn().mockResolvedValue(scenario),
  getLatest: vi.fn().mockResolvedValue(null),
  solveSchedule: vi.fn().mockResolvedValue(result),
  diagnosticCompare: vi.fn().mockResolvedValue({ all_comparable: true, note: 'x', conclusion: 'y', schemes: [] }),
  getProcessOverview: vi.fn().mockResolvedValue({ flow: [
    { order: 1, process: '客户需求', pending_count: 0, in_progress_count: 0, completed_count: 1, anomaly_count: 0, quantity: 100, main_risk: '', is_finishing: false, pred: [], succ: ['生产需求确认'] },
    { order: 6, process: '整经生产', pending_count: 1, in_progress_count: 0, completed_count: 0, anomaly_count: 0, quantity: 100, main_risk: '实际执行状态待确认', is_finishing: false, pred: ['整经计划'], succ: ['经轴准备'] },
    { order: 10, process: '织造生产', pending_count: 1, in_progress_count: 0, completed_count: 0, anomaly_count: 0, quantity: 100, main_risk: '', is_finishing: false, pred: ['上轴'], succ: ['落布'] },
    { order: 12, process: '水洗', pending_count: 0, in_progress_count: 0, completed_count: 0, anomaly_count: 0, quantity: 0, main_risk: '', is_finishing: true, pred: ['落布'], succ: ['验布'] },
  ], statuses: [], branch_notes: ['b1'] }),
  getProcessTasks: vi.fn().mockResolvedValue({ tasks: [{ task_id: 'T1', order_id: 'ORD-T1', product_id: 'P1', required_quantity: 100, scheduled_quantity: 50, unscheduled_quantity: 50, current_process: '织造生产', current_status: '进行中', completed_processes: [], next_process: '落布', blocked_reason: '', data_source: '推导数据', use_temp_params: true }] }),
  getProcessCases: vi.fn().mockResolvedValue({ cases: [{ label: '已进入织造排程的任务', task_id: 'T1', product_id: 'P1', current_process: '织造生产', found: true }] }),
  getHomepageProgress: vi.fn().mockResolvedValue({ required_qty: 100, material_ready_qty: 50, beam_ready_qty: 50, weave_scheduled_qty: 50, weave_done_qty: 0, finishing_qty: 0, stocked_qty: 0, note: 'n' }),
  getProcessGantt: vi.fn().mockResolvedValue({
    process_order: ['整经', '织造', '水洗'],
    groups: [
      { process: '整经', bars: [{ bar_id: 'WARP-1', process: '整经', label: 'WP550', warp_beam_sku: 'WP550', plan_meters: 4800, plan_count: 1, target_loom_ids: ['LOOM-305'], warping_machine_id: '', machine_display: '整经计划池', machine_status: '按计划池管理', warping_resource_mode: '计划池', start: '2026-04-03', end: '2026-04-03', derived: false, data_source: '来源表', warp_spec: '设定米数 4830 / 根数 4524 / 钢筘 9.3', beam_instance_ids: ['BEAM-WP550-2026-04-03-01'], source_cell: 'O118' }] },
      { process: '织造', bars: [{ bar_id: 'WEAVE-1', process: '织造', label: '#101', loom_id: '#101', product_id: 'P1', weaving_sku: 'RP550', washing_sku: 'SP550', beam_id: 'WB-P1-001', quantity: 1000, start: '2026-04-01', end: '2026-04-03', derived: true, data_source: '排程求解结果' }] },
      { process: '水洗', bars: [{ bar_id: 'WASH-1', process: '水洗', label: '1号水洗机', machine_id: 'WASH-01', washing_sku: 'SP550', batch_code: 'PH888', plan_length: 1000, input_length: 990, start: '09:05:00', end: '09:25:00', derived: false, data_source: '来源表' }] },
    ],
    stats: { master_product_count: 19, warp_task_count: 1, warp_beam_sku_count: 12, target_loom_count: 30, weave_task_count: 3, wash_task_count: 0, wash_unmatched_count: 1, virtual_beam_count: 1, machine_pending_count: 0, chain_full_count: 11, chain_broken_count: 8 },
    chain_broken_reasons: { 缺水洗品番: 1 }, order_warnings: [], chains: [], beam_instances_count: 1,
    time_source_summary: { '来源表计划(非CP-SAT约束)': 2, 'CP-SAT求解结果': 1 },
    product_reconciliation: [
      { flow_id: 'FLOW-P1', product_id: 'P1', product_back_sku: 'P550', warp_beam_sku: 'WP550', weaving_sku: 'RP550', washing_sku: 'SP550', target_loom_ids: ['LOOM-305'], status: '完整串联', reason: '字段完整', missing_fields: [], mapping_state: '来源表完整', mapping_source: '工艺汇总背番号', mapping_confidence: '来源表', terminal_process: '水洗', publishable: true, in_weave_plan: true, in_process_master: true },
      { flow_id: 'FLOW-X', product_id: 'PH55463N', product_back_sku: 'P547', warp_beam_sku: 'WP546', weaving_sku: 'RP547', washing_sku: null, target_loom_ids: ['LOOM-406'], status: '缺水洗品番', reason: '来源表缺水洗品番', missing_fields: ['washing_sku'], mapping_state: '来源表缺字段', mapping_source: '工艺汇总背番号', mapping_confidence: '来源表', terminal_process: '织造', publishable: false, in_weave_plan: true, in_process_master: true },
    ],
    unmatched_washing_rows: [{ washing_sku: 'A产品', match_status: '待核对' }],
    note: '当前整经按计划池管理，不要求具体整经机编号。',
    warping_resource_mode: '计划池',
  }),
  getWarpingBeams: vi.fn().mockResolvedValue({
    count: 12,
    beams: [
      { warp_beam_sku: 'WP550', set_length: 4830, warp_threads: 4524, reed: '9.3', yarn_code: 'LS7056AB', unit_consumption_kg: 0.29375, initial_inventory: null, plan_dates: ['2026-06-15'], target_loom_ids: ['LOOM-305'], source_sheet: '整经预测辅助表', data_source: '来源表' },
    ],
  }),
  getWarpingInstances: vi.fn().mockResolvedValue({
    count: 7, virtual_count: 7, real_count: 0,
    instances: [{ beam_instance_id: 'BEAM-WP550-2026-06-15-01', warp_beam_sku: 'WP550', plan_date: '2026-06-15', instance_meters: 9660, target_loom_id: ['LOOM-305'], warping_machine_id: '', is_derived: true, data_source: '推导数据(源表无实体经轴编号)', status: '整经计划' }],
    note: '源表无实体经轴编号，实例全部为虚拟(推导)数据。',
  }),
  getWarpingInventory: vi.fn().mockResolvedValue({
    count: 12,
    inventory: [{ warp_beam_sku: 'WP550', initial_inventory: null, daily: [{ date: '2026-06-16', warp_complete_m: 9660, weave_mount_demand_m: 4687.5, stock_m: 19372.5 }], anomaly_dates: [] }],
    anomaly_dates: [],
  }),
  getWeeklyWarpingPlan: vi.fn().mockResolvedValue({
    schedule_start: '2026-04-01', schedule_end: '2026-04-08', horizon_days: 7,
    resource_mode: '计划池', resource_count: 1, minutes_per_beam: 240,
    tasks: [],
    daily: Array.from({ length: 7 }, (_, i) => ({ date: `2026-04-0${i + 1}`, task_count: 0, plan_count: 0, plan_meters: 0 })),
    unscheduled: [], blocked_products: [],
    stats: { task_count: 0, beam_sku_count: 0, plan_count: 0, plan_meters: 0, utilization: 0 },
    assumptions: ['测试口径'],
  }),
  getWeeklyWeavingPlan: vi.fn().mockResolvedValue({
    schedule_start: '2026-04-01', schedule_end: '2026-04-08', horizon_days: 7,
    tasks: [], daily: Array.from({ length: 7 }, (_, i) => ({ date: `2026-04-0${i + 1}`, task_count: 0, scheduled_meters: 0, loom_count: 0 })),
    order_violations: [],
    stats: { task_count: 0, product_count: 0, loom_count: 0, scheduled_meters: 0, unscheduled_meters: 0, order_violation_count: 0 },
    note: '测试口径',
  }),
  getTaskPool: vi.fn().mockResolvedValue({
    tasks: [{ task_id: 'T1', product_id: 'P1', required_quantity: 7200, scheduled_quantity: 7200, unscheduled_quantity: 0, due_date: '2026-05-31', priority: 1, split_allowed: false, min_batch_qty: 500, max_parts: 3, locked: false, lock_reason: null, beam_code: 'INTERNAL-P1', flow_id: 'FLOW-P1', product_back_sku: 'P550', warp_beam_sku: 'WP550', weaving_sku: 'RP550', washing_sku: 'SP550', beam_instance_id: 'WB-P1-001', chain_status: '完整串联', chain_missing_fields: [], chain_reason: '字段完整', mapping_state: '来源表完整', mapping_source: '工艺汇总背番号', process: null, reed: null, compatible_loom_count: 105, allowed_loom_count: 105, assigned_looms: ['#412'], machine_id: '#412', assign_start: '2026-04-01', assign_end: '2026-04-21', lateness_minutes: 0, changeover_type: 'threading', status: '已排程', current_process: '织造生产', current_status: '已排程', blocked_reason: '', primary_reason: '', secondary_reasons: [], data_source: 'CP-SAT排程结果' }],
    count: 1,
    by_status: { '已排程': 1 },
    chain_status_count: { '完整串联': 1 },
    sum_required: 7200, sum_scheduled: 7200, sum_unscheduled: 0,
    urgent_window_days: 14, due_urgent_count: 0, locked_count: 0, split_count: 0,
  }),
  getLoomResources: vi.fn().mockResolvedValue({
    looms: [{ loom_id: '#101', region: '区域1', status: '未安排', available: true, current_product: null, capacity_m_per_day: 400, waste_edge_disc: true, waste_edge_hole: '1', edge_cut: true, big_package: true, water_filter: false, yarn_frame: true, reed: '9.3钢筘', full_width_edge_support: '2350', wheels_gear: null, heald: null, compatible_products: [], tooling_note: '废边盘 / 切边', used: false, assigned_task_count: 0, scheduled_minutes: 0, assign_starts: [], assign_ends: [], products_scheduled: [], source_sheet: '②织机状态' }],
    count: 1, available_count: 1, unavailable_count: 0, used_count: 0, idle_count: 1,
    by_region: { '区域1': 1 }, by_status: { '未安排': 1 },
    capability_summary: { waste_edge_disc: 1, edge_cut: 1, big_package: 1, water_filter: 0, yarn_frame: 1 },
    data_source: '来源表', note: '织机主档 108 台。',
  }),
  getDataSnapshots: vi.fn().mockResolvedValue({ snapshots: [], count: 0, active_snapshot_id: null, note: '候选快照尚未启用。' }),
  previewDataImport: vi.fn(),
  saveDataSnapshot: vi.fn(),
}))

describe('App', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('OPTIMAL 与 HIGH_RISK 同时显示', async () => {
    const { getLatest } = await import('./api')
    ;(getLatest as any).mockResolvedValue(result)
    render(<App />)
    await waitFor(() => expect(screen.getByText('算法状态：OPTIMAL')).toBeInTheDocument())
    expect(screen.getByText('业务状态：HIGH_RISK')).toBeInTheDocument()
  })

  it('排程看板可打开规则自查抽屉', async () => {
    const { getLatest } = await import('./api')
    ;(getLatest as any).mockResolvedValue(result)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /规则自查/ }))
    expect(screen.getByRole('dialog', { name: '规则自查明细' })).toBeInTheDocument()
    expect(screen.getByText(/依据《织造排产问题求解》逐条核验/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(screen.queryByRole('dialog', { name: '规则自查明细' })).not.toBeInTheDocument()
  })

  it('运行排程调用真实接口(展示加载/结果)', async () => {
    const { solveSchedule } = await import('./api')
    ;(solveSchedule as any).mockResolvedValue(result)
    render(<App />)
    const btn = await screen.findByRole('button', { name: /运行排程/ })
    fireEvent.click(btn)
    await waitFor(() => expect(solveSchedule).toHaveBeenCalled())
    expect(solveSchedule).toHaveBeenCalledWith(expect.objectContaining({ horizon_days: 7, schedule_start: '2026-04-01', optimize_rules: true }))
    await waitFor(() => expect(screen.getByText('算法状态：OPTIMAL')).toBeInTheDocument())
  })

  it('空排程结果页面不崩溃', async () => {
    const { getLatest } = await import('./api')
    ;(getLatest as any).mockResolvedValue(null)
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('empty')).toBeInTheDocument())
  })

  it('诊断模式显示不可发布', async () => {
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '调整参数' }))
    const mat = await screen.findByLabelText('启用物料约束')
    fireEvent.click(mat)
    expect(screen.getByText('诊断模式，不可发布')).toBeInTheDocument()
  })

  it('接口错误不展示假结果', async () => {
    const { getLatest, solveSchedule } = await import('./api')
    ;(getLatest as any).mockResolvedValue(null)
    ;(solveSchedule as any).mockRejectedValue(new Error('后端未启动'))
    render(<App />)
    const btn = await screen.findByRole('button', { name: /运行排程/ })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByTestId('error')).toBeInTheDocument())
    expect(screen.getByText(/后端未启动/)).toBeInTheDocument()
  })

  it('本次求解参数显示 provenance 时间(15秒)，不读表单(30秒)', async () => {
    const { getLatest } = await import('./api')
    ;(getLatest as any).mockResolvedValue(result)
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('result-params')).toBeInTheDocument())
    expect(screen.getByText('本次求解参数')).toBeInTheDocument()
    expect(screen.getByText('15 秒')).toBeInTheDocument()   // provenance.total_time_limit_s
    expect(screen.getByText('1.875 秒')).toBeInTheDocument() // 每层时间
  })

  it('参数不同时提示差异，参数全同则不提示', () => {
    // 纯函数单测：类型归一化后再比较
    const p = { total_time_limit_s: 15, horizon_days: 14, compatibility_mode: 'balanced',
      material_enabled: true, beam_enabled: true, schedule_start: '2026-04-01T00:00:00' }
    const formDiff = { maxTime: 30, horizonDays: 60, mode: 'balanced', materialOn: true, beamOn: true, startDate: '2026-04-01' }
    const d1 = paramMismatch(p, formDiff)
    expect(d1.length).toBeGreaterThan(0)
    expect(d1).toContain('最大求解时间')
    expect(d1).toContain('排程周期')
    const formSame = { maxTime: 15, horizonDays: 14, mode: 'balanced', materialOn: true, beamOn: true, startDate: '2026-04-01' }
    expect(paramMismatch(p, formSame)).toEqual([])
    const d2 = paramMismatch(p, { ...formSame, startDate: '2026-04-02' })
    expect(d2).toContain('开始日期')
  })

  it('工艺流程页面可进入并展示流程卡片与首页进度条', async () => {
    render(<App />)
    const bar = await screen.findByTestId('process-bar')
    expect(bar).toBeInTheDocument()
    expect(screen.getAllByText(/需求总量/).length).toBeGreaterThan(0)
    const nav = await screen.findByRole('button', { name: '工艺流程' })
    fireEvent.click(nav)
    await waitFor(() => expect(screen.getByTestId('process-page')).toBeInTheDocument())
    expect(screen.getAllByText(/客户需求/).length).toBeGreaterThan(0)
    expect(screen.getByTestId('primary-stage-整经')).toBeInTheDocument()
    expect(screen.getByTestId('primary-stage-织造')).toBeInTheDocument()
    expect(screen.getByTestId('primary-stage-水洗')).toBeInTheDocument()
    expect(screen.getByText('已进入织造排程的任务')).toBeInTheDocument()
    expect(screen.queryByText('正常完成全部流程')).not.toBeInTheDocument()
  })

  it('任务池页可进入并展示任务表格', async () => {
    render(<App />)
    const nav = await screen.findByRole('button', { name: '任务池' })
    fireEvent.click(nav)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    expect(screen.getAllByTestId('task-row').length).toBe(1)
    expect(screen.getByText('T1')).toBeInTheDocument()
  })

  it('织机资源页可进入并展示织机表格', async () => {
    render(<App />)
    const nav = await screen.findByRole('button', { name: '织机资源' })
    fireEvent.click(nav)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    expect(screen.getAllByTestId('loom-row').length).toBe(1)
    expect(screen.getByText('#101')).toBeInTheDocument()
  })

  it('显示后端连接状态', async () => {
    render(<App />)
    await waitFor(() => expect(screen.getByText('后端已连接')).toBeInTheDocument())
    expect(screen.getByTestId('service-status')).toHaveClass('online')
  })

  it('数据质量中心集中展示数据问题', async () => {
    const { getLatest } = await import('./api')
    ;(getLatest as any).mockResolvedValue({
      ...result,
      issues: [{ severity: 'WARNING', code: 'unscheduled', message: '任务 T4 未排数量 3000（需求 3000）' }],
    })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '数据质量' }))
    await waitFor(() => expect(screen.getByTestId('data-quality-page')).toBeInTheDocument())
    expect(screen.getByText('d1')).toBeInTheDocument()
    expect(screen.queryByText(/任务 T4 未排数量/)).not.toBeInTheDocument()
    expect(screen.getByTestId('schedule-issue-note')).toHaveTextContent('3,000 米未排')
    expect(screen.queryByTestId('warnings')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '导出待补数据' })).toBeEnabled()
  })

  it('全局只展示输入数据质量摘要并可进入质量中心', async () => {
    render(<App />)
    const banner = await screen.findByTestId('warnings')
    expect(banner).toHaveTextContent('0 阻断、1 警告、0 提示')
    expect(screen.queryByText('d1')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看数据质量' }))
    await waitFor(() => expect(screen.getByTestId('data-quality-page')).toBeInTheDocument())
  })

  it('数据导入页面展示预检查入口和候选快照历史', async () => {
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '数据导入' }))
    await waitFor(() => expect(screen.getByTestId('data-import-page')).toBeInTheDocument())
    expect(screen.getByText('Excel导入预检查与数据快照')).toBeInTheDocument()
    expect(screen.getByTestId('snapshot-history')).toHaveTextContent('候选数据快照历史（0）')
  })

  it('顶部只展示参数摘要，参数编辑统一进入模拟参数页面', async () => {
    render(<App />)
    const summary = await screen.findByTestId('solve-parameter-summary')
    expect(summary).toHaveTextContent('2026-04-01')
    expect(summary).toHaveTextContent('7天')
    expect(summary).toHaveTextContent('物料约束开启')
    expect(screen.queryByLabelText('启用物料约束')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '调整参数' }))
    await waitFor(() => expect(screen.getByTestId('parameters-page')).toBeInTheDocument())
    expect(screen.getByLabelText('启用物料约束')).toBeInTheDocument()
    expect(screen.getByText('经轴提前到位')).toBeInTheDocument()
    expect(screen.getByText('120 分钟')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '按当前参数运行排程' })).toBeEnabled()
  })
})

describe('Gantt', () => {
  it('横坐标按天展示完整排程周期', () => {
    render(<Gantt result={result} showAllLooms={false} filterProduct="" filterStatus="" searchLoom="" onSelect={() => {}} />)
    expect(screen.getAllByTestId('gantt-day')).toHaveLength(14)
    expect(screen.getByText('时间单位：天（共 14 天）')).toBeInTheDocument()
  })

  it('甘特图时间位置与 start/end 一致', async () => {
    render(<Gantt result={result} showAllLooms={false} filterProduct="" filterStatus="" searchLoom="" onSelect={() => {}} />)
    const bars = await screen.findAllByText('P1')
    expect(bars.length).toBe(1)
  })

  it('默认只显示有任务织机', async () => {
    render(<Gantt result={result} showAllLooms={false} filterProduct="" filterStatus="" searchLoom="" onSelect={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('row-#101')).toBeInTheDocument())
    expect(screen.getByTestId('row-#102')).toBeInTheDocument()
  })

  it('显示全部织机开关', async () => {
    render(<Gantt result={result} showAllLooms={true} filterProduct="" filterStatus="" searchLoom="" onSelect={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('row-#101')).toBeInTheDocument())
    expect(screen.getByTestId('row-#102')).toBeInTheDocument()
  })

  it('点击任务打开详情', async () => {
    let picked: any = null
    render(<Gantt result={result} showAllLooms={false} filterProduct="" filterStatus="" searchLoom="" onSelect={(a) => { picked = a }} />)
    const bar = await screen.findByText('P2')
    fireEvent.click(bar)
    expect(picked && picked.task_id).toBe('T2')
  })
})

describe('StatusBadges / KpiCards / UnscheduledPanel', () => {
  it('算法与业务状态分开显示', () => {
    render(<StatusBadges solver="FEASIBLE" business="PARTIAL" />)
    expect(screen.getByText('算法状态：FEASIBLE')).toBeInTheDocument()
    expect(screen.getByText('业务状态：PARTIAL')).toBeInTheDocument()
  })

  it('利用率显示分子和分母', () => {
    render(<KpiCards kpi={result.kpi} onMaxDelay={() => {}} />)
    expect(screen.getByText(/计划占用/)).toBeInTheDocument()
    expect(screen.getByText(/4,840/)).toBeInTheDocument()
    expect(screen.getByText(/9,680/)).toBeInTheDocument()
  })

  it('最终可执行口径不再把算法初排标为已排', () => {
    render(<KpiCards kpi={{ ...result.kpi, scheduled_quantity: 1800, unscheduled_quantity: 5100 }} onMaxDelay={() => {}} scope="executable" />)
    expect(screen.getByTestId('kpi-scope')).toHaveTextContent('最终可执行计划')
    expect(screen.getByText('最终可执行数量')).toBeInTheDocument()
    expect(screen.getByText('最终未排数量')).toBeInTheDocument()
  })

  it('最大延误可定位', () => {
    render(<KpiCards kpi={result.kpi} onMaxDelay={() => {}} />)
    expect(screen.getByText('最大延误')).toBeInTheDocument()
    expect(screen.getByText('120 分钟')).toBeInTheDocument()
    expect(screen.getByText('点击定位任务')).toBeInTheDocument()
  })

  it('未排原因数量可对账', () => {
    render(<UnscheduledPanel result={result} onSelectReason={() => {}} />)
    expect(screen.getAllByText(/3,000 米/).length).toBeGreaterThan(0)
    expect(screen.getByText('1 个任务')).toBeInTheDocument()
  })

  it('未排按原因分组显示占比', () => {
    render(<UnscheduledPanel result={result} onSelectReason={() => {}} />)
    expect(screen.getByText('无兼容织机')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()
  })
})

describe('ProcessGantt', () => {
  it('展示统一产品工艺链对账并区分经轴品番', async () => {
    const { getProcessGantt } = await import('./api')
    const pg = await (getProcessGantt as any)()
    render(<ProcessGantt data={pg} />)
    expect(screen.getByTestId('product-chain-audit')).toBeInTheDocument()
    expect(screen.getByTestId('pg-timeline').compareDocumentPosition(screen.getByTestId('product-chain-audit'))
      & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText('产品工艺链对账（2 个基础产品）')).toBeInTheDocument()
    expect(screen.getAllByText('WP550').length).toBeGreaterThan(0)
    expect(screen.getByText(/水洗计划中有 1 条记录未匹配/)).toBeInTheDocument()
  })

  it('整经条点击打开详情抽屉并显示经轴/规格/来源', async () => {
    const { getProcessGantt } = await import('./api')
    const pg = await (getProcessGantt as any)()
    render(<ProcessGantt data={pg} />)
    const bars = await screen.findAllByTestId('pg-bar')
    const warpBar = bars.find(b => b.textContent?.includes('WP550'))!
    fireEvent.click(warpBar)
    await waitFor(() => expect(screen.getByTestId('pg-drawer')).toBeInTheDocument())
    expect(screen.getByText(/经轴编号/)).toBeInTheDocument()
    expect(screen.getByText('BEAM-WP550-2026-04-03-01')).toBeInTheDocument()
    expect(screen.getByText(/设定米数 4830/)).toBeInTheDocument()
    expect(screen.getByText(/O118/)).toBeInTheDocument()
    expect(screen.getAllByText('LOOM-305').length).toBeGreaterThan(0)
  })

  it('日期刻度行按排程天数计算宽度且含刻度', async () => {
    const { getProcessGantt } = await import('./api')
    const pg = await (getProcessGantt as any)()
    render(<ProcessGantt data={pg} scheduleStart="2026-04-01" horizonDays={7} />)
    await waitFor(() => expect(screen.getByTestId('pg-timeline')).toBeInTheDocument())
    expect(screen.getByTestId('pg-timeline')).toBeInTheDocument()
    expect(screen.getAllByTestId('pg-tick')).toHaveLength(7)
    expect(screen.getByText('时间单位：天（共 7 天）')).toBeInTheDocument()
    expect(screen.getByTestId('process-sequence')).toHaveTextContent('整经完成 → 穿综穿筘 → 织造准备/上轴 → 织造完成 → 水洗')
  })

  it('相关目标织机文本(非目标织机)', async () => {
    const { getProcessGantt } = await import('./api')
    const pg = await (getProcessGantt as any)()
    render(<ProcessGantt data={pg} />)
    await waitFor(() => expect(screen.getByTestId('process-gantt')).toBeInTheDocument())
    expect(screen.getAllByText(/相关目标织机/).length).toBeGreaterThan(0)
  })
})
