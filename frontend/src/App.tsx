import React, { useEffect, useMemo, useState } from 'react'
import { Gantt } from './components/Gantt'
import ProcessGantt from './components/ProcessGantt'
import WarpsPanel from './components/WarpsPanel'
import TasksPanel from './components/TasksPanel'
import LoomsPanel from './components/LoomsPanel'
import SimulationPanel from './components/SimulationPanel'
import DataImportPanel from './components/DataImportPanel'
import { DataQualityPanel, ServiceStatus, SimulationParametersPanel } from './components/FoundationPanels'
import { StatusBadges, KpiCards, UnscheduledPanel, DiagnosticsPanel, WarningsPanel, TaskDrawer } from './components/Panels'
import ProcessFlow from './components/ProcessFlow'
import { RuleAuditDrawer, buildRuleAudit } from './components/RuleAuditDrawer'
import { getScenario, solveSchedule, getLatest, getHomepageProgress, getProcessGantt, health } from './api'
import type { Assignment, ProcessGanttResult, ScenarioSummary, ScheduleResult, CompatMode } from './types'
import { executableProcessGantt, executableProcessProgress, executableScheduleKpi, executableScheduleResult, executableUnscheduledResult, scheduleViewMode } from './scheduleView'

const NAV = [
  { id: 'board', label: '排程看板' },
  { id: 'quality', label: '数据质量' },
  { id: 'data-import', label: '数据导入' },
  { id: 'parameters', label: '模拟参数' },
  { id: 'process', label: '工艺流程' },
  { id: 'tasks', label: '任务池' },
  { id: 'looms', label: '织机资源' },
  { id: 'warps', label: '经轴与整经' },
  { id: 'simulation', label: '工况模拟' },
  { id: 'materials', label: '物料风险' },
  { id: 'diagnostics', label: '求解诊断' },
]

const LOADING_MSGS = ['正在建立模型', '正在求解交期目标', '正在优化换款与机台分配', '正在生成结果']

export default function App() {
  const [page, setPage] = useState('board')
  const [scenario, setScenario] = useState<ScenarioSummary | null>(null)
  const [result, setResult] = useState<ScheduleResult | null>(null)
  const [progress, setProgress] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMsg, setLoadingMsg] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Assignment | null>(null)
  const [showAllLooms, setShowAllLooms] = useState(false)
  const [filterProduct, setFilterProduct] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [searchLoom, setSearchLoom] = useState('')
  const [horizonDays, setHorizonDays] = useState<number | null>(7)
  const [mode, setMode] = useState<CompatMode>('balanced')
  const [maxTime, setMaxTime] = useState(30)
  const [materialOn, setMaterialOn] = useState(true)
  const [beamOn, setBeamOn] = useState(true)
  const [startDate, setStartDate] = useState('2026-04-01')
  const [lastSolve, setLastSolve] = useState<string>('')
  const [ganttView, setGanttView] = useState<'process' | 'loom'>('process')
  const [processGantt, setProcessGantt] = useState<ProcessGanttResult | null>(null)
  const [serviceState, setServiceState] = useState<'checking' | 'online' | 'offline'>('checking')
  const [lastServiceSuccess, setLastServiceSuccess] = useState('')
  const [ruleAuditOpen, setRuleAuditOpen] = useState(false)

  const diagnosticMode = !materialOn || !beamOn

  const checkService = async () => {
    setServiceState('checking')
    try {
      const r = await health()
      if (r.status !== 'ok') throw new Error('health status is not ok')
      setServiceState('online')
      setLastServiceSuccess(new Date().toLocaleTimeString())
    } catch {
      setServiceState('offline')
    }
  }

  useEffect(() => {
    checkService()
    getScenario().then(setScenario).catch(() => {})
    getLatest().then(r => { setResult(r); setLastSolve(new Date().toLocaleTimeString()) }).catch(() => {})
    getHomepageProgress().then(setProgress).catch(() => {})
    getProcessGantt().then(setProcessGantt).catch(() => {})
  }, [])

  useEffect(() => {
    if (!loading) { setLoadingMsg(0); return }
    const id = setInterval(() => setLoadingMsg(m => Math.min(m + 1, LOADING_MSGS.length - 1)), 900)
    return () => clearInterval(id)
  }, [loading])

  const runSolve = async () => {
    setLoading(true); setError(null)
    try {
      const r = await solveSchedule({
        compatibility_mode: mode, max_time_s: maxTime, horizon_days: horizonDays,
        schedule_start: startDate,
        enable_material_constraint: materialOn, enable_beam_constraint: beamOn,
        freeze_days: 3, objective_mode: 'lexicographic', optimize_rules: true,
      })
      setResult(r); setLastSolve(new Date().toLocaleTimeString())
      setServiceState('online'); setLastServiceSuccess(new Date().toLocaleTimeString())
      const [ganttRefresh, progressRefresh] = await Promise.allSettled([
        getProcessGantt(), getHomepageProgress(),
      ])
      if (ganttRefresh.status === 'fulfilled') setProcessGantt(ganttRefresh.value)
      if (progressRefresh.status === 'fulfilled') setProgress(progressRefresh.value)
    } catch (e: any) {
      setError(String(e.message || e)); setResult(null)
      if (e?.kind === 'connection') setServiceState('offline')
    } finally { setLoading(false) }
  }

  const boardResult = useMemo(() => executableScheduleResult(result), [result])
  const boardKpi = useMemo(() => executableScheduleKpi(result), [result])
  const boardUnscheduledResult = useMemo(() => executableUnscheduledResult(result), [result])
  const boardProgress = useMemo(() => executableProcessProgress(progress, result), [progress, result])
  const boardProcessGantt = useMemo(() => executableProcessGantt(processGantt, result), [processGantt, result])
  const boardViewMode = scheduleViewMode(result)
  const ruleAudit = useMemo(() => result ? buildRuleAudit(result) : null, [result])
  const products = boardResult ? Array.from(new Set(boardResult.assignments.map(a => a.product_id))) : []
  const jumpMaxDelay = () => {
    if (!boardResult || !boardKpi) return
    const a = boardResult.assignments.find(x => x.task_id === boardKpi.max_delay_task_id)
    if (a) setSelected(a)
  }

  return (
    <div className="layout" data-testid="app">
      <aside className="nav">
        <div className="brand">益丰整经织造排程中心</div>
        {NAV.map(n => (
          <button key={n.id} className={'nav-item' + (page === n.id ? ' active' : '')} onClick={() => setPage(n.id)}>
            {n.label}
          </button>
        ))}
      </aside>
      <section className="main">
        <header className="toolbar">
          <span className="param-group-label">当前求解方案</span>
          <div className="solve-parameter-summary" data-testid="solve-parameter-summary">
            <span>{startDate}</span>
            <span>{horizonDays == null ? '完整周期' : `${horizonDays}天`}</span>
            <span>{mode}</span>
            <span>{maxTime}秒</span>
            <span>物料约束{materialOn ? '开启' : '关闭'}</span>
            <span>经轴约束{beamOn ? '开启' : '关闭'}</span>
          </div>
          {diagnosticMode && <span className="diagnostic-flag">诊断模式，不可发布</span>}
          <button className="secondary" onClick={() => setPage('parameters')}>调整参数</button>
          <button className="primary" onClick={runSolve} disabled={loading}>
            {loading ? LOADING_MSGS[loadingMsg] + '…' : '运行排程'}
          </button>
          <span className="muted">最近求解：{lastSolve || '—'}</span>
          <ServiceStatus state={serviceState} lastSuccess={lastServiceSuccess} onRetry={checkService} />
        </header>

        {error && <div className="error-banner" data-testid="error">{error}</div>}

        {page === 'board' && (
          <div className="content">
            {result ? (
              <>
                <div className="status-row">
                  <div><StatusBadges solver={result.status} business={result.business_status} /></div>
                  <button className="rule-audit-trigger" onClick={() => setRuleAuditOpen(true)}>
                    规则自查
                    {ruleAudit && <span>{ruleAudit.counts['不符合']}项未达到</span>}
                  </button>
                </div>
                {result.rule_optimization?.enabled && (
                  <div className="rule-optimization-note" data-testid="rule-optimization-note">
                    规则优化已执行：产量、换款与时间紧凑度已参与求解，整经按已选织造量反推，并已生成匹级落布计划。
                  </div>
                )}
                {result.status === 'OPTIMAL' && (
                  <div className="optimal-note">OPTIMAL 仅表示数学模型在当前数据与规则下求解完成，不代表业务方案可直接执行。</div>
                )}
                {result.business_status === 'HIGH_RISK' && boardKpi && (
                  <div className="risk-banner">当前有 {pct(1 - boardKpi.demand_coverage_rate)} 的需求尚未进入最终可执行计划，不建议发布。</div>
                )}
                {boardKpi && <KpiCards kpi={boardKpi} onMaxDelay={jumpMaxDelay}
                  scope={boardViewMode === 'initial' ? 'solver' : 'executable'} />}
                <ProcessBar progress={boardProgress} onStage={p => setPage('process')} />
                <ExecutionPreviewBanner preview={result.execution_preview} onOpen={() => setPage('simulation')} />
                <ResultParams params={result.provenance} diffFields={paramMismatch(result.provenance, { maxTime, horizonDays, mode, materialOn, beamOn, startDate })} />
                <div className="toolbar-inline">
                  <div className="view-toggle">
                    <button className={ganttView === 'process' ? 'active' : ''} onClick={() => setGanttView('process')}>按工艺流程</button>
                    <button className={ganttView === 'loom' ? 'active' : ''} onClick={() => setGanttView('loom')}>按织机</button>
                  </div>
                  <span className={`schedule-view-badge ${boardViewMode}`} data-testid="schedule-view-badge">
                    {boardViewMode === 'executable' ? '展示口径：逐轴校验后的最终可执行计划'
                      : boardViewMode === 'invalid' ? '执行校验未通过：不展示未经验证的织造计划'
                        : '展示口径：算法初排（尚未执行逐轴校验）'}
                  </span>
                  <label>机号 <input value={searchLoom} onChange={e => setSearchLoom(e.target.value)} /></label>
                  <label>产品 <select value={filterProduct} onChange={e => setFilterProduct(e.target.value)}>
                    <option value="">全部</option>{products.map(p => <option key={p} value={p}>{p}</option>)}
                  </select></label>
                  <label>状态 <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                    <option value="">全部</option><option value="late">逾期</option>
                    <option value="on_time">按时</option><option value="locked">锁定</option>
                  </select></label>
                  <label className="toggle"><input type="checkbox" checked={showAllLooms} onChange={e => setShowAllLooms(e.target.checked)} /> 显示全部织机</label>
                </div>
                {ganttView === 'process' ? (
                  boardProcessGantt ? <ProcessGantt data={boardProcessGantt} scheduleStart={result.schedule_start} horizonDays={result.kpi.horizon_days || 7} />
                    : <div className="empty-state">暂无工艺流程数据。</div>
                ) : (
                  <Gantt result={boardResult || result} showAllLooms={showAllLooms} filterProduct={filterProduct}
                    filterStatus={filterStatus} searchLoom={searchLoom} onSelect={setSelected} />
                )}
                <UnscheduledPanel result={boardUnscheduledResult || result} onSelectReason={(code) => { setFilterStatus(''); setFilterProduct(''); }} />
              </>
            ) : (
              <div className="empty-state" data-testid="empty">
                {loading ? LOADING_MSGS[loadingMsg] + '…' : '暂无排程结果，请点击“运行排程”。'}
              </div>
            )}
          </div>
        )}

        {page === 'diagnostics' && (
          <div className="content">
            {result ? <DiagnosticsPanel result={result} /> : <div className="empty-state">请先运行排程以查看诊断。</div>}
          </div>
        )}

        {page === 'quality' && (
          <div className="content"><DataQualityPanel scenario={scenario} result={result} /></div>
        )}

        {page === 'data-import' && (
          <div className="content"><DataImportPanel /></div>
        )}

        {page === 'parameters' && (
          <div className="content"><SimulationParametersPanel
            values={{ startDate, horizonDays, mode, maxTime, materialOn, beamOn }}
            onChange={patch => {
              if (patch.startDate !== undefined) setStartDate(patch.startDate)
              if (patch.horizonDays !== undefined) setHorizonDays(patch.horizonDays)
              if (patch.mode !== undefined) setMode(patch.mode)
              if (patch.maxTime !== undefined) setMaxTime(patch.maxTime)
              if (patch.materialOn !== undefined) setMaterialOn(patch.materialOn)
              if (patch.beamOn !== undefined) setBeamOn(patch.beamOn)
            }}
            onRun={runSolve} loading={loading} result={result}
          /></div>
        )}

        {page === 'process' && <ProcessFlow />}

        {page === 'warps' && (
          <div className="content"><WarpsPanel executionPreview={result?.execution_preview} onOpenSimulation={() => setPage('simulation')} /></div>
        )}

        {page === 'simulation' && (
          <div className="content"><SimulationPanel scheduleId={result?.schedule_id} initialData={result?.execution_preview} /></div>
        )}

        {page === 'tasks' && (
          <div className="content"><TasksPanel /></div>
        )}

        {page === 'looms' && (
          <div className="content"><LoomsPanel /></div>
        )}

        {page === 'materials' && (
          <div className="content placeholder">
            <div className="placeholder-head">
              <h4>{NAV.find(n => n.id === page)?.label}</h4>
              <span className="placeholder-tag">本页为阶段3数据概览</span>
            </div>
            <p className="muted">管理功能后续阶段开放（本阶段仅展示汇总数据）。</p>
            <table className="summary-table">
              <tbody>
                <tr><td>产品数量</td><td>{scenario?.products ?? '—'}</td></tr>
                <tr><td>织机总数</td><td>{scenario?.looms ?? '—'}</td></tr>
                <tr><td>可用织机</td><td>{scenario?.available_looms ?? '—'}</td></tr>
                <tr><td>物料种类</td><td>{scenario?.materials ?? '—'}</td></tr>
                <tr><td>生产任务</td><td>{scenario?.tasks ?? '—'}</td></tr>
              </tbody>
            </table>
            <p className="muted">新增 / 编辑 / 删除等操作：后续阶段开放。</p>
          </div>
        )}

        {page !== 'quality' && <WarningsPanel scenario={scenario} onOpenQuality={() => setPage('quality')} />}
      </section>
      <TaskDrawer assignment={selected} result={result!} onClose={() => setSelected(null)} />
      <RuleAuditDrawer audit={ruleAudit} open={ruleAuditOpen} onClose={() => setRuleAuditOpen(false)} />
    </div>
  )
}

function pct(v: any): string { return v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%` }

function normDate(s: any): string { return String(s || '').slice(0, 10) }

export function paramMismatch(p: any, form: any): string[] {
  if (!p) return []
  const diffs: string[] = []
  if (Number(p.total_time_limit_s) !== Number(form.maxTime)) diffs.push('最大求解时间')
  const pHz = p.horizon_days == null ? '完整' : Number(p.horizon_days)
  const fHz = form.horizonDays == null ? '完整' : Number(form.horizonDays)
  if (pHz !== fHz) diffs.push('排程周期')
  if (String(p.compatibility_mode) !== String(form.mode)) diffs.push('适配模式')
  if (Boolean(p.material_enabled) !== Boolean(form.materialOn)) diffs.push('物料约束')
  if (Boolean(p.beam_enabled) !== Boolean(form.beamOn)) diffs.push('经轴约束')
  if (normDate(p.schedule_start) !== normDate(form.startDate)) diffs.push('开始日期')
  return diffs
}

function ResultParams({ params, diffFields }: { params: any; diffFields: string[] }) {
  if (!params) return null
  const rows: [string, any][] = [
    ['求解编号', params.schedule_id], ['场景编号', params.scenario_id],
    ['数据快照编号', params.data_snapshot_hash], ['开始日期', params.schedule_start],
    ['结束日期', params.schedule_end], ['周期天数', params.horizon_days + ' 天'],
    ['适配模式', params.compatibility_mode], ['物料约束', params.material_enabled ? '开启' : '关闭'],
    ['经轴约束', params.beam_enabled ? '开启' : '关闭'], ['目标层数', params.objective_layers],
    ['总时间限制', params.total_time_limit_s + ' 秒'],
    ['每层时间限制', params.per_layer_time_limit_s + ' 秒'],
    ['任务数', params.task_count], ['需求总量', fmtNum(params.required_quantity) + ' 米'],
    ['配置版本', params.config_version], ['代码版本', params.code_version],
  ]
  return (
    <div className="params-panel" data-testid="result-params">
      <div className="params-head"><h4>本次求解参数</h4>
        {diffFields.length > 0 && <span className="param-mismatch">当前表单参数与展示结果不同（{diffFields.join('、')}）</span>}</div>
      <div className="params-grid">{rows.map(([k, v]) => (
        <div className="param-cell" key={k}><span>{k}</span><b>{v ?? '—'}</b></div>
      ))}</div>
    </div>
  )
}

function fmtNum(v: any): string { return v == null ? '—' : Number(v).toLocaleString() }

const PROGRESS_STAGES: { key: string; label: string }[] = [
  { key: 'required_qty', label: '需求总量' }, { key: 'material_ready_qty', label: '原料已满足' },
  { key: 'beam_ready_qty', label: '经轴已准备' }, { key: 'weave_scheduled_qty', label: '织造已排' },
  { key: 'weave_done_qty', label: '织造已完成' }, { key: 'finishing_qty', label: '后整待处理' },
  { key: 'stocked_qty', label: '已入库' },
]

function ProcessBar({ progress, onStage }: { progress: any; onStage: (p: string) => void }) {
  if (!progress) return null
  return (
    <div className="process-bar" data-testid="process-bar">
      {PROGRESS_STAGES.map(s => (
        <button key={s.key} className="proc-stage" onClick={() => onStage(s.key)} title="点击进入工艺流程">
          <span className="ps-label">{s.label}</span>
          <span className="ps-qty">{fmtNum(progress[s.key])} 米</span>
        </button>
      ))}
      <span className="muted">{progress.note}</span>
    </div>
  )
}

function ExecutionPreviewBanner({ preview, onOpen }: { preview: any; onOpen: () => void }) {
  if (!preview) return null
  const kpi = preview.kpi || {}
  const trace = preview.planning_trace || {}
  const decisionCount = Array.isArray(trace.decisions) ? trace.decisions.length : 0
  const boundCount = Array.isArray(preview.weaving_plan) ? preview.weaving_plan.filter((x: any) => x.beam_id).length : 0
  const ok = preview.validation?.ok === true
  return (
    <div className={'execution-preview-banner ' + (ok ? 'ok' : 'warning')} data-testid="execution-preview-summary">
      <div>
        <strong>整经—织造联动校验已执行</strong>
        <span>
          算法初排 {fmtNum(kpi.solver_scheduled_quantity)} 米 → 校验缩减 {fmtNum(kpi.reduced_quantity || 0)} 米 → 最终可执行 {fmtNum(kpi.simulated_quantity)} 米；
          {boundCount} 段织造已绑定具体经轴，共形成 {decisionCount} 条订单决策记录。
        </span>
        <small>{ok ? '已验证经轴数量、提前两小时到位和七天边界。' : '仍有硬约束未通过，请查看逐轴决策。'}</small>
      </div>
      <button onClick={onOpen}>查看逐轴决策</button>
    </div>
  )
}
