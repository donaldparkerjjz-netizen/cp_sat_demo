export type SolverStatus = 'OPTIMAL' | 'FEASIBLE' | 'INFEASIBLE' | 'UNKNOWN'
export type BusinessStatus = 'READY' | 'PARTIAL' | 'HIGH_RISK' | 'NOT_EXECUTABLE'
export type CompatMode = 'strict' | 'balanced' | 'simulation'

export interface Assignment {
  task_id: string
  part_index: number
  loom_id: string
  product_id: string
  source_target_loom_ids?: string[]
  target_mapping_status?: string | null
  source_target_match?: boolean | null
  beam_id: string | null
  start: string
  end: string
  start_minute: number
  end_minute: number
  scheduled_quantity: number
  locked: boolean
  lock_reason: string | null
  changeover_type: string
  lateness_minutes: number
  rolls?: { roll_id: string; sequence: number; planned_meters: number; scheduled_meters: number; status: string }[]
}

export interface UnscheduledItem {
  task_id: string
  required_quantity: number
  scheduled_quantity: number
  unscheduled_quantity: number
  reason_codes: string[]
  primary_reason: string
  secondary_reasons: string[]
  business_text: string
  candidate_loom_count: number
  theoretical_capacity: number
  missing_material: { material_code: string | null; missing_kg: number | null }
}

export interface ObjectiveLevel {
  level: number
  name: string
  best_value: number | null
  best_bound: number | null
  gap: number | null
  status: SolverStatus
  solve_time_s: number
}

export interface Kpi {
  required_quantity: number
  scheduled_quantity: number
  unscheduled_quantity: number
  on_time_quantity: number
  late_quantity: number
  total_lateness_minutes: number
  max_lateness_minutes: number
  changeover_count: number
  beam_change_count: number
  threading_count: number
  plan_change_count: number
  utilization: number
  fleet_utilization?: number
  used_loom_utilization?: number
  used_loom_available_minutes?: number
  used_loom_gross_minutes?: number
  used_loom_maintenance_minutes?: number
  used_loom_downtime_minutes?: number
  scheduled_machine_minutes: number
  available_machine_minutes: number
  horizon_minutes: number
  horizon_days: number
  gross_machine_minutes: number
  maintenance_minutes: number
  downtime_minutes: number
  demand_coverage_rate: number
  on_time_rate: number
  on_time_demand_rate: number
  total_delay_minutes: number
  max_delay_task_id: string | null
  used_loom_count: number
  task_fragment_count: number
  single_task_loom_count: number
  average_tasks_per_used_loom: number
  total_idle_gap_minutes: number
}

export interface ReasonSummary {
  reason_code: string
  task_count: number
  quantity: number
}

export interface TaskDiagnostic {
  task_id: string
  product_id: string
  required_quantity: number
  scheduled_quantity: number
  unscheduled_quantity: number
  compatible_loom_count: number
  candidate_loom_count: number
  all_loom_count: number
  rejected_by_product_rule: number
  rejected_by_tooling_rule: number
  top10_candidate_looms: string[]
  candidate_loom_ids: string[]
  current_loom_id: string | null
  current_loom_reason: string
  excluded_loom_count: number
  exclusion_reason_categories: Record<string, number>
  primary_reason: string
  secondary_reasons: string[]
  final_reason_codes: string[]
  is_style_change: boolean
  is_beam_change: boolean
  is_threading: boolean
  business_text: string
  theoretical_capacity: number
  missing_material: { material_code: string | null; missing_kg: number | null }
}

export interface Diagnostics {
  demand_coverage_rate: number
  available_loom_count: number
  candidate_loom_count: number
  used_loom_count: number
  unused_loom_count: number
  horizon_total_minutes: number
  available_machine_minutes: number
  scheduled_machine_minutes: number
  utilization_formula: string
  utilization: number
  fully_unscheduled_task_count: number
  partially_unscheduled_task_count: number
  unscheduled_reason_summary: ReasonSummary[]
  unscheduled_secondary_summary: ReasonSummary[]
  unscheduled_reason_quantity_reconcile: boolean
  task_diagnostics: TaskDiagnostic[]
  compatibility_mode: CompatMode
}

export interface ScheduleResult {
  schedule_id: string
  status: SolverStatus
  solver_status: SolverStatus
  business_status: BusinessStatus
  comparison_status: string
  schedule_start: string
  schedule_end: string
  model_stats: { num_variables: number; num_constraints: number; num_workers: number; time_limit_s: number; per_layer_time_s: number }
  assignments: Assignment[]
  unscheduled: UnscheduledItem[]
  objective_levels: ObjectiveLevel[]
  kpi: Kpi
  diagnostics: Diagnostics
  issues: { severity: string; code: string; message: string }[]
  risk_reasons: string[]
  validation: { ok: boolean; checks: { check: string; pass: boolean; message: string }[] }
  result_scope?: 'initial' | 'final_executable'
  execution_preview?: ExecutionPreview
  initial_plan?: Record<string, unknown>
  final_schedule?: {
    schema_version: number
    schedule_id: string
    result_scope: 'final_executable'
    status: 'EXECUTABLE' | 'INVALID'
    input_shopfloor_snapshot: Record<string, unknown>
    simulation_config: Record<string, unknown>
    validation: { ok: boolean; checks?: unknown[]; errors?: string[] }
    execution: ExecutionPreview
    roll_plan?: Record<string, any>[]
    rule_optimization?: Record<string, any>
  }
  rule_optimization?: Record<string, any>
  roll_plan?: Record<string, any>[]
  provenance: {
    scenario_id: string; data_snapshot_hash: string; schedule_id: string;
    schedule_start: string; schedule_end: string; horizon_minutes: number; horizon_days: number;
    compatibility_mode: CompatMode; material_enabled: boolean; beam_enabled: boolean;
    objective_layers: number; per_layer_time_limit_s: number; total_time_limit_s: number;
    task_count: number; required_quantity: number; config_version: string; code_version: string;
  }
}

export interface ExecutionPreview {
  schedule_start?: string
  schedule_end?: string
  status?: string
  result_scope?: 'final_executable'
  events?: Record<string, any>[]
  warping_plan?: Record<string, any>[]
  threading_plan?: Record<string, any>[]
  loom_setup_plan?: Record<string, any>[]
  weaving_plan?: Record<string, any>[]
  forecasts?: Record<string, any>[]
  assumptions?: string[]
  kpi?: Record<string, any>
  validation?: { ok: boolean; checks?: unknown[]; errors?: string[] }
  planning_trace?: Record<string, any>
  solver_summary?: Record<string, any>
  simulation_config?: Record<string, any>
  shopfloor_snapshot?: Record<string, any>
}

export interface ScenarioSummary {
  products: number
  looms: number
  available_looms: number
  tasks: number
  warps: number
  materials: number
  data_warnings: string[]
  data_errors: string[]
  data_info: string[]
  severity: { error: number; warning: number; info: number }
}

export interface SolveParams {
  compatibility_mode: CompatMode
  max_time_s: number
  schedule_start?: string
  horizon_days: number | null
  enable_material_constraint: boolean
  enable_beam_constraint: boolean
  freeze_days: number
  objective_mode: string
  optimize_rules?: boolean
}

export type ProcessName = '整经' | '穿综穿筘' | '织造准备' | '织造' | '水洗'

export interface ProcessBar {
  bar_id: string
  process: ProcessName
  label: string
  // 整经
  warp_beam_sku?: string
  plan_meters?: number
  plan_count?: number
  target_loom_ids?: string[]
  warping_machine_id?: string
  machine_display?: string
  machine_status?: string
  warping_resource_mode?: string
  // 织造
  loom_id?: string
  resource_id?: string
  product_id?: string
  product_back_sku?: string | null
  weaving_sku?: string
  washing_sku?: string
  beam_instance_id?: string
  beam_id?: string
  quantity?: number
  setup_type?: string
  setup_label?: string
  // 水洗
  machine_id?: string
  batch_code?: string
  plan_length?: number | null
  input_length?: number | null
  customer?: string | null
  // 通用
  start: string | null
  end: string | null
  derived: boolean
  data_source: string
  // 数据时间来源(整经/水洗=非CP-SAT约束)
  time_source?: string
  // 缺水洗品番(工艺串联在织造节点终止)
  missing_washing?: boolean
  missing_reason?: string
  chain_incomplete?: boolean
  chain_status?: string
  chain_missing_fields?: string[]
  chain_reason?: string
  mapping_state?: string
  mapping_source?: string
  mapping_complete?: boolean
  // 经轴/织造 的 flow 关联
  flow_id?: string
  flow_ids?: string[]
  // 整经条详情
  warp_spec?: string
  beam_instance_ids?: string[]
  source_cell?: string
}

export interface ProcessGroup {
  process: ProcessName
  bars: ProcessBar[]
}

export interface ProcessGanttResult {
  process_order: ProcessName[]
  groups: ProcessGroup[]
  stats: Record<string, number>
  chain_broken_reasons: Record<string, number>
  order_warnings: string[]
  chains: any[]
  beam_instances_count: number
  note: string
  time_source_summary?: Record<string, number>
  product_reconciliation?: ProductChainRow[]
  unmatched_washing_rows?: Record<string, unknown>[]
  warping_resource_mode?: string
  view_mode?: 'executable' | 'invalid' | 'initial'
}

export interface ProductChainRow {
  flow_id: string
  product_id: string
  product_back_sku: string | null
  warp_beam_sku: string | null
  weaving_sku: string | null
  washing_sku: string | null
  target_loom_ids: string[]
  status: string
  reason: string
  missing_fields: string[]
  mapping_state: string
  mapping_source: string
  mapping_confidence: string
  terminal_process: string
  publishable: boolean
  in_weave_plan: boolean
  in_process_master: boolean
}

export interface WarpBeamSkuRow {
  warp_beam_sku: string
  set_length: number | null
  warp_threads: number | null
  reed: string | null
  yarn_code: string | null
  unit_consumption_kg: number | null
  initial_inventory: number | null
  plan_dates: string[]
  target_loom_ids: string[]
  source_sheet: string
  data_source: string
}

export interface WarpBeamsResult {
  count: number
  beams: WarpBeamSkuRow[]
}

export interface WarpBeamInstance {
  beam_instance_id: string
  warp_beam_sku: string
  plan_date: string
  instance_meters: number
  target_loom_id: string[]
  warping_machine_id: string
  is_derived: boolean
  data_source: string
  status: string
}

export interface WarpInstancesResult {
  count: number
  virtual_count: number
  real_count: number
  instances: WarpBeamInstance[]
  note: string
}

export interface WarpInventoryDay {
  date: string
  warp_complete_m: number
  weave_mount_demand_m: number
  stock_m: number
}

export interface WarpInventoryRow {
  warp_beam_sku: string
  initial_inventory: number | null
  daily: WarpInventoryDay[]
  anomaly_dates: string[]
}

export interface WarpInventoryResult {
  count: number
  inventory: WarpInventoryRow[]
  anomaly_dates: { beam: string; date: string; stock_m: number }[]
}

export interface WeeklyWarpingTask {
  task_id: string
  sequence: number
  warp_beam_sku: string
  product_ids: string[]
  order_due_minute?: number | null
  order_due_date?: string | null
  order_priority?: number
  planning_basis?: string
  plan_date: string
  start: string
  end: string
  complete_at: string
  plan_meters: number
  plan_count: number
  target_loom_id: string[]
  machine_placeholder: string
  warping_resource_mode: string
  data_source: string
  is_derived: boolean
  beam_instance_id?: string
}

export interface WeeklyWarpingPlan {
  schedule_start: string
  schedule_end: string
  horizon_days: number
  resource_mode: string
  resource_count: number
  minutes_per_beam: number
  tasks: WeeklyWarpingTask[]
  daily: { date: string; task_count: number; plan_count: number; plan_meters: number }[]
  unscheduled: { warp_beam_sku: string; remaining_meters: number; remaining_beams: number; reason: string }[]
  blocked_products: string[]
  stats: { task_count: number; beam_sku_count: number; plan_count: number; plan_meters: number; utilization: number }
  assumptions: string[]
}

export interface WeeklyWeavingTask {
  sequence: number
  task_id: string
  product_id: string
  warp_beam_sku: string | null
  beam_instance_id: string | null
  beam_allocations?: { beam_instance_id: string; allocated_meters: number; beam_total_meters: number; beam_available_at: string; is_derived: boolean }[]
  beam_quantity_ok?: boolean | null
  beam_ledger_status?: string | null
  loom_id: string
  source_target_loom_ids: string[]
  target_mapping_status: string | null
  source_target_match: boolean | null
  beam_ready_at: string | null
  start: string
  end: string
  scheduled_quantity: number
  changeover_type: string | null
  order_ok: boolean
  status: string
  data_source: string
}

export interface WeeklyWeavingPlan {
  schedule_start: string
  schedule_end: string
  horizon_days: number
  tasks: WeeklyWeavingTask[]
  daily: { date: string; task_count: number; scheduled_meters: number; loom_count: number }[]
  order_violations: { task_id: string; reason: string }[]
  stats: { task_count: number; product_count: number; loom_count: number; scheduled_meters: number; unscheduled_meters: number; order_violation_count: number }
  simulation_basis?: {
    compatibility_mode: string
    material_enabled: boolean
    beam_enabled: boolean
    target_loom_violation_count: number
    target_loom_missing_count: number
    beam_ledger_shortage_count?: number
    beam_instance_ids_derived?: boolean
    publishable: boolean
  }
  note: string
}

export interface TaskPoolRow {
  task_id: string
  product_id: string
  required_quantity: number
  scheduled_quantity: number
  unscheduled_quantity: number
  due_date: string | null
  priority: number
  split_allowed: boolean
  min_batch_qty: number | null
  max_parts: number | null
  locked: boolean
  lock_reason: string | null
  beam_code: string | null
  flow_id?: string
  product_back_sku?: string | null
  warp_beam_sku?: string | null
  weaving_sku?: string | null
  washing_sku?: string | null
  beam_instance_id?: string | null
  chain_status?: string
  chain_missing_fields?: string[]
  chain_reason?: string
  mapping_state?: string
  mapping_source?: string
  process: string | null
  reed: string | null
  compatible_loom_count: number | null
  allowed_loom_count: number | null
  assigned_looms: string[]
  machine_id: string | null
  assign_start: string | null
  assign_end: string | null
  lateness_minutes: number
  changeover_type: string | null
  status: string
  current_process: string
  current_status: string
  blocked_reason: string
  primary_reason: string
  secondary_reasons: string[]
  data_source: string
}

export interface TaskPoolResult {
  tasks: TaskPoolRow[]
  count: number
  by_status: Record<string, number>
  chain_status_count?: Record<string, number>
  sum_required: number
  sum_scheduled: number
  sum_unscheduled: number
  urgent_window_days: number
  due_urgent_count: number
  locked_count: number
  split_count: number
}

export interface LoomResourceRow {
  loom_id: string
  region: string
  status: string
  available: boolean
  current_product: string | null
  capacity_m_per_day: number | null
  waste_edge_disc: boolean | null
  waste_edge_hole: string | null
  edge_cut: boolean | null
  big_package: boolean | null
  water_filter: boolean | null
  yarn_frame: boolean | null
  reed: string | null
  full_width_edge_support: string | null
  wheels_gear: boolean | null
  heald: boolean | null
  compatible_products: string[]
  tooling_note: string
  used: boolean
  assigned_task_count: number
  scheduled_minutes: number
  assign_starts: string[]
  assign_ends: string[]
  products_scheduled: string[]
  source_sheet: string
}

export interface LoomResourcesResult {
  looms: LoomResourceRow[]
  count: number
  available_count: number
  unavailable_count: number
  used_count: number
  idle_count: number
  by_region: Record<string, number>
  by_status: Record<string, number>
  capability_summary: Record<string, number>
  data_source: string
  note: string
}
