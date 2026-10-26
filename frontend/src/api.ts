export type Category = string;
export type Kind = 'note' | 'task' | 'idea';
export type RecordStatus = 'open' | 'partial' | 'done';
export interface Fields { text: string; date: string; category: Category; status: RecordStatus }
export interface Entry extends Fields {
  id: string; kind: Kind; version: number; created_at: string; updated_at: string;
  source: string; processing: 'not_analyzed'; previous_version: number | null;
}
export interface Proposal {
  id: string; action: 'revise' | 'create_task' | 'create_idea'; status: 'pending' | 'accepted' | 'rejected';
  before: Entry | null; after: Fields; reason: string; expected_version: number | null; created_at: string;
}
export interface AppStatus {
  user_files?: import('./UserFilesPanel').UserFilesStatus;
  today: string; timezone: string; categories: Record<string, string>;
  storage: { healthy: boolean; errors: string[] }; model: { status: string; message: string };
}
export interface Daily {
  date: string; notice: string; groups: { category: string; label: string; state: string; records: Entry[] }[];
  uncategorized: Entry[]; tasks: Entry[];
}

let csrf = '';
let leavingPage = false;
const pendingReads = new Set<AbortController>();
window.addEventListener('pagehide', () => { leavingPage = true; for (const controller of pendingReads) controller.abort(); });
window.addEventListener('pageshow', () => { leavingPage = false; });
const attempts = new Map<string, string>();
export async function connect() {
  const response = await fetch('/api/session');
  if (!response.ok) throw new Error('无法建立本机会话，请刷新后重试。');
  csrf = (await response.json()).csrf_token;
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (leavingPage) throw new Error('页面正在刷新，请在新页面继续。');
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init.signal?.aborted) abort();
  init.signal?.addEventListener('abort', abort, { once: true });
  if (!init.method || init.method === 'GET') pendingReads.add(controller);
  try {
    const response = await fetch(path, { ...init, signal: controller.signal, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...init.headers } });
    if (!response.ok) {
      if(response.status===401)window.dispatchEvent(new Event('personalai-auth-expired'));
      const body = await response.json().catch(() => null);
      throw new Error(typeof body?.detail === 'string' ? body.detail : '操作未完成，请保留输入并重试。');
    }
    return await response.json();
  } finally {
    pendingReads.delete(controller);
    init.signal?.removeEventListener('abort', abort);
  }
}
export async function mutate<T>(path: string, body: object): Promise<T> {
  const signature = JSON.stringify([path, body]);
  const requestId = attempts.get(signature) ?? crypto.randomUUID();
  attempts.set(signature, requestId);
  const result = await api<T>(path, { method: 'POST', body: JSON.stringify({ ...body, request_id: requestId }) });
  attempts.delete(signature);
  return result;
}
export async function exportBackup() {
  const response = await fetch('/api/backups/export', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
  if (!response.ok) throw new Error((await response.json()).detail || '备份失败');
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] ?? 'personalai-backup.zip';
  link.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
export async function verifyBackup(file: File) {
  const response = await fetch('/api/backups/verify', { method: 'POST', headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/zip' }, body: file });
  const result = await response.json();
  if (!response.ok) throw new Error(result.detail || '备份校验失败');
  return result as { message: string; records: number; events: number };
}
