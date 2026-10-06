import { Component, OnDestroy, computed, inject, input, signal } from '@angular/core';
import { ApiService, ExecEvent, ExecutionDto, TaskDto } from '../../core/api.service';
import { layoutGraph } from '../../core/graph-layout';

const TERMINAL = ['COMPLETED', 'FAILED', 'CANCELLED'];
const LABEL: Record<string, string> = { PENDING: 'En attente', QUEUED: 'En file', RUNNING: 'En cours', WAITING: 'En attente', COMPLETED: 'Terminée',
  FAILED: 'Échec', CANCELLED: 'Annulée', CANCELLING: 'Annulation', REVIEW_REQUIRED: 'À relire' };
const FILL: Record<string, string> = { COMPLETED: 'var(--culture)', FAILED: 'var(--flag)', RUNNING: 'var(--reagent)' };

@Component({
  selector: 'app-execution-detail',
  template: `
  @if (exec(); as e) {
    <header class="head">
      <h1>{{ e.mission }}</h1>
      <p><span class="status" [class]="e.status">{{ label(e.status) }}</span> · {{ tokens() }} tokens</p>
      @if (!terminal()) { <button class="btn ghost" (click)="cancel()">Annuler</button> }
    </header>

    <h2>Plaque d’exécution</h2>
    @if (layout().wells.length) {
      <svg class="plate" [attr.viewBox]="'0 0 ' + layout().w + ' ' + layout().h" role="group" aria-label="Graphe des tâches">
        @for (l of layout().links; track l.key) { <line [attr.x1]="l.x1" [attr.y1]="l.y1" [attr.x2]="l.x2" [attr.y2]="l.y2" stroke="var(--rule)" stroke-width="1.5"/> }
        @for (w of layout().wells; track w.t.id) {
          <g [attr.transform]="'translate(' + w.x + ',' + w.y + ')'" tabindex="0" role="button" class="well"
             [attr.aria-label]="w.t.agent + ', ' + label(w.t.status)" (click)="pick(w.t.id)" (keydown.enter)="pick(w.t.id)">
            <circle r="24" [attr.fill]="fill(w.t.status)" fill-opacity="0.9" stroke="var(--ink)" [attr.stroke-width]="selected() === w.t.id ? 3 : 1.5"
                    [class.well-running]="w.t.status === 'RUNNING'" [attr.stroke-dasharray]="w.t.status === 'PENDING' ? '3 3' : null"/>
            @if (w.t.status === 'REVIEW_REQUIRED') { <circle r="30" fill="none" stroke="var(--reagent)" stroke-width="2"/> }
            <text y="46" text-anchor="middle" fill="var(--ink)" font-size="13" font-weight="500">{{ w.t.agent }}</text>
            <text y="62" text-anchor="middle" fill="var(--ink-soft)" font-size="11">{{ w.t.duration_ms ? (w.t.duration_ms / 1000).toFixed(1) + ' s' : label(w.t.status) }}</text>
          </g>
        }
      </svg>
    } @else { <p class="muted">Le plan est en cours d’élaboration…</p> }

    @if (sel(); as t) {
      <section class="panel detail" aria-live="polite">
        <h2>{{ t.title }} <span class="muted">· {{ t.agent }}</span></h2>
        <p>{{ label(t.status) }} · {{ t.tokens }} tokens · {{ t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + ' s' : '—' }}</p>
        @if (t.error) { <p class="error" role="alert">{{ t.error }}</p> }
        <h3>Messages reçus</h3>
        @for (m of messagesFor(t.agent); track $index) { <pre>{{ m }}</pre> } @empty { <p class="muted">Aucun.</p> }
        <h3>Sortie</h3>
        @if (outputs()[t.id]) { <pre>{{ outputs()[t.id] }}</pre> } @else { <p class="muted">Pas encore de sortie.</p> }
      </section>
    }

    @if (files().length) {
      <h2>Fichiers écrits par le Code Agent</h2>
      @for (f of files(); track f.path) { <details class="panel"><summary>{{ f.path }}</summary><pre class="diff">{{ f.diff }}</pre></details> }
    }
    @if (e.error) { <p class="error" role="alert">{{ e.error }}</p> }
    @if (e.result) { <h2>Résultat</h2><pre class="result">{{ e.result }}</pre> }

    <h2>Journal</h2>
    <div class="table-wrap"><table class="ledger"><thead><tr><th>#</th><th>Événement</th><th>Détail</th></tr></thead>
      <tbody>@for (ev of events(); track ev.seq) { <tr><td>{{ ev.seq }}</td><td>{{ ev.kind }}</td><td>{{ ev.data.title ?? ev.data.path ?? ev.data.reason ?? ev.data.error ?? '' }}</td></tr> }</tbody></table></div>
  } @else { <p>Chargement…</p> }`,
  styles: [`.head { margin-bottom: 2rem; } .plate { width: 100%; max-width: 56rem; background: var(--sheet); border: 1px solid var(--rule); margin: 1rem 0 1.5rem; } .well { cursor: pointer; }
    pre { white-space: pre-wrap; overflow-x: auto; max-height: 24rem; background: var(--sheet); border: 1px solid var(--rule); padding: .8rem; } .detail pre { background: var(--bench); } .detail { margin-bottom: 2rem; max-width: 56rem; }
    .diff { font-size: .85rem; }`],
})
export class ExecutionDetail implements OnDestroy {
  id = input.required<string>();
  private api = inject(ApiService);
  exec = signal<ExecutionDto | null>(null); events = signal<ExecEvent[]>([]);
  tasks = signal<Record<string, TaskDto>>({}); outputs = signal<Record<string, string>>({}); selected = signal<string | null>(null);
  private msgs = signal<{ recipient: string; content: string }[]>([]);
  terminal = computed(() => TERMINAL.includes(this.exec()?.status ?? ''));
  tokens = computed(() => this.exec()?.tokens || Object.values(this.tasks()).reduce((s, t) => s + t.tokens, 0));
  layout = computed(() => layoutGraph(this.tasks()));
  sel = computed(() => this.selected() ? this.tasks()[this.selected()!] : null);
  files = computed(() => this.events().filter(e => e.kind === 'file.written').map(e => e.data as { path: string; diff: string }));
  private timer = setInterval(() => this.poll(), 2000);
  constructor() { queueMicrotask(() => this.poll()); }

  label = (s: string) => LABEL[s] ?? s;
  fill = (s: string) => FILL[s] ?? 'transparent';
  messagesFor = (agent: string) => this.msgs().filter(m => m.recipient === agent).map(m => m.content);

  pick(id: string) {
    this.selected.set(id);
    this.api.get<any[]>('/api/tasks', { execution_id: this.id() }).subscribe(r => {
      this.outputs.set(Object.fromEntries(r.data.filter(t => t.output).map(t => [t.key, t.output])));
    });
    this.api.get<any[]>('/api/messages', { execution_id: this.id() }).subscribe(r => this.msgs.set(r.data));
  }

  private poll() {
    const last = this.events().at(-1)?.seq ?? 0;
    this.api.get<ExecutionDto>(`/api/executions/${this.id()}`).subscribe(r => this.exec.set(r.data));
    this.api.get<ExecEvent[]>(`/api/executions/${this.id()}/events`, { after: last }).subscribe(r => {
      if (!r.data.length) return;
      this.events.update(e => [...e, ...r.data]);
      this.tasks.update(cur => { const next = { ...cur };
        for (const ev of r.data) {
          if (ev.kind === 'graph') ev.data.nodes.forEach((n: TaskDto) => next[n.id] = n);
          else if (ev.kind.startsWith('task.') && ev.data.agent && ev.data.status) next[ev.data.id] = { ...next[ev.data.id], ...ev.data };
        } return next; });
    });
    if (this.terminal()) clearInterval(this.timer);
  }
  cancel() { this.api.post(`/api/executions/${this.id()}/cancel`, {}).subscribe(); }
  ngOnDestroy() { clearInterval(this.timer); }
}
