import { Injectable, signal } from '@angular/core';

const KEY = 'aiw.bridge';
export interface BridgeConf { url: string; token: string; }

/** Client du Local Bridge (127.0.0.1) appelé directement depuis le navigateur : les données de la machine ne passent pas par le serveur. */
@Injectable({ providedIn: 'root' })
export class BridgeClient {
  conf = signal<BridgeConf>(this.load());
  private load(): BridgeConf {
    try { const v = JSON.parse(localStorage.getItem(KEY) ?? ''); if (v?.url) return v; } catch { /* stockage indisponible */ }
    return { url: 'http://127.0.0.1:8765', token: '' };
  }
  save(c: BridgeConf) {
    this.conf.set(c);
    try { localStorage.setItem(KEY, JSON.stringify(c)); } catch { /* ignoré */ }
  }
  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    const { url, token } = this.conf();
    const r = await fetch(url.replace(/\/$/, '') + path, { ...init, headers: { ...(init?.headers ?? {}), Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j?.error?.message ?? `Bridge : HTTP ${r.status}`);
    return (j.data ?? j) as T;
  }
  health() { return this.call<any>('/health'); }
  hardware() { return this.call<any>('/hardware'); }
  runtimes() { return this.call<any[]>('/runtimes'); }
  gguf() { return this.call<any[]>('/gguf'); }
}
