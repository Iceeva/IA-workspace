import { Component, inject, signal } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-providers', imports: [FormsModule, JsonPipe],
  template: `<div class="page-head"><h1>Fournisseurs et modèles</h1></div>
  <div class="grid-2">
  <section class="panel"><h2>Fournisseurs connectés</h2>
    @for (p of providers(); track p.id) {
      <div class="row"><div><strong>{{ p.name }}</strong> <span class="muted">{{ p.kind }}{{ p.local ? ' · local' : '' }}</span><br>
        <span class="muted">{{ p.models.length }} modèle(s) · clé : {{ p.has_key ? p.key_hint : 'aucune' }}</span></div>
        <div><button class="btn ghost small" (click)="toggle(p)">{{ p.enabled ? 'Désactiver' : 'Activer' }}</button>
          <button class="btn ghost small" (click)="remove(p)">Supprimer</button></div></div>
    } @empty { <p class="muted">Aucun fournisseur. Ajoutez-en un ci-contre.</p> }
  </section>
  <section class="panel"><h2>Ajouter un fournisseur</h2>
    <label class="field">Type<select class="input" [(ngModel)]="f.kind" (ngModelChange)="preset()">@for (k of presets(); track k.kind) { <option [value]="k.kind">{{ k.kind }}</option> }</select></label>
    <label class="field">Nom (minuscules, chiffres, - _)<input [(ngModel)]="f.name"></label>
    <label class="field">Endpoint<input [(ngModel)]="f.base_url" placeholder="https://…"></label>
    <label class="field">Clé API (chiffrée, jamais réaffichée)<input type="password" [(ngModel)]="f.api_key" autocomplete="off"></label>
    <label class="field">Modèles (identifiants séparés par des virgules)<input [(ngModel)]="f.models"></label>
    <label class="check"><input type="checkbox" [(ngModel)]="f.local"> Modèles locaux (restent sur la machine)</label>
    <button class="btn" [disabled]="!f.name || !f.kind" (click)="add()">Ajouter</button>
  </section></div>
  <section class="panel" style="margin-top:1.5rem"><h2>Stratégie d’utilisation des modèles</h2>
    @if (s(); as s) {
      <label class="field">Mode<select class="input" [(ngModel)]="s.mode">
        <option value="single">Un seul modèle pour tous les agents</option><option value="per_agent">Un modèle par agent</option><option value="auto">Routage automatique</option></select></label>
      @if (s.mode === 'single') { <label class="field">Modèle unique (fournisseur:modèle)<input [(ngModel)]="s.single_model"></label> }
      @if (s.mode === 'per_agent') { <label class="field">Affectations (agent=fournisseur:modèle, une par ligne)<textarea rows="4" [(ngModel)]="perAgent"></textarea></label> }
      @if (s.mode === 'auto') { <div class="grid-2">
        @for (w of ['quality','speed','cost']; track w) { <label class="field">Poids « {{ w }} » : {{ s.weights[w] }}<input type="range" min="0" max="1" step="0.05" [(ngModel)]="s.weights[w]"></label> } </div> }
      <label class="check"><input type="checkbox" [(ngModel)]="s.local_only"> Local uniquement</label>
      <label class="check"><input type="checkbox" [(ngModel)]="s.sensitive_local"> Tâches sensibles toujours en local</label>
      <label class="check"><input type="checkbox" [(ngModel)]="s.prefer_local"> Préférer le local</label>
      <label class="field">Repli (fournisseur:modèle, dans l’ordre, séparés par des virgules)<input [(ngModel)]="fallback"></label>
      <div class="grid-2"><label class="field">Budget mensuel (USD)<input type="number" min="0" [(ngModel)]="s.monthly_budget_usd"></label>
        <label class="field">À la limite<select class="input" [(ngModel)]="s.on_limit"><option value="block">Bloquer</option><option value="confirm">Demander confirmation</option></select></label></div>
      <button class="btn" (click)="save()">Enregistrer</button>
    }
  </section>
  <section class="panel" style="margin-top:1.5rem"><h2>Simulation du routage</h2>
    <label class="field">Capacités requises (virgules)<input [(ngModel)]="needs"></label>
    <label class="check"><input type="checkbox" [(ngModel)]="sensitive"> Données sensibles</label>
    <button class="btn ghost" (click)="route()">Quel modèle serait choisi ?</button>
    @if (decision(); as d) { <pre>{{ d | json }}</pre> }
  </section>`,
  styles: [`.row { display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--rule); padding: .6rem 0; } .check { display: block; margin: .4rem 0; } pre { overflow: auto; font-size: .8rem; }`],
})
export class Providers {
  private api = inject(ApiService); private toast = inject(Toast);
  providers = signal<any[]>([]); presets = signal<any[]>([]); s = signal<any>(null); decision = signal<any>(null);
  f: any = { kind: 'openai', name: '', base_url: '', api_key: '', models: '', local: false };
  perAgent = ''; fallback = ''; needs = 'chat'; sensitive = false;
  constructor() {
    this.api.get<any[]>('/api/providers/presets').subscribe(r => { this.presets.set(r.data); this.preset(); });
    this.load();
    this.api.get<any>('/api/ai-settings').subscribe(r => { const d = r.data;
      this.s.set(d); this.fallback = (d.fallback ?? []).join(', ');
      this.perAgent = Object.entries(d.per_agent ?? {}).map(([k, v]) => `${k}=${v}`).join('\n'); });
  }
  load() { this.api.get<any[]>('/api/providers').subscribe(r => this.providers.set(r.data)); }
  preset() { const p = this.presets().find(x => x.kind === this.f.kind); if (p) this.f.base_url = p.base_url ?? ''; }
  add() {
    const models = String(this.f.models).split(',').map(x => x.trim()).filter(Boolean).map(id => ({ id }));
    this.api.post('/api/providers', { kind: this.f.kind, name: this.f.name, base_url: this.f.base_url || null,
      api_key: this.f.api_key || null, models, local: this.f.local }).subscribe({
      next: () => { this.toast.info('Fournisseur ajouté'); this.f.api_key = ''; this.f.name = ''; this.load(); },
      error: e => this.toast.error(e?.error?.error?.message ?? 'Ajout impossible') });
  }
  toggle(p: any) { this.api.patch(`/api/providers/${p.id}`, { enabled: !p.enabled }).subscribe(() => this.load()); }
  remove(p: any) { if (confirm(`Supprimer « ${p.name} » ?`)) this.api.delete(`/api/providers/${p.id}`).subscribe(() => this.load()); }
  save() {
    const d = { ...this.s() };
    d.fallback = this.fallback.split(',').map(x => x.trim()).filter(Boolean);
    d.per_agent = Object.fromEntries(this.perAgent.split('\n').map(l => l.split('=').map(x => x.trim())).filter(p => p.length === 2 && p[0] && p[1]));
    d.monthly_budget_usd = d.monthly_budget_usd === '' ? null : d.monthly_budget_usd;
    this.api.put('/api/ai-settings', d).subscribe({ next: () => this.toast.info('Stratégie enregistrée'),
      error: e => this.toast.error(e?.error?.error?.message ?? 'Enregistrement impossible') });
  }
  route() {
    this.api.post<any>('/api/models/route', { needs: this.needs.split(',').map(x => x.trim()).filter(Boolean), sensitive: this.sensitive }).subscribe({
      next: r => this.decision.set(r.data), error: e => this.toast.error(e?.error?.error?.message ?? 'Aucun modèle disponible') });
  }
}
