import React, { useMemo } from 'react'
import type { Assignment, ScheduleResult } from '../types'

const PALETTE = ['#4f81bd', '#9bbb59', '#c0504d', '#8064a2', '#f79646', '#1f77b4', '#2ca02c', '#d62728', '#9467bd']

function colorFor(product: string): string {
  let h = 0
  for (const c of product) h = (h * 31 + c.charCodeAt(0)) % 997
  return PALETTE[h % PALETTE.length]
}

export function parseMinute(startIso: string, minute: number): Date {
  const base = new Date(startIso.slice(0, 10) + 'T00:00:00')
  return new Date(base.getTime() + minute * 60000)
}

interface Props {
  result: ScheduleResult
  showAllLooms: boolean
  filterProduct: string
  filterStatus: string
  searchLoom: string
  onSelect: (a: Assignment) => void
  dayWidth?: number
}

export function Gantt({ result, showAllLooms, filterProduct, filterStatus, searchLoom, onSelect, dayWidth = 96 }: Props) {
  const usedLooms = useMemo(() => Array.from(new Set(result.assignments.map(a => a.loom_id))), [result])
  // 默认只显示有排程任务的织机；显示全部时用候选织机(来自 diagnostics 可用/候选)
  const allLoomIds = useMemo(() => {
    if (showAllLooms) {
      const cand = result.diagnostics?.candidate_loom_count || 0
      const pool = new Set(usedLooms)
      // 补充候选(用 # 号示例，仅用于占位提示；实际织机名为 candidate_loom_ids)
      return pool.size > 0 ? Array.from(pool) : [`#1 至 ${cand} 台可选`]
    }
    return usedLooms
  }, [result, showAllLooms, usedLooms])

  const days = Math.max(1, result.kpi.horizon_days || 7)
  const width = days * dayWidth
  const startDate = parseMinute(result.schedule_start, 0)

  const shown = allLoomIds
    .filter(l => !searchLoom || l.toLowerCase().includes(searchLoom.toLowerCase()))
  const visibleAssignments = result.assignments
    .filter(a => !filterProduct || a.product_id === filterProduct)
    .filter(a => filterStatus !== 'late' || a.lateness_minutes > 0)
    .filter(a => filterStatus !== 'on_time' || a.lateness_minutes === 0)
    .filter(a => filterStatus !== 'locked' || a.locked)

  const loomToAssignments = (loom: string) => visibleAssignments.filter(a => a.loom_id === loom)

  return (
    <div className="gantt-wrap" data-testid="gantt">
      <div className="gantt-unit">时间单位：天（共 {days} 天）</div>
      <div className="gantt-header-row" style={{ width: 140 + width }}>
        <div className="gantt-corner">织机</div>
        <div className="gantt-timeline">
          {Array.from({ length: days }, (_, i) => (
            <div key={i} className="gantt-day" style={{ width: dayWidth }} data-testid="gantt-day">
              {formatDay(startDate, i)}
            </div>
          ))}
        </div>
      </div>
      <div className="gantt-scroll">
        <div style={{ width: 140 + width, minWidth: 600 }}>
          {shown.map(loom => {
            const assigns = loomToAssignments(loom)
            return (
              <div key={loom} className="gantt-row" style={{ width: 140 + width }} data-testid={`row-${loom}`}>
                <div className="gantt-row-label">{loom}</div>
                <div className="gantt-lane" style={{ width }}>
                  {assigns.map((a, idx) => {
                    const x = (a.start_minute / 1440) * dayWidth
                    const w = Math.max(5, ((a.end_minute - a.start_minute) / 1440) * dayWidth)
                    const late = a.lateness_minutes > 0
                    return (
                      <div key={idx}
                        className={'gantt-bar' + (late ? ' late' : '') + (a.locked ? ' locked' : '') + (a.beam_id?.startsWith('WB') ? ' virtual' : '')}
                        style={{ left: x, width: w, background: colorFor(a.product_id) }}
                        onClick={() => onSelect(a)}
                        title={`${a.product_id} ${a.task_id} 量=${a.scheduled_quantity}`}>
                        <span className="gantt-bar-text">{a.product_id}</span>
                        <span className="gantt-bar-qty">{a.scheduled_quantity}</span>
                        <span className="gantt-bar-meta">{a.task_id}{a.beam_id ? ` / ${a.beam_id}` : ''}</span>
                        {a.locked && <span className="gantt-lock">🔒</span>}
                        {a.beam_id?.startsWith('WB') && <span className="gantt-risk">虚拟轴</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
          {shown.length === 0 && <div className="gantt-empty">当前筛选下无排程任务织机</div>}
        </div>
      </div>
    </div>
  )
}

function formatDay(start: Date, i: number): string {
  const d = new Date(start.getTime() + i * 86400000)
  return `${d.getMonth() + 1}/${d.getDate()}`
}
