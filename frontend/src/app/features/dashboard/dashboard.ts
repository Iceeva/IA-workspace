import { Component, OnDestroy, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-dashboard', imports: [RouterLink, DatePipe, DecimalPipe],
  template: `
  <div class="page-head"><h1>Tableau de bord</h1><a class="btn" routerLink="/executions">Nouvelle mission</a></div>
  @if (d(); as d) {
    <dl class="readings">
      <div><dt>Projets</dt><dd>{{ u()?.projects ?? '—' }}</dd></div>
      <div><dt>Agents configurés</dt><dd>{{ u()?.agents ?? '—' }}</dd></div>
      <div><dt>Tâches en cours</dt><dd>{{ d.running_tasks }}</dd></div>
      <div><dt>Exécutions actives</dt><dd>{{ d.active_executions }}</dd></div>
      <div><dt>Tokens (mois)</dt><dd>{{ (u()?.tokens ?? 0) | number }}</dd></div>
    </dl>
    <div class="grid-2">
      <section><h2>Moniteur d’agents</h2>
        @if (d.agent_monitor.length) {
          <ul class="monitor">@for (a of d.agent_monitor; track $index) { <li><span class="status" [class]="a.status === 'RUNNING' ? 'RUNNING' : 'PENDING'">{{ a.agent }}</span><span class="muted">{{ a.status === 'RUNNING' ? 'au travail' : 'en attente' }}</span></li> }</ul>
        } @else { <p class="muted">Aucun agent actif pour le moment.</p> }
      </section>
      <section><h2>Erreurs récentes</h2>
        @for (e of d.errors; track e.id) { <p><a [routerLink]="['/executions', e.id]">{{ e.mission }}</a><br><span class="error">{{ e.error }}</span></p> }
        @empty { <p class="muted">Aucune erreur.</p> }
      </section>
    </div>
    <h2 style="margin-top:2rem">Activité récente</h2>
    <div class="table-wrap"><table class="ledger"><thead><tr><th>Mission</th><th>État</th><th>Tokens</th><th>Date</th></tr></thead>
      <tbody>@for (e of d.recent; track e.id) { <tr><td><a [routerLink]="['/executions', e.id]">{{ e.mission }}</a></td>
        <td><span class="status" [class]="e.status">{{ e.status }}</span></td><td>{{ e.tokens | number }}</td><td>{{ e.created_at | date:'short' }}</td></tr> }</tbody></table></div>
  } @else { <p>Chargement…</p> }`,
  styles: [`.readings { display: flex; flex-wrap: wrap; gap: 2.5rem; margin: 0 0 2.5rem; padding: 0; } .readings div { border-top: 2px solid var(--ink); padding-top: .5rem; min-width: 8rem; }
    dt { color: var(--ink-soft); } dd { margin: 0; font: 2rem var(--serif); } .monitor { list-style: none; padding: 0; } .monitor li { display: flex; justify-content: space-between; border-bottom: 1px solid var(--rule); padding: .4rem 0; }`],
})
export class Dashboard implements OnDestroy {
  private api = inject(ApiService);
  d = signal<any>(null); u = signal<any>(null);
  private t = setInterval(() => this.load(), 5000);
  constructor() { this.load(); this.api.get<any>('/api/usage').subscribe(r => this.u.set(r.data)); }
  private load() { this.api.get<any>('/api/dashboard').subscribe(r => this.d.set(r.data)); }
  ngOnDestroy() { clearInterval(this.t); }
}
