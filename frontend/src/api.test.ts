import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getScenario, health } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('API 中文错误分类', () => {
  it('网络不可达时给出后端连接提示', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(getScenario()).rejects.toMatchObject({ kind: 'connection' })
    await expect(getScenario()).rejects.toThrow(/无法连接排程服务/)
  })

  it('服务端错误包含状态码和业务提示', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: '模拟内部异常' }), {
      status: 500, headers: { 'Content-Type': 'application/json' },
    }))))
    await expect(getScenario()).rejects.toMatchObject({ kind: 'server', status: 500 })
    await expect(getScenario()).rejects.toThrow(/排程服务处理失败.*模拟内部异常/)
  })

  it('成功健康检查能够解析结果', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok', engine: 'cp-sat' }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })))
    await expect(health()).resolves.toEqual({ status: 'ok', engine: 'cp-sat' })
  })

  it('ApiError保留接口路径用于追踪', () => {
    const error = new ApiError('错误', 'request', '/api/test', 422)
    expect(error).toMatchObject({ name: 'ApiError', kind: 'request', path: '/api/test', status: 422 })
  })
})
