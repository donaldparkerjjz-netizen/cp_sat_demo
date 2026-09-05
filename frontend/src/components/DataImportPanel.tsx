import React, { useEffect, useState } from 'react'
import { getDataSnapshots, previewDataImport, saveDataSnapshot } from '../api'

export default function DataImportPanel() {
  const [selected, setSelected] = useState<File | null>(null)
  const [preview, setPreview] = useState<any>(null)
  const [history, setHistory] = useState<any>({ snapshots: [], count: 0 })
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')

  const loadHistory = () => getDataSnapshots().then(setHistory).catch(e => setError(String(e?.message || e)))
  useEffect(() => { loadHistory() }, [])

  const runPreview = async () => {
    if (!selected) return
    setLoading(true); setError(''); setSaved(''); setPreview(null)
    try {
      const content_base64 = await fileToBase64(selected)
      setPreview(await previewDataImport({ filename: selected.name, content_base64 }))
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally { setLoading(false) }
  }

  const save = async () => {
    if (!preview?.can_save) return
    setSaving(true); setError('')
    try {
      const result = await saveDataSnapshot({ preview_id: preview.preview_id, note })
      setSaved(`已保存候选数据快照 ${result.snapshot_id}；当前排程数据源未切换。`)
      await loadHistory()
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally { setSaving(false) }
  }

  return <div className="foundation-page" data-testid="data-import-page">
    <div className="foundation-head"><div><h3>Excel导入预检查与数据快照</h3><p>先检查再保存；本阶段保存的是候选快照，不会改变当前排程数据源。</p></div></div>
    <section className="import-card">
      <div className="import-controls">
        <label className="file-picker">选择Excel文件<input aria-label="选择Excel文件" type="file" accept=".xlsx,.xlsm" onChange={e => { setSelected(e.target.files?.[0] || null); setPreview(null); setSaved('') }} /></label>
        <span>{selected ? `${selected.name} · ${formatBytes(selected.size)}` : '尚未选择文件'}</span>
        <button className="primary" onClick={runPreview} disabled={!selected || loading}>{loading ? '正在检查…' : '开始预检查'}</button>
      </div>
      <p className="muted">检查工作表、业务解析、基础数据数量和数据质量；单个文件最大25MB。</p>
    </section>
    {error && <div className="error-banner" data-testid="import-error">{error}</div>}
    {saved && <div className="import-success" data-testid="import-success">{saved}</div>}

    {preview && <>
      <section className={`import-result ${preview.can_save ? 'ready' : 'blocked'}`} data-testid="import-preview">
        <div><b>{preview.can_save ? '预检查完成，可以保存候选快照' : '预检查存在阻断问题'}</b><span>{preview.filename}</span><small>SHA-256 {preview.sha256.slice(0, 16)}…</small></div>
        <div className="import-result-counts"><span>{preview.sheet_count} 张表</span><span>{preview.error_count} 个阻断</span><span>{preview.warning_count} 个警告</span></div>
      </section>
      <section className="parameter-section"><h4>与当前数据对比</h4><div className="comparison-grid">
        {(preview.comparison ?? []).map((x: any) => <div key={x.key}><span>{x.label}</span><b>{x.incoming}</b><small>当前 {x.current}，变化 {x.delta > 0 ? '+' : ''}{x.delta}</small></div>)}
      </div></section>
      <section className="parameter-section"><h4>工作表检查</h4><div className="quality-table-wrap"><table className="quality-table"><thead><tr><th>工作表</th><th>行数</th><th>列数</th><th>用途</th></tr></thead><tbody>
        {(preview.sheets ?? []).map((x: any) => <tr key={x.name}><td><b>{x.name}</b></td><td>{x.rows}</td><td>{x.columns}</td><td>{x.required ? '排程必要表' : '辅助表'}</td></tr>)}
      </tbody></table></div></section>
      <section className="parameter-section"><h4>预检查问题</h4>
        {(preview.issues ?? []).length ? <div className="quality-table-wrap"><table className="quality-table"><thead><tr><th>级别</th><th>对象</th><th>问题</th><th>建议动作</th></tr></thead><tbody>
          {preview.issues.map((x: any, i: number) => <tr key={`${x.code}-${i}`}><td><span className={`quality-level q-${x.severity === 'ERROR' ? '阻断' : x.severity === 'WARNING' ? '警告' : '提示'}`}>{x.severity === 'ERROR' ? '阻断' : x.severity === 'WARNING' ? '警告' : '提示'}</span></td><td>{x.object}</td><td>{x.message}</td><td>{x.action}</td></tr>)}
        </tbody></table></div> : <p className="muted">未发现数据质量问题。</p>}
      </section>
      <section className="snapshot-save"><label>快照备注<input value={note} onChange={e => setNote(e.target.value)} placeholder="例如：客户9月3日反馈版本" /></label><button onClick={save} disabled={!preview.can_save || saving}>{saving ? '正在保存…' : '保存为候选数据快照'}</button><small>{preview.note}</small></section>
    </>}

    <section className="parameter-section" data-testid="snapshot-history"><h4>候选数据快照历史（{history.count ?? 0}）</h4><p className="muted">{history.note}</p>
      {(history.snapshots ?? []).length ? <table className="quality-table"><thead><tr><th>快照编号</th><th>文件</th><th>保存时间</th><th>数据量</th><th>状态</th><th>备注</th></tr></thead><tbody>
        {history.snapshots.map((x: any) => <tr key={x.snapshot_id}><td><b>{x.snapshot_id}</b></td><td>{x.filename}</td><td>{x.created_at}</td><td>{x.metrics.products}产品 / {x.metrics.looms}织机 / {x.metrics.tasks}任务</td><td>已保存，未启用</td><td>{x.note || '—'}</td></tr>)}
      </tbody></table> : <div className="empty-state">尚未保存候选数据快照。</div>}
    </section>
  </div>
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '')
    reader.onerror = () => reject(new Error('无法读取所选文件，请重新选择。'))
    reader.readAsDataURL(file)
  })
}

function formatBytes(size: number): string {
  return size >= 1024 * 1024 ? `${(size / 1024 / 1024).toFixed(1)}MB` : `${Math.ceil(size / 1024)}KB`
}
