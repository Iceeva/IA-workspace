import { API } from './auth.service';

export interface StreamEvent { delta?: string; error?: string; done?: boolean; tokens?: number; conversation_id?: string; }

/** Lit le flux SSE de POST /api/chat avec fetch (EventSource ne permet pas les en-têtes d'authentification). */
export async function* streamChat(body: unknown, token: string, org: string, signal?: AbortSignal): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API}/api/chat`, { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'X-Organization-Id': org },
    body: JSON.stringify(body) });
  if (!res.ok || !res.body) {
    const j = await res.json().catch(() => null);
    throw new Error(j?.error?.message ?? `Erreur ${res.status}`);
  }
  if (res.headers.get('content-type')?.includes('application/json')) { // mode équipe : pas de flux
    yield { done: true, ...(await res.json()).data };
    return;
  }
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      if (frame.startsWith('data: ')) yield JSON.parse(frame.slice(6));
    }
  }
}
