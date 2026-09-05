import type { ScheduleResult, ScenarioSummary, SolveParams } from './types'

export const API_BASE = (import.meta as any).env?.VITE_API_BASE || 'http://127.0.0.1:8000'

export class ApiError extends Error {
  kind: 'connection' | 'timeout' | 'request' | 'server' | 'response'
  status?: number
  path: string

  constructor(message: string, kind: ApiError['kind'], path: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.path = path
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 90_000)
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
      signal: controller.signal,
    })
  } catch (error: any) {
    if (error?.name === 'AbortError') {
      throw new ApiError(`请求超时：排程服务在90秒内没有响应（${path}）`, 'timeout', path)
    }
    throw new ApiError(`无法连接排程服务 ${API_BASE}，请确认后端已经启动后重试。`, 'connection', path)
  } finally {
    window.clearTimeout(timeout)
  }
  if (!res.ok) {
    let detail = ''
    try {
      const j = await res.json()
      detail = j?.detail || j?.message || ''
    } catch { /* ignore */ }
    const suffix = detail ? `：${detail}` : ''
    if (res.status === 422) throw new ApiError(`请求参数或导入数据不符合要求${suffix}`, 'request', path, res.status)
    if (res.status >= 500) throw new ApiError(`排程服务处理失败（错误码 ${res.status}）${suffix}`, 'server', path, res.status)
    throw new ApiError(`接口请求失败（错误码 ${res.status}）${suffix}`, 'request', path, res.status)
  }
  try {
    return await res.json() as T
  } catch {
    throw new ApiError(`排程服务返回的数据格式不完整（${path}）`, 'response', path, res.status)
  }
}

export function health() {
  return request<{ status: string; engine: string; service?: string; data_status?: any }>('/api/health')
}

export function getScenario() {
  return request<ScenarioSummary>('/api/scenarios/current')
}

export function solveSchedule(params: SolveParams) {
  return request<ScheduleResult>('/api/schedules/solve', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export function getLatest() {
  return request<ScheduleResult>('/api/schedules/latest')
}

export function getSchedule(id: string) {
  return request<ScheduleResult>(`/api/schedules/${id}`)
}

export function getDiagnostics(id: string) {
  return request<any>(`/api/schedules/${id}/diagnostics`)
}

export function diagnosticCompare(params: { max_time_s: number; compatibility_mode: string }) {
  return request<any>('/api/schedules/diagnostic-compare', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export function getProcessOverview() {
  return request<any>('/api/process/overview')
}
export function getProcessTasks() {
  return request<any>('/api/process/tasks')
}
export function getHomepageProgress() {
  return request<any>('/api/process/progress')
}
export function getProcessCases() {
  return request<any>('/api/process/cases')
}
export function getProcessGantt() {
  return request<any>('/api/process/gantt')
}
export function getWarpingBeams() {
  return request<any>('/api/warping/beams')
}
export function getWarpingInstances() {
  return request<any>('/api/warping/instances')
}
export function getWarpingInventory() {
  return request<any>('/api/warping/inventory')
}
export function getWeeklyWarpingPlan() {
  return request<any>('/api/warping/weekly-plan')
}
export function getWeeklyWeavingPlan() {
  return request<any>('/api/weaving/weekly-plan')
}
export function runWeeklySimulation(params: {
  schedule_id?: string
  snapshot_id?: string
  commit_final_state?: boolean
  lead_time_minutes?: number
  edge_support_use_limit?: number
  warping_minutes_per_beam?: number
  threading_minutes?: number
} = {}) {
  return request<any>('/api/simulation/run', {
    method: 'POST', body: JSON.stringify(params),
  })
}
export function getLatestShopfloorSnapshot() {
  return request<any>('/api/shopfloor/snapshot/latest')
}
export function getShopfloorSnapshot(id: string) {
  return request<any>(`/api/shopfloor/snapshot/${id}`)
}
export function saveShopfloorSnapshot(payload: Record<string, any>) {
  return request<any>('/api/shopfloor/snapshot', {
    method: 'POST', body: JSON.stringify(payload),
  })
}
export function getTaskPool() {
  return request<any>('/api/tasks/pool')
}
export function getLoomResources() {
  return request<any>('/api/looms/resource')
}
export function previewDataImport(payload: { filename: string; content_base64: string }) {
  return request<any>('/api/data/import-preview', { method: 'POST', body: JSON.stringify(payload) })
}
export function getDataSnapshots() {
  return request<any>('/api/data/snapshots')
}
export function saveDataSnapshot(payload: { preview_id: string; note?: string }) {
  return request<any>('/api/data/snapshots', { method: 'POST', body: JSON.stringify(payload) })
}
