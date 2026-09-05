import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import SimulationPanel from './components/SimulationPanel'

const { runWeeklySimulation } = vi.hoisted(() => ({ runWeeklySimulation: vi.fn() }))
vi.mock('./api', () => ({ runWeeklySimulation }))

describe('SimulationPanel', () => {
  it('有求解时固化结果时直接展示，不在页面初始化时重新模拟', async () => {
    runWeeklySimulation.mockClear()
    render(<SimulationPanel scheduleId="S0" initialData={{
      status: 'SIMULATED', schedule_start: '2026-04-01T00:00:00',
      solver_summary: { schedule_id: 'S0' }, validation: { ok: true },
      kpi: { simulated_quantity: 320, beam_bound_segment_count: 1, setup_type_counts: {} },
      events: [], forecasts: [], assumptions: [], warping_plan: [], threading_plan: [], loom_setup_plan: [],
    }} />)
    await waitFor(() => expect(screen.getByTestId('simulation-page')).toBeInTheDocument())
    expect(runWeeklySimulation).not.toHaveBeenCalled()
    expect(screen.getByText('320 米')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新已保存结果' })).toBeInTheDocument()
  })

  it('一周横轴从排程起点开始，不受本地时区偏移', async () => {
    runWeeklySimulation.mockResolvedValue({
      status: 'SIMULATED', schedule_start: '2026-04-01T00:00:00',
      solver_summary: { schedule_id: 'S1' }, validation: { ok: true },
      kpi: { simulated_quantity: 1000, warping_task_count: 1, threading_task_count: 1,
        setup_segment_count: 1, setup_type_counts: {} },
      events: [], forecasts: [], assumptions: [], warping_plan: [], threading_plan: [], loom_setup_plan: [],
    })
    render(<SimulationPanel scheduleId="S1" />)

    await waitFor(() => expect(screen.getByTestId('simulation-page')).toBeInTheDocument())
    expect(screen.getByText('04-01')).toBeInTheDocument()
    expect(screen.getByText('04-07')).toBeInTheDocument()
    expect(screen.queryByText('03-31')).not.toBeInTheDocument()
  })

  it('跨天织造事件会在实际占用的每一天分段显示', async () => {
    runWeeklySimulation.mockResolvedValue({
      status: 'SIMULATED', schedule_start: '2026-04-01T00:00:00',
      solver_summary: { schedule_id: 'S2' }, validation: { ok: true },
      kpi: { simulated_quantity: 1000, setup_type_counts: {} },
      events: [{
        event_id: 'E1', event_type: 'weaving', product_id: 'P-CROSS', resource_id: '#301',
        start: '2026-04-01T20:00:00', end: '2026-04-03T06:00:00',
        start_minute: 1200, end_minute: 3240,
      }],
      forecasts: [], assumptions: [], warping_plan: [], threading_plan: [], loom_setup_plan: [],
    })
    render(<SimulationPanel scheduleId="S2" />)

    await waitFor(() => expect(screen.getByTestId('simulation-page')).toBeInTheDocument())
    expect(screen.getAllByText('P-CROSS')).toHaveLength(3)
    expect(screen.getByText('20:00—24:00 续')).toBeInTheDocument()
    expect(screen.getByText('续 00:00—24:00 续')).toBeInTheDocument()
    expect(screen.getByText('续 00:00—06:00')).toBeInTheDocument()
  })

  it('经轴或七天边界导致缩减时会明确显示对账结果', async () => {
    runWeeklySimulation.mockResolvedValue({
      status: 'SIMULATED_ADJUSTED', schedule_start: '2026-04-01T00:00:00',
      solver_summary: { schedule_id: 'S3' }, validation: { ok: true },
      kpi: { solver_scheduled_quantity: 1000, simulated_quantity: 760,
        reduced_quantity: 240, beam_bound_segment_count: 2,
        source_warping_task_count: 3, supplemental_warping_count: 1,
        setup_type_counts: {} },
      events: [], forecasts: [], assumptions: [], warping_plan: [], threading_plan: [], loom_setup_plan: [],
    })
    render(<SimulationPanel scheduleId="S3" />)

    await waitFor(() => expect(screen.getByTestId('simulation-audit')).toBeInTheDocument())
    expect(screen.getByText(/已明确缩减 240 米/)).toBeInTheDocument()
    expect(screen.getByText('760 米')).toBeInTheDocument()
    expect(screen.getByText('1 个')).toBeInTheDocument()
  })

  it('展示订单到可执行织造的完整决策链和逐轴明细', async () => {
    runWeeklySimulation.mockResolvedValue({
      status: 'SIMULATED', schedule_start: '2026-04-01T00:00:00',
      solver_summary: { schedule_id: 'S4' }, validation: { ok: true },
      kpi: { simulated_quantity: 500, beam_bound_segment_count: 1, setup_type_counts: {} },
      events: [], forecasts: [], assumptions: [], warping_plan: [], threading_plan: [], loom_setup_plan: [],
      planning_trace: {
        stages: [
          { key: 'orders', label: '订单需求', value: '1 单 / 500 米', detail: '读取订单要求' },
          { key: 'execution', label: '可执行织造', value: '500 米', detail: '七天内完成' },
        ],
        rules: ['订单按交期优先。', '每段绑定具体经轴。'],
        decisions: [{
          task_id: 'T-P1', order_id: 'P1', product_id: 'P1', due_at: '2026-04-07T00:00:00',
          priority: 2, split_allowed: false, requested_quantity: 500, warp_beam_sku: 'WP1',
          required_beam_count: 1, beam_ids: ['BEAM-WP1-001'], beam_origins: ['weekly_warping_plan'],
          loom_id: '#101', beam_ready_at: '2026-04-01T04:00:00', required_ready_by: '2026-04-01T06:00:00',
          lead_time_ok: true, first_weave_start: '2026-04-01T08:00:00', last_weave_end: '2026-04-03T00:00:00',
          executable_quantity: 500, reduced_quantity: 0, status: '可执行', reason: '全部约束通过',
        }],
      },
    })
    render(<SimulationPanel scheduleId="S4" />)

    await waitFor(() => expect(screen.getByTestId('planning-trace')).toBeInTheDocument())
    expect(screen.getByText('订单驱动的整经—织造联动决策')).toBeInTheDocument()
    expect(screen.getByText('BEAM-WP1-001')).toBeInTheDocument()
    expect(screen.getByText('全部约束通过')).toBeInTheDocument()
  })
})
