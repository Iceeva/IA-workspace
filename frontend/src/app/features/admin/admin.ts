import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

const TABS = [['users', 'Utilisateurs'], ['organizations', 'Organisations'], ['workspaces', 'Espaces'], ['agents', 'Agents'], ['models', 'Modèles'],
  ['providers', 'Providers'], ['executions', 'Exécutions'], ['usage', 'Usage'], ['audit', 'Audit & journaux']] as const;

@Component({
  selector: 'app-admin', imports: [FormsModule],
  template: `<div class="page-head"><h1>Administration</h1></div>
  <div class="tabs" role="tablist">@for (t of tabs; track t[0]) { <button role="tab" [class.on]="tab() === t[0]" [attr.aria-selected]="tab() === t[0]" (click)="open(t[0])">{{ t[1] }}</button> }</div>
  @if (tab() === 'providers') {
    <p class="muted">Un provider désactivé bloque toute nouvelle exécution et tout chat. Les clés API restent côté serveur (variables d’environnement).</p>
  }
  @if (tab() === 'models') {
    <form class="row" (ngSubmit)="addModel()"><select [(ngModel)]="mProv" name="p" aria-label="Provider"><option value="openrouter">openrouter</option><option value="openai">openai</option><option value="anthropic">anthropic</option><option value="ollama">ollama</option></select>
      <input [(ngModel)]="mId" name="m" placeholder="identifiant du modèle" aria-label="Identifiant du modèle"><button class="btn small" [disabled]="!mId.trim()">Ajouter</button></form>
  }
  @if (tab() === 'organizations') { <p class="muted">Pour modifier les limites d’une organisation, utilisez le formulaire sous le tableau.</p> }
  <div class="table-wrap"><table class="ledger"><thead><tr>@for (c of cols(); track c) { <th>{{ c }}</th> }<th></th></tr></thead><tbody>
    @for (r of rows(); track $index) { <tr>@for (c of cols(); track c) { <td>{{ r[c] }}</td> }<td>
      @if (tab() === 'providers' || tab() === 'models') { <button class="btn ghost small" (click)="toggle(r)">{{ r.enabled ? 'Désactiver' : 'Activer' }}</button> }
      @if (tab() === 'users' && !r.disabled) { <button class="btn danger small" (click)="disable(r.id)">Désactiver le compte</button> }</td></tr> }
    @empty { <tr><td [attr.colspan]="cols().length + 1" class="muted">Aucune donnée.</td></tr> }</tbody></table></div>
  @if (tab() === 'organizations' && rows().length) {
    <form class="panel row lim" (ngSubmit)="limits()"><select [(ngModel)]="lOrg" name="o" aria-label="Organisation">@for (r of rows(); track r.id) { <option [value]="r.id">{{ r.name }}</option> }</select>
      <input [(ngModel)]="lPlan" name="pl" aria-label="Plan"><input type="number" [(ngModel)]="lTok" name="t" aria-label="Limite de tokens"><input type="number" [(ngModel)]="lSto" name="s" aria-label="Limite de stockage (Mo)">
      <button class="btn small">Appliquer</button></form> }`,
  styles: [`.row { display: flex; gap: .5rem; margin-bottom: 1rem; flex-wrap: wrap; } .row input, .row select { background: var(--sheet); border: 1px solid var(--rule); padding: .4rem .6rem; } .lim { margin-top: 1rem; max-width: 48rem; }`],
})
export class Admin {
  private api = inject(ApiService); private toast = inject(Toast);
  tabs = TABS; tab = signal<string>('users'); rows = signal<any[]>([]); cols = signal<string[]>([]);
  mProv = 'openrouter'; mId = ''; lOrg = ''; lPlan = 'free'; lTok = 500000; lSto = 500;
  constructor() { this.open('users'); }
  open(t: string) {
    this.tab.set(t);
    this.api.get<any[]>(`/api/admin/${t === 'audit' ? 'audit' : t}`).subscribe(r => {
      this.rows.set(r.data.map(x => ({ ...x }))); this.cols.set(r.data.length ? Object.keys(r.data[0]).filter(k => k !== 'id' || t === 'audit') : []);
      if (t === 'organizations' && r.data[0]) this.lOrg = r.data[0].id;
    });
  }
  toggle(r: any) {
    const url = this.tab() === 'providers' ? `/api/admin/providers/${r.name}` : `/api/admin/models/${r.id}`;
    this.api.put(url, { enabled: !r.enabled }).subscribe(() => this.open(this.tab()));
  }
  addModel() { this.api.post('/api/admin/models', { provider: this.mProv, model_id: this.mId, enabled: true }).subscribe(() => { this.mId = ''; this.open('models'); }); }
  disable(id: string) { if (confirm('Désactiver ce compte ?')) this.api.post(`/api/admin/users/${id}/disable`, {}).subscribe(() => this.open('users')); }
  limits() { this.api.put(`/api/admin/organizations/${this.lOrg}/limits`, { plan: this.lPlan, monthly_token_limit: this.lTok, storage_limit_mb: this.lSto })
    .subscribe(() => { this.toast.info('Limites mises à jour'); this.open('organizations'); }); }
}
