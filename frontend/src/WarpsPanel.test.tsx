import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import WarpsPanel from './components/WarpsPanel'
import type { WarpBeamsResult, WarpInstancesResult, WarpInventoryResult, WeeklyWarpingPlan } from './types'

const { beams12, instances7, inventoryOk, apiMocks } = vi.hoisted(() => {
  const beams12: WarpBeamsResult = {
    count: 12,
    beams: Array.from({ length: 12 }, (_, i) => ({
      warp_beam_sku: `WP${550 - i}`,
      set_length: 4800 + i,
      warp_threads: 4500 + i,
      reed: '9.3',
      yarn_code: 'LS7056AB',
      unit_consumption_kg: 0.29375,
      initial_inventory: null,
      plan_dates: i < 5 ? ['2026-04-03'] : [],
      target_loom_ids: i === 0 ? ['LOOM-502', 'LOOM-603'] : [],
      source_sheet: '整经预测辅助表',
      data_source: '来源表',
    })),
  }
  const instances7: WarpInstancesResult = {
    count: 7,
    virtual_count: 7,
    real_count: 0,
    instances: Array.from({ length: 7 }, (_, i) => ({
      beam_instance_id: `BEAM-WP550-2026-06-15-0${i + 1}`,
      warp_beam_sku: 'WP550',
      plan_date: '2026-06-15',
      instance_meters: 9660,
      target_loom_id: ['LOOM-305'],
      warping_machine_id: '',
      is_derived: true,
      data_source: '推导数据(源表无实体经轴编号)',
      status: '整经计划',
    })),
    note: '源表无实体经轴编号，实例全部为虚拟(推导)数据。',
  }
  const inventoryOk: WarpInventoryResult = {
    count: 12,
    inventory: [
      { warp_beam_sku: 'WP550', initial_inventory: null, daily: [
        { date: '2026-06-15', warp_complete_m: 9660, weave_mount_demand_m: 0, stock_m: 9660 },
        { date: '2026-06-16', warp_complete_m: 9660, weave_mount_demand_m: 4687.5, stock_m: 19372.5 },
      ], anomaly_dates: [] },
    ],
    anomaly_dates: [],
  }
  const apiMocks = {
    getWarpingBeams: vi.fn(),
    getWarpingInstances: vi.fn(),
    getWarpingInventory: vi.fn(),
    getWeeklyWarpingPlan: vi.fn(),
    getWeeklyWeavingPlan: vi.fn(),
  }
  return { beams12, instances7, inventoryOk, apiMocks }
})

vi.mock('./api', () => apiMocks)

function mockAll(beams = beams12, instances = instances7, inventory = inventoryOk) {
  apiMocks.getWarpingBeams.mockResolvedValue(beams)
  apiMocks.getWarpingInstances.mockResolvedValue(instances)
  apiMocks.getWarpingInventory.mockResolvedValue(inventory)
  const weekly: WeeklyWarpingPlan = {
    schedule_start: '2026-04-01', schedule_end: '2026-04-08', horizon_days: 7,
    resource_mode: '计划池', resource_count: 1, minutes_per_beam: 240,
    tasks: [
      { task_id: 'WARP-WEEK-WP550-01', sequence: 1, warp_beam_sku: 'WP550', product_ids: ['PH550'], plan_date: '2026-04-01', start: '2026-04-01T00:00:00', end: '2026-04-01T04:00:00', complete_at: '2026-04-01T04:00:00', plan_meters: 4830, plan_count: 1, target_loom_id: ['LOOM-305'], machine_placeholder: '整经计划池', warping_resource_mode: '计划池', data_source: '一周滚动排产推导', is_derived: true },
      { task_id: 'WARP-WEEK-WP551-01', sequence: 2, warp_beam_sku: 'WP551', product_ids: ['PH551'], plan_date: '2026-04-01', start: '2026-04-01T04:00:00', end: '2026-04-01T08:00:00', complete_at: '2026-04-01T08:00:00', plan_meters: 3600, plan_count: 1, target_loom_id: ['LOOM-306'], machine_placeholder: '整经计划池', warping_resource_mode: '计划池', data_source: '一周滚动排产推导', is_derived: true },
    ],
    daily: Array.from({ length: 7 }, (_, i) => ({ date: `2026-04-0${i + 1}`, task_count: i === 0 ? 2 : 0, plan_count: i === 0 ? 2 : 0, plan_meters: i === 0 ? 8430 : 0 })),
    unscheduled: [], blocked_products: ['PH-NO-BEAM'],
    stats: { task_count: 2, beam_sku_count: 2, plan_count: 2, plan_meters: 8430, utilization: 0.0794 },
    assumptions: ['源表没有具体整经机编号，按一个整经计划池串行模拟。'],
  }
  apiMocks.getWeeklyWarpingPlan.mockResolvedValue(weekly)
  apiMocks.getWeeklyWeavingPlan.mockResolvedValue({
    schedule_start: '2026-04-01', schedule_end: '2026-04-08', horizon_days: 7,
    tasks: [{ sequence: 1, task_id: 'T1', product_id: 'PH550', warp_beam_sku: 'WP550', beam_instance_id: 'WB-WP550-001', loom_id: '#305', beam_ready_at: '2026-04-01T04:00:00', start: '2026-04-01T04:00:00', end: '2026-04-07T00:00:00', scheduled_quantity: 2200, changeover_type: 'beam_change', order_ok: true, status: '已排织造', data_source: 'CP-SAT' }],
    daily: Array.from({ length: 7 }, (_, i) => ({ date: `2026-04-0${i + 1}`, task_count: i === 0 ? 1 : 0, scheduled_meters: i === 0 ? 2200 : 0, loom_count: i === 0 ? 1 : 0 })),
    order_violations: [], stats: { task_count: 1, product_count: 1, loom_count: 1, scheduled_meters: 2200, unscheduled_meters: 800, order_violation_count: 0 },
    note: '织造最早开始时间由对应经轴品番首根完成时间确定。',
  })
}

describe('WarpsPanel', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('顶部显示 12 类经轴品番 / 7 根虚拟经轴 / 2 个本周整经任务', async () => {
    mockAll()
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-page')).toBeInTheDocument())
    expect(screen.getByText('12 类')).toBeInTheDocument()
    expect(screen.getByText('7 根')).toBeInTheDocument()
    expect(screen.getByText('2 个')).toBeInTheDocument()
  })

  it('展示一周七天整经计划并说明工艺先后约束', async () => {
    mockAll()
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-weekly-plan')).toBeInTheDocument())
    expect(screen.getAllByTestId('warping-day')).toHaveLength(7)
    expect(screen.getAllByTestId('weekly-warping-row')).toHaveLength(2)
    expect(screen.getByText(/整经完成 → 经轴上轴 → 织造/)).toBeInTheDocument()
    expect(screen.getAllByText('整经计划池').length).toBeGreaterThan(0)
  })

  it('只展示织造衔接摘要并跳转工况模拟，不再加载和展示重复初排表', async () => {
    mockAll()
    const onOpenSimulation = vi.fn()
    render(<WarpsPanel executionPreview={{
      kpi: { solver_scheduled_quantity: 2200, simulated_quantity: 1800, reduced_quantity: 400, beam_bound_segment_count: 2, supplemental_warping_count: 1 },
      planning_trace: { decisions: [] },
    }} onOpenSimulation={onOpenSimulation} />)
    await waitFor(() => expect(screen.getByTestId('weaving-handoff-summary')).toBeInTheDocument())
    expect(screen.getByText(/最终织造时间、实际轴号、缩减原因/)).toBeInTheDocument()
    expect(screen.queryByTestId('weaving-weekly-plan')).not.toBeInTheDocument()
    expect(screen.queryByTestId('executable-weaving-plan')).not.toBeInTheDocument()
    expect(apiMocks.getWeeklyWeavingPlan).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '查看执行仿真' }))
    expect(onOpenSimulation).toHaveBeenCalledOnce()
  })

  it('经轴品番主档列出品番/设定米数/钢筘/纱线', async () => {
    mockAll()
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-page')).toBeInTheDocument())
    expect(screen.getByTestId('warps-sku')).toBeInTheDocument()
    expect(screen.getAllByText('WP550').length).toBeGreaterThan(0)
  })

  it('经轴实例表格显示 7 根虚拟经轴及其状态/数据来源', async () => {
    mockAll()
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-page')).toBeInTheDocument())
    const section = screen.getByTestId('warps-instances')
    expect(section.querySelectorAll('tbody tr').length).toBe(7)
    expect(screen.getByText('BEAM-WP550-2026-06-15-01')).toBeInTheDocument()
    expect(screen.getAllByText(/推导数据/).length).toBeGreaterThan(0)
  })

  it('经轴库存显示每日 整经完成量/上轴需求/结存', async () => {
    mockAll()
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-page')).toBeInTheDocument())
    expect(screen.getByTestId('warps-inventory')).toBeInTheDocument()
    expect(screen.getAllByText('19372.5').length).toBeGreaterThan(0)
  })

  it('异常日期(负结存)被标出', async () => {
    mockAll(beams12, instances7, {
      count: 1,
      inventory: [{ warp_beam_sku: 'WN446', initial_inventory: 0, daily: [
        { date: '2026-04-04', warp_complete_m: 0, weave_mount_demand_m: 1, stock_m: -1 },
      ], anomaly_dates: ['2026-04-04'] }],
      anomaly_dates: [{ beam: 'WN446', date: '2026-04-04', stock_m: -1 }],
    })
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-page')).toBeInTheDocument())
    expect(screen.getByTestId('inv-anomaly')).toBeInTheDocument()
    expect(screen.getByText(/异常日期/)).toBeInTheDocument()
  })

  it('空数据显示空态且不崩溃', async () => {
    mockAll(
      { count: 0, beams: [] },
      { count: 0, virtual_count: 0, real_count: 0, instances: [], note: '无' },
      { count: 0, inventory: [], anomaly_dates: [] },
    )
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-page')).toBeInTheDocument())
    expect(screen.getByTestId('warps-sku')).toBeInTheDocument()
    expect(screen.getByTestId('warps-inventory')).toBeInTheDocument()
  })

  it('接口失败时显示错误状态', async () => {
    apiMocks.getWarpingBeams.mockRejectedValue(new Error('boom'))
    apiMocks.getWarpingInstances.mockResolvedValue(instances7)
    apiMocks.getWarpingInventory.mockResolvedValue(inventoryOk)
    apiMocks.getWeeklyWarpingPlan.mockResolvedValue({})
    render(<WarpsPanel />)
    await waitFor(() => expect(screen.getByTestId('warps-error')).toBeInTheDocument())
    expect(screen.getByText(/加载失败/)).toBeInTheDocument()
  })
})
