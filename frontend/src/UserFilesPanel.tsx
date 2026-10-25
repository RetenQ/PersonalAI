import { useEffect, useState } from 'react';
import { api } from './api';

export interface UserFilesStatus {
  directory: string; entry: string; healthy: boolean; sequence: number | null;
  source_sequence: number; error: string; preserved_count: number;
}

export function UserFilesWarning({ status }: { status?: UserFilesStatus }) {
  return status && !status.healthy ? <p className="alert error" role="alert">{status.error} 原始记录以保存结果为准，可前往设置重新整理可读资料。</p> : null;
}

export function UserFilesPanel({ revision = 0 }: { revision?: number }) {
  const [status, setStatus] = useState<UserFilesStatus>();
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => { let active = true; const controller = new AbortController(); api<UserFilesStatus>('/api/user-files', { signal: controller.signal }).then(r => { if (active) { setStatus(r); setError(''); } }).catch(e => { if (active) setError(e.message); }); return () => { active = false; controller.abort(); }; }, [revision]);
  return <section className="panel module" aria-label="用户资料文件">
    <h2>用户资料文件</h2>
    <p className="module-description">网页维护，Markdown 自动整理。档案、目标、任务、状态、日志和待确认内容分别存放，每份资料保留来源与修订链接。</p>
    {error && <p className="alert error" role="alert">{error}</p>}
    <UserFilesWarning status={status}/>
    {status && <>
      <p>阅读入口：<span className="path-text">{status.entry}</span></p>
      <p className="module-description">可在文件管理器中打开；此目录不通过网页静态地址开放。</p>
      <p role="status">{status.healthy ? `已整理至事件版本 ${status.sequence}` : '资料整理尚未完成'}</p>
      {status.preserved_count > 0 && <p className="modal-hint">发现过 {status.preserved_count} 份被改动或未完成整理的文件，已先保留到数据目录下的 user-edits/。这些副本没有自动导入或纳入应用备份。</p>}
    </>}
    <p className="modal-hint">请在网页修改资料。重新整理不改变正式记录；应用备份同时包含修订历史与可读文件，不包含密钥和旧访谈档案。</p>
    <button className="secondary" disabled={busy} onClick={async () => {
      setBusy(true); setError('');
      try { setStatus(await api<UserFilesStatus>('/api/user-files/rebuild', { method: 'POST' })); }
      catch (e) { setError((e as Error).message); }
      finally { setBusy(false); }
    }}>{busy ? '正在整理…' : '重新整理资料'}</button>
  </section>;
}
