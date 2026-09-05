import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import TasksPanel from './components/TasksPanel'
import type { TaskPoolResult } from './types'

const { poolOk, apiMocks } = vi.hoisted(() => {
  const poolOk: TaskPoolResult = {
    tasks: [
      { task_id: 'T1', product_id: 'P1', required_quantity: 7200, scheduled_quantity: 7200, unscheduled_quantity: 0, due_date: '2026-05-31', priority: 1, split_allowed: false, min_batch_qty: 500, max_parts: 3, locked: false, lock_reason: null, beam_code: 'WP550', process: null, reed: null, compatible_loom_count: 105, allowed_loom_count: 105, assigned_looms: ['#412'], machine_id: '#412', assign_start: '2026-04-01', assign_end: '2026-04-21', lateness_minutes: 0, changeover_type: 'threading', status: '已排程', current_process: '织造生产', current_status: '已排程', blocked_reason: '', primary_reason: '', secondary_reasons: [], data_source: 'CP-SAT排程结果' },
      { task_id: 'T2', product_id: 'P2', required_quantity: 3000, scheduled_quantity: 0, unscheduled_quantity: 3000, due_date: '2026-05-31', priority: 3, split_allowed: true, min_batch_qty: 500, max_parts: 2, locked: false, lock_reason: null, beam_code: null, process: null, reed: null, compatible_loom_count: 0, allowed_loom_count: 0, assigned_looms: [], machine_id: null, assign_start: null, assign_end: null, lateness_minutes: 0, changeover_type: null, status: '未排程', current_process: '织造生产', current_status: '等待条件', blocked_reason: '无兼容织机', primary_reason: 'NO_COMPATIBLE_LOOM', secondary_reasons: [], data_source: '来源表' },
      { task_id: 'T3', product_id: 'P3', required_quantity: 5000, scheduled_quantity: 2000, unscheduled_quantity: 3000, due_date: '2026-05-31', priority: 2, split_allowed: false, min_batch_qty: 500, max_parts: 3, locked: true, lock_reason: '人工锁定', beam_code: 'WP451', process: null, reed: null, compatible_loom_count: 10, allowed_loom_count: 10, assigned_looms: ['#101'], machine_id: '#101', assign_start: '2026-04-02', assign_end: '2026-04-05', lateness_minutes: 120, changeover_type: 'same', status: '锁定', current_process: '织造生产', current_status: '进行中', blocked_reason: '', primary_reason: '', secondary_reasons: [], data_source: '来源表' },
    ],
    count: 3,
    by_status: { '已排程': 1, '未排程': 1, '锁定': 1 },
    sum_required: 15200,
    sum_scheduled: 9200,
    sum_unscheduled: 6000,
    urgent_window_days: 14,
    due_urgent_count: 0,
    locked_count: 1,
    split_count: 1,
  }
  const apiMocks = { getTaskPool: vi.fn() }
  return { poolOk, apiMocks }
})

vi.mock('./api', () => apiMocks)

function mockTaskPool(overrides: Partial<TaskPoolResult> = {}) {
  apiMocks.getTaskPool.mockResolvedValue({ ...poolOk, ...overrides })
}

describe('TasksPanel', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('顶部统计显示任务数/需求/已排/未排', async () => {
    mockTaskPool()
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    expect(screen.getByTestId('task-stat-total')).toHaveTextContent('3')
    expect(screen.getByTestId('task-stat-required')).toHaveTextContent('15,200')
    expect(screen.getByTestId('task-stat-unscheduled')).toHaveTextContent('6,000')
  })

  it('表格列全并显示状态徽章(已排程/未排程/锁定)', async () => {
    mockTaskPool()
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    expect(screen.getAllByTestId('task-row').length).toBe(3)
    expect(screen.getAllByText('已排程').length).toBeGreaterThan(0)
    expect(screen.getAllByText('未排程').length).toBeGreaterThan(0)
    expect(screen.getAllByText('锁定').length).toBeGreaterThan(0)
  })

  it('按状态筛选', async () => {
    mockTaskPool()
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    const statusSel = screen.getByLabelText(/状态/)
    fireEvent.change(statusSel, { target: { value: '未排程' } })
    expect(screen.getAllByTestId('task-row').length).toBe(1)
    expect(screen.getByText('T2')).toBeInTheDocument()
    expect(screen.queryByText('T1')).not.toBeInTheDocument()
  })

  it('按产品筛选', async () => {
    mockTaskPool()
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    const prodSel = screen.getByLabelText(/产品/)
    fireEvent.change(prodSel, { target: { value: 'P2' } })
    expect(screen.getAllByTestId('task-row').length).toBe(1)
    expect(screen.getByText('T2')).toBeInTheDocument()
  })

  it('搜索任务号/产品/织机', async () => {
    mockTaskPool()
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    const search = screen.getByLabelText(/搜索/)
    fireEvent.change(search, { target: { value: '#412' } })
    expect(screen.getAllByTestId('task-row').length).toBe(1)
    expect(screen.getByText('T1')).toBeInTheDocument()
  })

  it('空数据不崩溃', async () => {
    mockTaskPool({ tasks: [], count: 0, by_status: {}, sum_required: 0, sum_scheduled: 0, sum_unscheduled: 0, due_urgent_count: 0, locked_count: 0, split_count: 0 })
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-page')).toBeInTheDocument())
    expect(screen.queryAllByTestId('task-row').length).toBe(0)
  })

  it('接口失败显示错误', async () => {
    apiMocks.getTaskPool.mockRejectedValue(new Error('boom'))
    render(<TasksPanel />)
    await waitFor(() => expect(screen.getByTestId('tasks-error')).toBeInTheDocument())
    expect(screen.getByText(/加载失败/)).toBeInTheDocument()
  })
})
