import { Component, OnDestroy, inject, signal } from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-monitoring', imports: [DecimalPipe, DatePipe, RouterLink],
  template: `<div class="page-head"><h1>Monitoring</h1><span class="muted">actualisé toutes les 5 s</span></div>
  @if (o(); as o) {
    <dl class="readings">
      <div><dt>Tokens (mois)</dt><dd>{{ o.usage_month.tokens | number }}</dd></div>
      <div><dt>Coût estimé (mois)</dt><dd>{{ o.usage_month.cost_usd }} $</dd></div>
      <div><dt>Budget</dt><dd>{{ o.usage_month.budget_usd ?? '—' }}{{ o.usage_month.budget_usd ? ' $' : '' }}</dd></div>
      <div><dt>Appels LLM</dt><dd>{{ o.usage_month.calls | number }}</dd></div>
      <div><dt>Validations en attente</dt><dd>{{ o.pending_approvals }}</dd></div>
      <div><dt>Bridge local</dt><dd>{{ o.bridge.online ? 'en ligne' : 'hors ligne' }}</dd></div></dl>
    @if (o.usage_month.budget_usd) { <div class="meter" role="meter" aria-label="Budget consommé" [attr.aria-valuenow]="o.usage_month.cost_usd" aria-valuemin="0" [attr.aria-valuemax]="o.usage_month.budget_usd"><div [style.width.%]="pct(o.usage_month.cost_usd, o.usage_month.budget_usd)"></div></div> }
    <div class="grid-2" style="margin-top:1.5rem">
      <section class="panel"><h2>Fournisseurs</h2>
        @for (p of o.providers; track p.name) { <p><span class="dot" [class.on]="p.enabled"></span> {{ p.name }} <span class="muted">{{ p.kind }}{{ p.local ? ' · local' : '' }}</span></p> } @empty { <p class="muted">Aucun.</p> }</section>
      <section class="panel"><h2>Modèles les plus utilisés</h2>
        @for (m of o.usage_month.by_model; track m.model) { <p>{{ m.model || '—' }} <span class="muted">{{ m.tokens | number }} tokens · {{ m.cost_usd }} $</span></p> } @empty { <p class="muted">Aucun usage.</p> }</section>
      <section class="panel"><h2>Exécutions (30 j)</h2>
        @for (e of entries(o.executions_30d); track e[0]) { <p>{{ e[0] }} : <strong>{{ e[1] }}</strong></p> } @empty { <p class="muted">Aucune.</p> }
        <h3>Workflows (7 j)</h3>@for (e of entries(o.workflow_runs_7d); track e[0]) { <p>{{ e[0] }} : <strong>{{ e[1] }}</strong></p> } @empty { <p class="muted">Aucun.</p> }</section>
      <section class="panel"><h2>Dernières erreurs</h2>
        @for (e of o.recent_errors; track e.id) { <p><a [routerLink]="['/executions', e.id]">{{ e.at | date:'short' }}</a> — {{ e.error }}</p> } @empty { <p class="muted">Aucune erreur récente.</p> }</section>
    </div>
  } @else { <p>Chargement…</p> }
  @if (live(); as d) {
    <section class="panel" style="margin-top:1.5rem"><h2>Agents au travail</h2>
      <p class="muted">{{ d.running_tasks }} tâche(s) en cours · {{ d.active_executions }} exécution(s) active(s)</p>
      @for (a of d.agent_monitor; track $index) { <p>{{ a.agent }} <span class="muted">{{ a.status }}</span></p> } @empty { <p class="muted">Aucun agent actif.</p> }</section> }`,
  styles: [`.readings { display: flex; flex-wrap: wrap; gap: 2rem; margin: 0 0 1.5rem; padding: 0; } .readings div { border-top: 2px solid var(--ink); padding-top: .5rem; min-width: 8rem; } dt { color: var(--ink-soft); } dd { margin: 0; font: 1.6rem var(--serif); }
    .meter { height: .6rem; background: var(--rule); } .meter div { height: 100%; background: var(--titration); } .dot { display: inline-block; width: .6rem; height: .6rem; border-radius: 50%; background: #9ca3af; } .dot.on { background: #16a34a; }`],
})
export class Monitoring implements OnDestroy {
  private api = inject(ApiService);
  o = signal<any>(null); live = signal<any>(null);
  private t = setInterval(() => this.load(), 5000);
  constructor() { this.load(); }
  ngOnDestroy() { clearInterval(this.t); }
  load() { this.api.get<any>('/api/dashboard/overview').subscribe(r => this.o.set(r.data)); this.api.get<any>('/api/dashboard').subscribe(r => this.live.set(r.data)); }
  entries = (o: Record<string, number>) => Object.entries(o ?? {});
  pct = (v: number, max: number) => max ? Math.min(100, (v / max) * 100) : 0;
}
