import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { ThemeService } from '../../core/theme.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-settings', imports: [FormsModule],
  template: `<div class="page-head"><h1>Paramètres</h1></div>
  @if (auth.me(); as me) {
    <section class="panel"><h2>Compte</h2><p>{{ me.full_name }} · {{ me.email }}</p>
      @if (!me.email_verified) { <p class="muted">Adresse non vérifiée. <button class="btn ghost small" (click)="resend()">Renvoyer le lien</button></p> } @else { <p class="muted">Adresse vérifiée.</p> }</section>
    <section class="panel"><h2>Apparence</h2>
      <div role="radiogroup" aria-label="Thème">@for (t of ['system', 'light', 'dark']; track t) { <label class="radio"><input type="radio" name="theme" [checked]="theme.mode() === t" (change)="theme.set($any(t))"> {{ t === 'system' ? 'Système' : t === 'light' ? 'Clair' : 'Sombre' }}</label> }</div></section>
    <section class="panel"><h2>Organisation</h2>
      @for (o of me.organizations; track o.id) { <p>{{ o.name }} <span class="muted">· {{ o.role }}{{ o.id === auth.org() ? ' · active' : '' }}</span></p> }
      <form (ngSubmit)="createOrg()" class="row"><input [(ngModel)]="orgName" name="o" placeholder="Nouvelle organisation" aria-label="Nom de l’organisation"><button class="btn small" [disabled]="!orgName.trim()">Créer</button></form></section>
    <section class="panel"><h2>Clés API</h2><p class="muted">Utilisez l’en-tête <code>X-API-Key</code> avec <code>X-Organization-Id</code>. Une clé n’est affichée qu’une seule fois.</p>
      @if (newKey()) { <p role="status"><strong>Copiez cette clé maintenant :</strong> <code>{{ newKey() }}</code></p> }
      <form (ngSubmit)="createKey()" class="row"><input [(ngModel)]="keyName" name="k" placeholder="Nom de la clé" aria-label="Nom de la clé"><button class="btn small" [disabled]="!keyName.trim()">Générer</button></form>
      @for (k of keys(); track k.id) { <p>{{ k.name }} <span class="muted">· {{ k.prefix }}…</span> <button class="btn danger small" (click)="revoke(k.id)">Révoquer</button></p> }</section>
  }`,
  styles: [`section { max-width: 40rem; margin-bottom: 1.2rem; } .row { display: flex; gap: .5rem; margin: .6rem 0; } .row input { flex: 1; background: var(--bench); border: 1px solid var(--rule); padding: .4rem .6rem; } .radio { margin-right: 1rem; } code { word-break: break-all; }`],
})
export class Settings {
  auth = inject(AuthService); theme = inject(ThemeService); private api = inject(ApiService); private toast = inject(Toast);
  keys = signal<any[]>([]); newKey = signal(''); orgName = ''; keyName = '';
  constructor() { this.loadKeys(); }
  loadKeys() { this.api.get<any[]>('/api/api-keys').subscribe(r => this.keys.set(r.data)); }
  resend() { this.api.post<{ status: string }>('/api/auth/resend-verification', {}).subscribe(r => this.toast.info(r.data.status === 'sent' ? 'E-mail envoyé' : 'Envoi impossible : SMTP non configuré')); }
  createOrg() { this.api.post('/api/organizations', { name: this.orgName }).subscribe(() => { this.orgName = ''; this.auth.loadMe(); this.toast.info('Organisation créée'); }); }
  createKey() { this.api.post<{ key: string }>('/api/api-keys', { name: this.keyName }).subscribe(r => { this.newKey.set(r.data.key); this.keyName = ''; this.loadKeys(); }); }
  revoke(id: string) { this.api.delete(`/api/api-keys/${id}`).subscribe(() => this.loadKeys()); }
}
