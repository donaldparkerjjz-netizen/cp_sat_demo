import { describe, expect, it } from 'vitest'
import { dailySlices } from './ProcessGantt'
import type { ProcessBar } from '../types'

const crossDayBar = {
  bar_id: 'WEAVE-1',
  process: '织造',
  label: '#502',
  start: '2026-04-01T19:40:00',
  end: '2026-04-03T09:30:00',
  derived: true,
  data_source: '最终可执行计划',
} as ProcessBar

describe('工艺甘特图跨天切片', () => {
  it('在每个占用日显示开始、续产和结束片段', () => {
    expect(dailySlices([crossDayBar], '2026-04-01')[0]).toMatchObject({
      displayStart: '19:40', displayEnd: '24:00', continuesBefore: false, continuesAfter: true,
    })
    expect(dailySlices([crossDayBar], '2026-04-02')[0]).toMatchObject({
      displayStart: '00:00', displayEnd: '24:00', continuesBefore: true, continuesAfter: true,
    })
    expect(dailySlices([crossDayBar], '2026-04-03')[0]).toMatchObject({
      displayStart: '00:00', displayEnd: '09:30', continuesBefore: true, continuesAfter: false,
    })
    expect(dailySlices([crossDayBar], '2026-04-04')).toEqual([])
  })

  it('在当天24点结束时显示24:00，不误放到次日', () => {
    const boundaryBar = { ...crossDayBar, end: '2026-04-03T00:00:00' }
    expect(dailySlices([boundaryBar], '2026-04-02')[0]).toMatchObject({
      displayEnd: '24:00', continuesAfter: false,
    })
    expect(dailySlices([boundaryBar], '2026-04-03')).toEqual([])
  })
})
