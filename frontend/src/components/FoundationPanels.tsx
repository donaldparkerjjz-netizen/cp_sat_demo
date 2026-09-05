import React, { useMemo } from 'react'
import { API_BASE } from '../api'
import type { CompatMode, ScenarioSummary, ScheduleResult } from '../types'

export type ServiceState = 'checking' | 'online' | 'offline'

export function ServiceStatus({ state, lastSuccess, onRetry }: {
  state: ServiceState
  lastSuccess: string
  onRetry: () => void
}) {
  const label = state === 'online' ? '后端已连接' : state === 'offline' ? '后端未连接' : '正在检查后端'
  return (
    <div className={`service-status ${state}`} data-testid="service-status" title={`API：${API_BASE}`}>
      <i />
      <span>{label}</span>
      {lastSuccess && <small>最近成功 {lastSuccess}</small>}
      {state !== 'online' && <button onClick={onRetry}>重新连接</button>}
    </div>
  )
}

type QualityRow = {
  severity: '阻断' | '警告' | '提示'
  object: string
  message: string
  impact: string
  source: string
  action: string
}

function inferQuality(message: string, severity: QualityRow['severity'], source: string): QualityRow {
  const m = message || '未提供问题说明'
  if (/经轴|轴号/.test(m)) return { severity, object: '经轴', message: m, impact: '影响整经或织造逐轴执行', source, action: '补充经轴品番、实体轴号和剩余米数' }
  if (/织机|适配/.test(m)) return { severity, object: '织机', message: m, impact: '影响机台候选与产能判断', source, action: '确认产品—织机适配关系和设备状态' }
  if (/交期|优先级|订单/.test(m)) return { severity, object: '订单', message: m, impact: '影响订单排序和准交判断', source, action: '取得真实订单交期与优先级' }
  if (/效率|产能/.test(m)) return { severity, object: '产能', message: m, impact: '影响生产时长和需求覆盖量', source, action: '补充产品在各织机上的实际效率' }
  if (/物料|到货|库存|纱线/.test(m)) return { severity, object: '物料', message: m, impact: '影响整经开工可行性', source, action: '确认库存和到货时间' }
  if (/工装|钢筘|边撑/.test(m)) return { severity, object: '工装', message: m, impact: '影响设备工艺适配', source, action: '补充工装需求和可用库存' }
  return { severity, object: '基础数据', message: m, impact: '可能影响排程可信度', source, action: '核对来源数据并确认处理方式' }
}

export function DataQualityPanel({ scenario, result }: { scenario: ScenarioSummary | null; result: ScheduleResult | null }) {
  const rows = useMemo<QualityRow[]>(() => {
    const items: QualityRow[] = []
    for (const x of scenario?.data_errors ?? []) items.push(inferQuality(x, '阻断', '当前数据快照'))
    for (const x of scenario?.data_warnings ?? []) items.push(inferQuality(x, '警告', '当前数据快照'))
    for (const x of scenario?.data_info ?? []) items.push(inferQuality(x, '提示', '当前数据快照'))
    return items
  }, [scenario])
  const counts = {
    blocked: rows.filter(x => x.severity === '阻断').length,
    warning: rows.filter(x => x.severity === '警告').length,
    info: rows.filter(x => x.severity === '提示').length,
    simulated: rows.filter(x => /模拟|推导|临时|统一/.test(x.message)).length,
  }

  const exportCsv = () => {
    const escape = (v: string) => `"${String(v).replaceAll('"', '""')}"`
    const body = [['严重程度', '数据对象', '问题', '影响', '来源', '建议动作'], ...rows.map(x => [x.severity, x.object, x.message, x.impact, x.source, x.action])]
      .map(line => line.map(escape).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([`\uFEFF${body}`], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = '待客户补充数据清单.csv'; a.click(); URL.revokeObjectURL(url)
  }

  return (
    <div className="foundation-page" data-testid="data-quality-page">
      <div className="foundation-head"><div><h3>数据质量中心</h3><p>这里只检查当前输入数据是否可信；未排、延期和缩减属于排程结果异常，不计入本页。</p></div><button onClick={exportCsv} disabled={!rows.length}>导出待补数据</button></div>
      <div className="quality-stat-grid">
        <Stat label="阻断问题" value={counts.blocked} tone="bad" />
        <Stat label="警告" value={counts.warning} tone="warn" />
        <Stat label="提示" value={counts.info} tone="info" />
        <Stat label="涉及模拟/推导" value={counts.simulated} tone="sim" />
      </div>
      <div className="data-snapshot-strip">
        <span>产品 <b>{scenario?.products ?? '—'}</b></span><span>织机 <b>{scenario?.looms ?? '—'}</b></span>
        <span>经轴品番 <b>{scenario?.warps ?? '—'}</b></span><span>任务 <b>{scenario?.tasks ?? '—'}</b></span>
        <span>快照 <b>{result?.provenance?.data_snapshot_hash || '尚无排程'}</b></span>
      </div>
      <div className="quality-table-wrap"><table className="quality-table">
        <thead><tr><th>严重程度</th><th>对象</th><th>问题</th><th>影响</th><th>来源</th><th>建议动作</th></tr></thead>
        <tbody>{rows.map((x, i) => <tr key={`${x.source}-${i}`}>
          <td><span className={`quality-level q-${x.severity}`}>{x.severity}</span></td><td>{x.object}</td><td>{x.message}</td><td>{x.impact}</td><td>{x.source}</td><td>{x.action}</td>
        </tr>)}</tbody>
      </table></div>
      {!rows.length && <div className="empty-state">当前没有数据质量问题。</div>}
      {Number(result?.kpi?.unscheduled_quantity || 0) > 0 && <div className="quality-scope-note" data-testid="schedule-issue-note">
        当前排程另有 {Number(result?.kpi?.unscheduled_quantity).toLocaleString()} 米未排；请在“排程看板”的未排任务区查看原因，本页不重复统计。
      </div>}
    </div>
  )
}

export type ParameterValues = {
  startDate: string
  horizonDays: number | null
  mode: CompatMode
  maxTime: number
  materialOn: boolean
  beamOn: boolean
}

export function SimulationParametersPanel({ values, onChange, onRun, loading, result }: {
  values: ParameterValues
  onChange: (patch: Partial<ParameterValues>) => void
  onRun: () => void
  loading: boolean
  result: ScheduleResult | null
}) {
  const assumptions = [
    ['默认织造效率', '400 米/天', '模拟值', '待客户确认'],
    ['经轴提前到位', '120 分钟', '模拟值', '待领导确认'],
    ['单轴整经工时', '240 分钟', '模拟值', '待客户确认'],
    ['穿综穿筘工时', '480 分钟', '模拟值', '待客户确认'],
    ['整经资源', '单一计划池', '推导口径', '待现场确认'],
    ['排程边界', '7天左闭右开', '系统规则', '当前已启用'],
  ]
  return (
    <div className="foundation-page" data-testid="parameters-page">
      <div className="foundation-head"><div><h3>模拟参数与业务假设</h3><p>下次求解参数可以调整；业务假设暂只展示，在领导确认前不改变算法默认值。</p></div><button className="primary" onClick={onRun} disabled={loading}>{loading ? '正在运行…' : '按当前参数运行排程'}</button></div>
      <section className="parameter-section"><h4>下次求解参数</h4><div className="parameter-form-grid">
        <label>开始日期<input type="date" value={values.startDate} onChange={e => onChange({ startDate: e.target.value })} /></label>
        <label>计划周期<select value={values.horizonDays ?? 'full'} onChange={e => onChange({ horizonDays: e.target.value === 'full' ? null : Number(e.target.value) })}><option value={7}>7天</option><option value={14}>14天</option><option value={30}>30天</option><option value={60}>60天</option><option value="full">完整周期</option></select></label>
        <label>适配模式<select value={values.mode} onChange={e => onChange({ mode: e.target.value as CompatMode })}><option value="strict">strict</option><option value="balanced">balanced</option><option value="simulation">simulation</option></select></label>
        <label>最大求解时间<input type="number" min={1} value={values.maxTime} onChange={e => onChange({ maxTime: Number(e.target.value) })} /><small>秒</small></label>
        <label className="parameter-check"><input type="checkbox" checked={values.materialOn} onChange={e => onChange({ materialOn: e.target.checked })} />启用物料约束</label>
        <label className="parameter-check"><input type="checkbox" checked={values.beamOn} onChange={e => onChange({ beamOn: e.target.checked })} />启用经轴约束</label>
      </div></section>
      <section className="parameter-section"><h4>当前模拟假设</h4><table className="quality-table"><thead><tr><th>参数</th><th>当前值</th><th>数据类型</th><th>确认状态</th></tr></thead><tbody>
        {assumptions.map(x => <tr key={x[0]}><td><b>{x[0]}</b></td><td>{x[1]}</td><td><span className="source-tag simulated">{x[2]}</span></td><td>{x[3]}</td></tr>)}
      </tbody></table></section>
      {result?.provenance && <section className="parameter-section"><h4>当前展示结果使用的版本</h4><div className="data-snapshot-strip"><span>排程 <b>{result.schedule_id}</b></span><span>配置 <b>{result.provenance.config_version}</b></span><span>代码 <b>{result.provenance.code_version}</b></span><span>数据快照 <b>{result.provenance.data_snapshot_hash}</b></span></div></section>}
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={`quality-stat ${tone}`}><b>{value}</b><span>{label}</span></div>
}
