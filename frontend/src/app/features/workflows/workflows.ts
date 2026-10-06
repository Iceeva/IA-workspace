import { Component, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

interface WfNode { id: string; agent: string; depends_on: string[]; status: string; duration_ms: number; output: string; }
const PALETTE = ['researcher', 'architect', 'coder', 'tester', 'reviewer'];

@Component({
  selector: 'app-workflows', imports: [FormsModule, RouterLink],
  template: `<div class="page-head"><h1>Éditeur de workflows</h1>
    <div class="bar"><select class="input" aria-label="Projet" [(ngModel)]="projectId"><option value="">Projet…</option>@for (p of projects(); track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
      <button class="btn" [disabled]="!canRun()" (click)="run()">Exécuter le workflow</button></div></div>
  <div class="layout">
    <aside class="panel" aria-label="Agents disponibles"><h2>Agents</h2><p class="muted">Glissez un agent dans la chaîne, ou cliquez pour l’ajouter.</p>
      @for (a of palette; track a) { <div class="chip" draggable="true" tabindex="0" (dragstart)="dragNew($event, a)" (click)="add(a)" (keydown.enter)="add(a)">{{ a }}</div> }</aside>
    <section aria-label="Chaîne de workflow" (dragover)="$event.preventDefault()" (drop)="drop($event, nodes().length)">
      <div class="node trigger panel"><strong>Déclencheur</strong>
        <label class="field">Mission (entrée)<textarea rows="3" [(ngModel)]="mission" placeholder="Décrivez la mission confiée au workflow"></textarea></label></div>
      @for (n of nodes(); track n.id; let i = $index) {
        <div class="arrow" aria-hidden="true">↓</div>
        <div class="node panel" draggable="true" (dragstart)="dragMove($event, i)" (dragover)="$event.preventDefault()" (drop)="drop($event, i); $event.stopPropagation()">
          <header><strong>{{ n.agent }}</strong><button class="btn ghost small" (click)="remove(i)" [attr.aria-label]="'Retirer ' + n.agent">Retirer</button></header>
          <dl><div><dt>Statut</dt><dd><span class="status" [class]="n.status">{{ n.status }}</span></dd></div>
            <div><dt>Modèle</dt><dd>{{ model }}</dd></div>
            <div><dt>Durée</dt><dd>{{ n.duration_ms ? (n.duration_ms / 1000).toFixed(1) + ' s' : '—' }}</dd></div></dl>
          @if (i > 0) { <fieldset><legend>Dépend de</legend>
            @for (p of nodes().slice(0, i); track p.id) { <label><input type="checkbox" [checked]="n.depends_on.includes(p.id)" (change)="toggleDep(n, p.id)"> {{ p.agent }} ({{ p.id }})</label> }</fieldset> }
          <details><summary>Entrée / Sortie</summary>
            <p class="muted">Entrée : {{ i === 0 ? 'mission du déclencheur' : 'sorties des nœuds dont il dépend' }}</p>
            <pre>{{ n.output || 'Pas encore de sortie.' }}</pre></details>
        </div>
      }
      @if (!nodes().length) { <p class="muted drop">Déposez ici le premier agent.</p> }
    </section>
  </div>
  @if (execId()) { <p>Exécution lancée : <a [routerLink]="['/executions', execId()]">voir le détail</a></p> }`,
  styles: [`.layout { display: grid; grid-template-columns: 14rem 1fr; gap: 1.5rem; max-width: 64rem; } .chip { border: 1px solid var(--ink); padding: .4rem .7rem; margin-bottom: .5rem; cursor: grab; background: var(--bench); }
    .node { max-width: 34rem; } .node header { display: flex; justify-content: space-between; align-items: center; } .arrow { text-align: center; color: var(--ink-soft); }
    dl { display: flex; gap: 1.5rem; margin: .6rem 0; } dt { color: var(--ink-soft); font-size: .8rem; } dd { margin: 0; } fieldset { border: 1px solid var(--rule); } label { display: block; }
    pre { white-space: pre-wrap; max-height: 12rem; overflow: auto; } .drop { border: 2px dashed var(--rule); padding: 1.5rem; text-align: center; } .bar { display: flex; gap: .6rem; }
    @media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }`],
})
export class Workflows implements OnDestroy {
  private api = inject(ApiService); private toast = inject(Toast);
  palette = PALETTE; model = 'modèle par défaut'; projects = signal<any[]>([]); nodes = signal<WfNode[]>([]); execId = signal(''); projectId = ''; mission = '';
  private seq = 0; private drag: { kind: 'new'; agent: string } | { kind: 'move'; from: number } | null = null; private timer?: any;
  constructor() { this.api.get<any[]>('/api/projects').subscribe(r => this.projects.set(r.data)); }
  canRun = () => !!this.projectId && this.mission.trim().length >= 5 && this.nodes().length > 0;
  add(agent: string, at = this.nodes().length) {
    const prev = this.nodes()[at - 1]; const n: WfNode = { id: 'n' + ++this.seq, agent, depends_on: prev ? [prev.id] : [], status: 'PENDING', duration_ms: 0, output: '' };
    this.nodes.update(l => [...l.slice(0, at), n, ...l.slice(at)]);
  }
  dragNew(e: DragEvent, agent: string) { this.drag = { kind: 'new', agent }; e.dataTransfer?.setData('text/plain', agent); }
  dragMove(e: DragEvent, from: number) { this.drag = { kind: 'move', from }; e.dataTransfer?.setData('text/plain', String(from)); }
  drop(e: DragEvent, at: number) {
    e.preventDefault(); const d = this.drag; this.drag = null; if (!d) return;
    if (d.kind === 'new') this.add(d.agent, at);
    else this.nodes.update(l => { const c = [...l], [m] = c.splice(d.from, 1); c.splice(d.from < at ? at - 1 : at, 0, m); return this.fixDeps(c); });
  }
  /** Après un déplacement, une dépendance ne peut viser qu'un nœud placé avant. */
  private fixDeps(l: WfNode[]) { return l.map((n, i) => ({ ...n, depends_on: n.depends_on.filter(d => l.findIndex(x => x.id === d) < i) })); }
  remove(i: number) { this.nodes.update(l => this.fixDeps(l.filter((_, k) => k !== i))); }
  toggleDep(n: WfNode, id: string) { n.depends_on = n.depends_on.includes(id) ? n.depends_on.filter(x => x !== id) : [...n.depends_on, id]; }
  run() {
    const workflow = this.nodes().map(n => ({ id: n.id, agent: n.agent, depends_on: n.depends_on }));
    this.api.post<{ id: string }>('/api/executions', { project_id: this.projectId, mission: this.mission, workflow }).subscribe(r => {
      this.execId.set(r.data.id); this.toast.info('Workflow lancé'); this.timer = setInterval(() => this.refresh(), 2500); });
  }
  private refresh() {
    this.api.get<any[]>('/api/tasks', { execution_id: this.execId() }).subscribe(r => {
      const by = Object.fromEntries(r.data.map(t => [t.key, t]));
      this.nodes.update(l => l.map(n => by[n.id] ? { ...n, status: by[n.id].status, duration_ms: by[n.id].duration_ms, output: by[n.id].output ?? '' } : n));
      if (r.data.length && r.data.every(t => ['COMPLETED', 'FAILED', 'CANCELLED', 'REVIEW_REQUIRED'].includes(t.status))) clearInterval(this.timer);
    });
  }
  ngOnDestroy() { clearInterval(this.timer); }
}
