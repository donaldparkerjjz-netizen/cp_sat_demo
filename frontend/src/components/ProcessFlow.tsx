import React, { useEffect, useMemo, useState } from 'react'
import { getProcessOverview, getProcessTasks, getProcessCases } from '../api'

const STATUS_CLASS: Record<string, string> = {
  '未开始': 'g', '等待条件': 'g', '可以开始': 'g', '进行中': 'b',
  '已排程': 'b', '部分已排': 'b', '已完成': 'ok', '已跳过': 'g', '异常阻塞': 'orange',
}

const PRIMARY_PROCESSES = [
  { process: '整经生产', label: '整经' },
  { process: '织造生产', label: '织造' },
  { process: '水洗', label: '水洗' },
]

const DETAIL_GROUPS = [
  { title: '生产准备', processes: ['客户需求', '生产需求确认', '原料库存检查', '缺料处理'] },
  { title: '整经与经轴', processes: ['整经计划', '整经生产', '经轴准备', '上轴', '穿综穿筘'] },
  { title: '织造', processes: ['织造生产', '落布'] },
  { title: '水洗与后整', processes: ['水洗', '涂层', '验布', '成品入库', '订单完成'] },
]

function PhaseCard({ c, onSelect, title, primary = false }: {
  c: any; onSelect: (p: string) => void; title?: string; primary?: boolean
}) {
  return (
    <button
      className={'phase-card' + (c.is_finishing ? ' finishing' : '') + (primary ? ' primary-stage' : '')}
      data-testid={primary ? `primary-stage-${title}` : undefined}
      onClick={() => onSelect(c.process)}
    >
      <div className="phase-title">{title || `${c.order}. ${c.process}`}</div>
      <div className="phase-nums">
        <span>待处理 {c.pending_count}</span><span>进行中 {c.in_progress_count}</span>
        <span>已完成 {c.completed_count}</span><span className="anom">异常 {c.anomaly_count}</span>
      </div>
      <div className="phase-qty">涉及 {c.quantity} 米</div>
      <div className="phase-risk">{c.main_risk || '无主要风险'}</div>
      {c.is_finishing && <div className="phase-tag">后续阶段接入正式排程</div>}
    </button>
  )
}

export default function ProcessFlow() {
  const [overview, setOverview] = useState<any>(null)
  const [tasks, setTasks] = useState<any[]>([])
  const [cases, setCases] = useState<any[]>([])
  const [selectedTask, setSelectedTask] = useState<any>(null)
  const [detailProc, setDetailProc] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getProcessOverview(), getProcessTasks(), getProcessCases()])
      .then(([o, t, c]) => { setOverview(o); setTasks(t.tasks || []); setCases(c.cases || []) })
      .catch(e => setError(String(e.message || e)))
  }, [])

  const procDetail = useMemo(() => (overview?.flow || []).find((f: any) => f.process === detailProc) || null, [overview, detailProc])

  if (error) return <div className="content"><div className="error-banner">{error}</div></div>
  if (!overview) return <div className="content"><div className="empty-state">正在加载工艺流程数据…</div></div>

  return (
    <div className="content process-page" data-testid="process-page">
      <h4>工艺流程</h4>
      {/* 第一部分：全流程图 */}
      <div className="branch-notes">
        {overview.branch_notes.map((n: string, i: number) => <span key={i} className="branch-note">{n}</span>)}
      </div>

      <section className="primary-processes" data-testid="primary-processes">
        <h5>主要生产流程</h5>
        <div className="primary-flow">
          {PRIMARY_PROCESSES.map((item, index) => {
            const c = overview.flow.find((f: any) => f.process === item.process)
            if (!c) return null
            return (
              <React.Fragment key={item.process}>
                <PhaseCard c={c} title={item.label} primary onSelect={setDetailProc} />
                {index < PRIMARY_PROCESSES.length - 1 && <span className="primary-arrow">➜</span>}
              </React.Fragment>
            )
          })}
        </div>
      </section>

      <section className="detailed-processes">
        <h5>详细工序</h5>
        <div className="process-groups">
          {DETAIL_GROUPS.map(group => {
            const cards = group.processes
              .map(process => overview.flow.find((f: any) => f.process === process))
              .filter(Boolean)
            return (
              <div className="process-section" key={group.title}>
                <div className="process-section-title">{group.title}</div>
                <div className="process-stage-grid">
                  {cards.map((c: any) => <PhaseCard key={c.process} c={c} onSelect={setDetailProc} />)}
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* 第三部分：工序详情 */}
      {procDetail && (
        <div className="proc-detail">
          <h5>{procDetail.process} 详情</h5>
          <div className="kv"><span>状态</span><b>待处理 {procDetail.pending_count}，进行中 {procDetail.in_progress_count}，已完成 {procDetail.completed_count}，异常 {procDetail.anomaly_count}</b></div>
          <div className="kv"><span>前置工序</span><b>{procDetail.pred.join('，') || '—'}</b></div>
          <div className="kv"><span>后续工序</span><b>{procDetail.succ.join('，') || '—'}</b></div>
          <div className="kv"><span>是否后整</span><b>{procDetail.is_finishing ? '是（模拟，后续阶段接入正式排程）' : '否'}</b></div>
        </div>
      )}

      {/* 第二部分：订单/产品流程跟踪 + 案例 */}
      <div className="proc-tracking">
        <h5>演示案例（点击查看该任务当前工序）</h5>
        <div className="case-list">
          {cases.map(c => <button key={c.label} className={'case-item' + (c.found ? '' : ' empty')}
            onClick={() => { const t = tasks.find(x => x.task_id === c.task_id); if (t) setSelectedTask(t) }}>
            <span>{c.label}</span><span className="muted">{c.found ? `${c.product_id}：${c.current_process}` : '暂无匹配任务'}</span>
          </button>)}
        </div>
        <div className="task-track-list">
          {tasks.filter(t => t.unscheduled_quantity > 0 || t.scheduled_quantity > 0).slice(0, 60).map(t => (
            <button key={t.task_id} className={'task-track ' + (selectedTask?.task_id === t.task_id ? 'selected' : '')}
              onClick={() => setSelectedTask(t)}>
              <span className="tt-task">{t.task_id}（{t.product_id}）</span>
              <span className="tt-proc">当前：{t.current_process}</span>
              <span className={'tt-status ' + (STATUS_CLASS[t.current_status] || 'g')}>{t.current_status}</span>
              <span className="muted">{t.blocked_reason ? `阻塞：${t.blocked_reason}` : ''}</span>
              {t.current_process && t.current_process.includes('水洗') === false && t.un_scheduled ? '' : ''}
            </button>
          ))}
        </div>
      </div>

      {/* 任务详情 */}
      {selectedTask && (
        <div className="proc-detail task-detail">
          <h5>任务流程详情</h5>
          <div className="kv"><span>任务/订单</span><b>{selectedTask.task_id} / {selectedTask.order_id}</b></div>
          <div className="kv"><span>产品编号</span><b>{selectedTask.product_id}</b></div>
          <div className="kv"><span>计划数量</span><b>{selectedTask.required_quantity} 米</b></div>
          <div className="kv"><span>已完成数量</span><b>{selectedTask.scheduled_quantity} 米</b></div>
          <div className="kv"><span>当前工序</span><b>{selectedTask.current_process}（{selectedTask.current_status}）</b></div>
          <div className="kv"><span>已完成工序</span><b>{selectedTask.completed_processes.join('，') || '—'}</b></div>
          <div className="kv"><span>下一工序</span><b>{selectedTask.next_process || '—'}</b></div>
          <div className="kv"><span>阻塞原因</span><b>{selectedTask.blocked_reason || '—'}</b></div>
          <div className="kv"><span>数据来源</span><b>{selectedTask.data_source}</b></div>
          <div className="kv"><span>临时参数</span><b>{selectedTask.use_temp_params ? '是' : '否'}</b></div>
        </div>
      )}
    </div>
  )
}
