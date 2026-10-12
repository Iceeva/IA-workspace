import { Component, effect, inject, input, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';

export interface TraceStep { id: string; title: string; agent: string; status: string; why: string; model: string; tools: { tool: string; action: string; ok: boolean; ms: number }[];
  tokens_in: number; tokens_out: number; duration_ms: number; error: string | null; output: string; next: string[]; fallbacks: { used?: string; failed: string[]; error?: string }[]; requested_by: string | null; }
export interface Trace { plan_source: string | null; plan_note: string | null; selection: { considered?: number; catalog_size?: number };
  replans: { task: string; agent: string; requested_by: string; reason: string }[]; steps: TraceStep[];
  totals: { tokens_in: number; tokens_out: number; duration_ms: number; tool_calls: number }; }

/** Trace d'observabilité (§41) : pour chaque agent, pourquoi il a été appelé, avec quel modèle et quels outils, et qui est appelé ensuite. */
@Component({
  selector: 'app-execution-trace',
  template: `
  @if (t(); as t) {
    <section class="trace" aria-label="Trace d’exécution">
      <p class="muted">Plan : {{ t.plan_source === 'workflow' ? 'workflow défini par l’utilisateur' : t.plan_source === 'planner' ? 'établi par le Planner' : 'plan par défaut' }}
        @if (t.plan_note) { ({{ t.plan_note }}) }
        · {{ t.steps.length }} étapes · {{ t.totals.tokens_in + t.totals.tokens_out }} tokens · {{ (t.totals.duration_ms / 1000).toFixed(1) }} s · {{ t.totals.tool_calls }} appels d’outils
        @if (t.selection.catalog_size) { · {{ t.selection.considered }} candidats examinés sur {{ t.selection.catalog_size }} agents }</p>
      <ol class="steps">
        @for (s of t.steps; track s.id) {
          <li [class]="s.status"><header><strong>{{ s.agent }}</strong> <span class="muted">— {{ s.title }}</span> <span class="st">{{ s.status }}</span></header>
            <dl>
              <dt>Pourquoi</dt><dd>{{ s.why }}</dd>
              <dt>Modèle</dt><dd>{{ s.model || '—' }} @for (f of s.fallbacks; track $index) { <span class="warn">· bascule : {{ f.failed.join(', ') }} @if (f.used) { → {{ f.used }} }</span> }</dd>
              <dt>Outils</dt><dd>@for (c of s.tools; track $index) { <span class="chip" [class.bad]="!c.ok">{{ c.tool }}.{{ c.action }} · {{ c.ms }} ms</span> } @empty { aucun }</dd>
              <dt>Consommation</dt><dd>{{ s.tokens_in }} → {{ s.tokens_out }} tokens · {{ (s.duration_ms / 1000).toFixed(1) }} s</dd>
              @if (s.error) { <dt>Erreur</dt><dd class="err">{{ s.error }}</dd> }
              @if (s.output) { <dt>Résultat</dt><dd><details><summary>Extrait</summary><pre>{{ s.output }}</pre></details></dd> }
              <dt>Ensuite</dt><dd>{{ s.next.length ? s.next.join(', ') : 'fin de chaîne' }}</dd>
            </dl></li>
        }
      </ol>
      @if (t.replans.length) { <h3>Replanifications</h3><ul>@for (r of t.replans; track $index) { <li>{{ r.requested_by }} a demandé « {{ r.agent }} » : {{ r.reason }}</li> }</ul> }
    </section>
  } @else { <p class="muted">Trace indisponible pour le moment.</p> }`,
  styles: [`.steps { list-style: none; padding: 0; display: grid; gap: .8rem; max-width: 56rem; } li { border: 1px solid var(--rule); background: var(--sheet); padding: .7rem 1rem; }
    li.FAILED { border-left: 3px solid #b91c1c; } li.COMPLETED { border-left: 3px solid #16a34a; } header { display: flex; gap: .5rem; align-items: baseline; } .st { margin-left: auto; font-size: .8rem; }
    dl { display: grid; grid-template-columns: 8rem 1fr; gap: .25rem .8rem; margin: .6rem 0 0; } dt { color: var(--ink-soft); } dd { margin: 0; } .chip { border: 1px solid var(--rule); padding: 0 .4rem; margin-right: .3rem; font-size: .85rem; }
    .chip.bad, .err { color: #b91c1c; border-color: #b91c1c; } .warn { color: #b45309; } pre { white-space: pre-wrap; max-height: 12rem; overflow: auto; }`],
})
export class ExecutionTrace {
  executionId = input.required<string>(); version = input<number>(0);   // `version` : change à chaque événement reçu → recharge
  private api = inject(ApiService);
  t = signal<Trace | null>(null);
  constructor() { effect(() => { this.version(); this.api.get<Trace>(`/api/executions/${this.executionId()}/trace`).subscribe({ next: r => this.t.set(r.data), error: () => {} }); }); }
}
