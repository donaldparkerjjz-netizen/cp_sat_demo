import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LoomsPanel from './components/LoomsPanel'
import type { LoomResourcesResult } from './types'

const { loomsOk, apiMocks } = vi.hoisted(() => {
  const loomsOk: LoomResourcesResult = {
    looms: [
      { loom_id: '#101', region: '区域1', status: '未安排', available: true, current_product: null, capacity_m_per_day: 400, waste_edge_disc: true, waste_edge_hole: '1', edge_cut: true, big_package: true, water_filter: false, yarn_frame: true, reed: '9.3钢筘', full_width_edge_support: '2350', wheels_gear: null, heald: null, compatible_products: [], tooling_note: '废边盘 / 切边 / 大卷装 / 纱架', used: false, assigned_task_count: 0, scheduled_minutes: 0, assign_starts: [], assign_ends: [], products_scheduled: [], source_sheet: '②织机状态' },
      { loom_id: '#301', region: '区域3', status: 'AB', available: true, current_product: 'PH555120', capacity_m_per_day: 400, waste_edge_disc: false, waste_edge_hole: null, edge_cut: false, big_package: true, water_filter: true, yarn_frame: true, reed: '9.3钢筘', full_width_edge_support: '2350', wheels_gear: null, heald: null, compatible_products: ['PH555120'], tooling_note: '大卷装 / 水过滤 / 纱架', used: true, assigned_task_count: 2, scheduled_minutes: 5000, assign_starts: ['2026-04-01'], assign_ends: ['2026-04-10'], products_scheduled: ['PH555120'], source_sheet: '②织机状态' },
      { loom_id: '#901', region: '区域9', status: 'NULL', available: false, current_product: null, capacity_m_per_day: null, waste_edge_disc: false, waste_edge_hole: null, edge_cut: false, big_package: false, water_filter: false, yarn_frame: false, reed: null, full_width_edge_support: null, wheels_gear: null, heald: null, compatible_products: [], tooling_note: '', used: false, assigned_task_count: 0, scheduled_minutes: 0, assign_starts: [], assign_ends: [], products_scheduled: [], source_sheet: '②织机状态' },
    ],
    count: 3,
    available_count: 2,
    unavailable_count: 1,
    used_count: 1,
    idle_count: 2,
    by_region: { '区域1': 1, '区域3': 1, '区域9': 1 },
    by_status: { '未安排': 1, 'AB': 1, '待确认/不可用': 1 },
    capability_summary: { waste_edge_disc: 1, edge_cut: 1, big_package: 2, water_filter: 1, yarn_frame: 2 },
    data_source: '来源表(②织机状态/织造计划) + 排程结果',
    note: '织机主档 108 台；当前状态/能力取自 ②织机状态与织造计划。',
  }
  const apiMocks = { getLoomResources: vi.fn() }
  return { loomsOk, apiMocks }
})

vi.mock('./api', () => apiMocks)

function mockLooms(overrides: Partial<LoomResourcesResult> = {}) {
  apiMocks.getLoomResources.mockResolvedValue({ ...loomsOk, ...overrides })
}

describe('LoomsPanel', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('顶部统计显示织机/可用/已排占用', async () => {
    mockLooms()
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    expect(screen.getByTestId('loom-stat-total')).toHaveTextContent('3')
    expect(screen.getByTestId('loom-stat-avail')).toHaveTextContent('2')
    expect(screen.getByTestId('loom-stat-used')).toHaveTextContent('1')
  })

  it('表格列全并显示工装能力/状态', async () => {
    mockLooms()
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    expect(screen.getAllByTestId('loom-row').length).toBe(3)
    expect(screen.getByText('#101')).toBeInTheDocument()
    expect(screen.getAllByText('PH555120').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/废边盘/).length).toBeGreaterThan(0)
  })

  it('按状态筛选', async () => {
    mockLooms()
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    const sel = screen.getByLabelText(/状态/)
    fireEvent.change(sel, { target: { value: 'AB' } })
    expect(screen.getAllByTestId('loom-row').length).toBe(1)
    expect(screen.getByText('#301')).toBeInTheDocument()
    expect(screen.queryByText('#101')).not.toBeInTheDocument()
  })

  it('按区域筛选', async () => {
    mockLooms()
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    const sel = screen.getByLabelText(/区域/)
    fireEvent.change(sel, { target: { value: '区域9' } })
    expect(screen.getAllByTestId('loom-row').length).toBe(1)
    expect(screen.getByText('#901')).toBeInTheDocument()
  })

  it('搜索机号/产品', async () => {
    mockLooms()
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    const input = screen.getByLabelText(/搜索/)
    fireEvent.change(input, { target: { value: 'PH555120' } })
    expect(screen.getAllByTestId('loom-row').length).toBe(1)
    expect(screen.getByText('#301')).toBeInTheDocument()
  })

  it('空数据不崩溃', async () => {
    mockLooms({ looms: [], count: 0, available_count: 0, unavailable_count: 0, used_count: 0, idle_count: 0, by_region: {}, by_status: {}, capability_summary: {} })
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-page')).toBeInTheDocument())
    expect(screen.queryAllByTestId('loom-row').length).toBe(0)
  })

  it('接口失败显示错误', async () => {
    apiMocks.getLoomResources.mockRejectedValue(new Error('boom'))
    render(<LoomsPanel />)
    await waitFor(() => expect(screen.getByTestId('looms-error')).toBeInTheDocument())
    expect(screen.getByText(/加载失败/)).toBeInTheDocument()
  })
})
