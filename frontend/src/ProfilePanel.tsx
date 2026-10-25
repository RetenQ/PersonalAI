import { useEffect, useState } from 'react';
import { api, mutate } from './api';
import type { Change, Entity } from './trackingTypes';
import { ChangeReview, Dialog } from './trackingUI';

interface Profile { personality: string; values: string; preferences: string; boundaries: string }
interface Result { profile: Profile; version: number }
const fields = [['personality', '个性与自我描述'], ['values', '重视的事情'], ['preferences', '协作与生活偏好'], ['boundaries', '个人边界']] as const;

export function ProfilePanel({ changed = () => {} }: { changed?: () => void }) {
  const [original, setOriginal] = useState<Result>();
  const [profile, setProfile] = useState<Profile>();
  const [change, setChange] = useState<Entity<Change>>();
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  async function load() {
    const result = await api<Result>('/api/profile');
    setOriginal(result); setProfile(result.profile);
  }
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel module" aria-label="个性与协作偏好">
    <h2>个性与协作偏好</h2>
    <p className="module-description">只记录你明确填写的自我描述，不自动推断个性，也不自动导入旧访谈。首次保存和后续修改均先展示差异，由你确认。</p>
    {error && <p className="alert error" role="alert">{error}</p>}
    {notice && <p className="alert success" role="status">{notice}</p>}
    {profile && original ? <form onSubmit={e => { e.preventDefault(); run(async () => {
      const result = await mutate<{ change: Entity<Change> }>('/api/profile', { data: profile, expected_version: original.version, reason: '用户更新个性与协作偏好' });
      setChange(result.change);
      changed();
    }); }}>
      {fields.map(([key, label]) => <label key={key}>{label}<textarea aria-label={label} maxLength={6000} value={profile[key]} onChange={e => setProfile({ ...profile, [key]: e.target.value })} placeholder="未提供的信息留空即可"/></label>)}
      <p className="modal-hint">确认后整理到 data/user/profile/PROFILE.md，旧版保留。这里的内容不会自动用于目标分析。</p>
      <button className="primary" disabled={busy}>预览档案修改</button>
    </form> : !error && <p>正在读取档案…</p>}
    {change && <Dialog title="确认个人档案修改" close={() => setChange(undefined)} busy={busy}>
      <ChangeReview change={change} names={{}} busy={busy} decide={decision => run(async () => {
        await mutate(`/api/changes/${change.id}/decision`, { decision }); setChange(undefined); await load();
        changed();
        setNotice(decision === 'accept' ? '档案已确认并保存。' : '已拒绝修改，原档案保持不变。');
      })}/>
      {error && <p className="alert error" role="alert">{error}</p>}
    </Dialog>}
  </section>;
}
