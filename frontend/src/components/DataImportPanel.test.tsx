import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import DataImportPanel from './DataImportPanel'
import { getDataSnapshots, previewDataImport, saveDataSnapshot } from '../api'

vi.mock('../api', () => ({
  getDataSnapshots: vi.fn(),
  previewDataImport: vi.fn(),
  saveDataSnapshot: vi.fn(),
}))

const preview = {
  preview_id: 'preview-1', filename: '客户数据.xlsx', sha256: '1234567890abcdef1234',
  status: 'READY', can_save: true, sheet_count: 10, error_count: 0, warning_count: 1,
  sheets: [{ name: '①基础资料', rows: 20, columns: 8, required: true }],
  issues: [{ severity: 'WARNING', code: 'TEMP_DATA', object: '基础资料', message: '存在模拟字段', action: '导入真实数据后复核' }],
  comparison: [{ key: 'products', label: '产品', incoming: 19, current: 18, delta: 1 }],
  note: '预检查不会切换当前排程数据源。',
}

describe('DataImportPanel', () => {
  beforeEach(() => {
    vi.mocked(getDataSnapshots).mockResolvedValue({ snapshots: [], count: 0, note: '候选快照尚未启用。' } as any)
    vi.mocked(previewDataImport).mockResolvedValue(preview as any)
    vi.mocked(saveDataSnapshot).mockResolvedValue({ snapshot_id: 'snapshot-1', status: 'SAVED_NOT_ACTIVE' } as any)
  })

  it('预检查成功后允许保存候选快照且不启用', async () => {
    render(<DataImportPanel />)
    await screen.findByTestId('snapshot-history')
    const file = new File(['xlsx'], '客户数据.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    fireEvent.change(screen.getByLabelText('选择Excel文件'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: '开始预检查' }))

    await screen.findByText('预检查完成，可以保存候选快照')
    expect(previewDataImport).toHaveBeenCalledWith(expect.objectContaining({ filename: '客户数据.xlsx' }))
    expect(screen.getByTestId('import-preview')).toHaveTextContent('0 个阻断')

    fireEvent.change(screen.getByPlaceholderText('例如：客户9月3日反馈版本'), { target: { value: '首份客户数据' } })
    fireEvent.click(screen.getByRole('button', { name: '保存为候选数据快照' }))
    await waitFor(() => expect(saveDataSnapshot).toHaveBeenCalledWith({ preview_id: 'preview-1', note: '首份客户数据' }))
    expect(await screen.findByTestId('import-success')).toHaveTextContent('当前排程数据源未切换')
  })
})
