import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-usage', imports: [DecimalPipe],
  template: `<div class="page-head"><h1>Usage</h1></div>
  @if (u(); as u) {
    <dl class="readings">
      <div><dt>Tokens utilisés</dt><dd>{{ u.tokens | number }}</dd></div><div><dt>Appels LLM</dt><dd>{{ u.llm_calls | number }}</dd></div>
      <div><dt>Exécutions</dt><dd>{{ u.executions }}</dd></div><div><dt>Projets</dt><dd>{{ u.projects }}</dd></div><div><dt>Agents</dt><dd>{{ u.agents }}</dd></div>
      <div><dt>Stockage</dt><dd>{{ (u.storage_bytes / 1048576).toFixed(1) }} Mo</dd></div>
      <div><dt>Temps d’exécution</dt><dd>{{ (u.execution_time_ms / 1000).toFixed(0) }} s</dd></div></dl>
    <div class="grid-2">
      <section><h2>Quota de tokens ({{ u.plan }})</h2>
        <div class="meter" role="meter" [attr.aria-valuenow]="u.tokens" aria-valuemin="0" [attr.aria-valuemax]="u.token_limit"><div [style.width.%]="pct(u.tokens, u.token_limit)"></div></div>
        <p class="muted">{{ u.tokens | number }} / {{ u.token_limit | number }}</p>
        <h2>Stockage</h2>
        <div class="meter" role="meter" [attr.aria-valuenow]="u.storage_bytes / 1048576" aria-valuemin="0" [attr.aria-valuemax]="u.storage_limit_mb"><div [style.width.%]="pct(u.storage_bytes / 1048576, u.storage_limit_mb)"></div></div>
        <p class="muted">{{ (u.storage_bytes / 1048576).toFixed(1) }} / {{ u.storage_limit_mb }} Mo</p></section>
      <section><h2>Tokens par agent (mois)</h2>
        @for (a of u.by_agent; track a.agent) { <div class="bar"><span>{{ a.agent }}</span><div class="meter"><div [style.width.%]="pct(a.tokens, maxAgent())"></div></div><span>{{ a.tokens | number }}</span></div> }
        @empty { <p class="muted">Aucun usage ce mois-ci.</p> }</section>
    </div>
    <h2 style="margin-top:2rem">14 derniers jours</h2>
    @if (u.daily.length) {
      <svg [attr.viewBox]="'0 0 ' + (u.daily.length * 40 + 20) + ' 150'" class="chart" role="img" aria-label="Tokens par jour">
        @for (d of u.daily; track d.day; let i = $index) { <rect [attr.x]="20 + i * 40" [attr.y]="130 - h(d.tokens)" width="26" [attr.height]="h(d.tokens)" fill="var(--titration)"/>
          <text [attr.x]="33 + i * 40" y="146" text-anchor="middle" font-size="9" fill="var(--ink-soft)">{{ d.day.slice(5) }}</text> }
      </svg>
    } @else { <p class="muted">Pas de données.</p> }
  } @else { <p>Chargement…</p> }`,
  styles: [`.readings { display: flex; flex-wrap: wrap; gap: 2rem; margin: 0 0 2rem; padding: 0; } .readings div { border-top: 2px solid var(--ink); padding-top: .5rem; min-width: 8rem; } dt { color: var(--ink-soft); } dd { margin: 0; font: 1.8rem var(--serif); }
    .meter { height: .6rem; background: var(--rule); } .meter div { height: 100%; background: var(--titration); } .bar { display: grid; grid-template-columns: 7rem 1fr 5rem; gap: .6rem; align-items: center; margin-bottom: .4rem; }
    .chart { width: 100%; max-width: 40rem; background: var(--sheet); border: 1px solid var(--rule); }`],
})
export class Usage {
  private api = inject(ApiService);
  u = signal<any>(null);
  maxAgent = computed(() => Math.max(1, ...(this.u()?.by_agent ?? []).map((a: any) => a.tokens)));
  private maxDay = computed(() => Math.max(1, ...(this.u()?.daily ?? []).map((d: any) => d.tokens)));
  constructor() { this.api.get<any>('/api/usage').subscribe(r => this.u.set(r.data)); }
  pct = (v: number, max: number) => max ? Math.min(100, (v / max) * 100) : 0;
  h = (t: number) => Math.max(2, (t / this.maxDay()) * 110);
}
