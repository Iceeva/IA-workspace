import { Injectable, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

export const API = (globalThis as any).__API_URL__ ?? 'http://localhost:8000';
interface Tokens { success: true; data: { access_token: string; refresh_token: string }; }

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  // sessionStorage : le jeton disparaît à la fermeture de l'onglet
  private _access = signal<string | null>(sessionStorage.getItem('aiw.access'));
  private _refresh = signal<string | null>(sessionStorage.getItem('aiw.refresh'));
  readonly org = signal<string | null>(sessionStorage.getItem('aiw.org'));
  readonly me = signal<{ full_name: string; email: string; email_verified: boolean; is_platform_admin: boolean;
    organizations: { id: string; name: string; role: string }[] } | null>(null);
  readonly isAuthenticated = computed(() => !!this._access());
  get accessToken() { return this._access(); }
  get refreshToken() { return this._refresh(); }

  async login(email: string, password: string) {
    const r = await firstValueFrom(this.http.post<Tokens>(`${API}/api/auth/login`, { email, password }));
    this.store(r);
    await this.loadMe();
    if (!this.org()) this.setOrg(this.me()?.organizations[0]?.id ?? null);
  }

  async register(body: { email: string; password: string; full_name: string; organization_name: string }) {
    const r = await firstValueFrom(this.http.post<Tokens & { organization_id: string; email_verification: string }>(`${API}/api/auth/register`, body));
    this.store(r); this.setOrg(r.organization_id); await this.loadMe();
    return r.email_verification;
  }

  async loadMe() {
    this.me.set((await firstValueFrom(this.http.get<any>(`${API}/api/me`))).data);
  }

  switchOrg(id: string) { this.setOrg(id); }

  async refresh(): Promise<boolean> {
    if (!this._refresh()) return false;
    try {
      this.store(await firstValueFrom(this.http.post<Tokens>(`${API}/api/auth/refresh`, { refresh_token: this._refresh() })));
      return true;
    } catch { this.logout(); return false; }
  }

  logout() {
    const rt = this._refresh();
    if (rt && this._access()) this.http.post(`${API}/api/auth/logout`, { refresh_token: rt }).subscribe({ error: () => {} });
    this.me.set(null);
    ['access', 'refresh', 'org'].forEach(k => sessionStorage.removeItem('aiw.' + k));
    this._access.set(null); this._refresh.set(null); this.org.set(null);
  }

  private setOrg(id: string | null) { this.org.set(id); if (id) sessionStorage.setItem('aiw.org', id); }
  private store(t: Tokens) {
    this._access.set(t.data.access_token); this._refresh.set(t.data.refresh_token);
    sessionStorage.setItem('aiw.access', t.data.access_token); sessionStorage.setItem('aiw.refresh', t.data.refresh_token);
  }
}
