import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { layoutGraph } from '../../core/graph-layout';

type N = Record<string, any>;
export const NODE_TYPES = ['agent', 'http', 'code', 'transform', 'condition', 'human', 'merge', 'loop'] as const;
const LABEL: Record<string, string> = { agent: 'Agent', http: 'Appel HTTP', code: 'Code Python', transform: 'Transformation', condition: 'Condition', human: 'Validation humaine', merge: 'Fusion', loop: 'Boucle' };

/** Éditeur visuel : liste de nœuds typés + aperçu du graphe. Produit la même définition JSON que celle acceptée par l'API. */
@Component({
  selector: 'app-workflow-builder', imports: [FormsModule],
  template: `
  <div class="wb">
    <div class="toolbar">@for (t of types; track t) { <button type="button" class="btn ghost small" (click)="add(t)">+ {{ label(t) }}</button> }</div>
    <svg [attr.viewBox]="'0 0 ' + lay().w + ' ' + lay().h" class="graph" role="img" aria-label="Aperçu du graphe du workflow">
      @for (l of lay().links; track l.key) { <line [attr.x1]="l.x1" [attr.y1]="l.y1" [attr.x2]="l.x2" [attr.y2]="l.y2" stroke="var(--ink-soft)" /> }
      @for (w of lay().wells; track w.t.id) { <g [attr.transform]="'translate(' + w.x + ',' + w.y + ')'"><circle r="22" fill="var(--sheet)" stroke="var(--titration)" stroke-width="2"/>
        <text y="4" text-anchor="middle" font-size="9">{{ short(w.t.type) }}</text><text y="38" text-anchor="middle" font-size="10">{{ w.t.id }}</text></g> }
    </svg>
    @for (n of nodes(); track $index; let i = $index) {
      <div class="node panel">
        <header><strong>{{ label(n['type']) }}</strong>
          <span><button type="button" class="btn ghost small" (click)="move(i, -1)" [disabled]="i === 0" aria-label="Monter">↑</button>
          <button type="button" class="btn ghost small" (click)="move(i, 1)" [disabled]="i === nodes().length - 1" aria-label="Descendre">↓</button>
          <button type="button" class="btn ghost small" (click)="remove(i)">Retirer</button></span></header>
        <div class="row"><label class="field">Identifiant<input [ngModel]="n['id']" (ngModelChange)="set(i, 'id', $event)"></label>
          <label class="field">Titre<input [ngModel]="n['title']" (ngModelChange)="set(i, 'title', $event)"></label></div>
        @switch (n['type']) {
          @case ('agent') { <label class="field">Agent (rôle ou id du catalogue)<input [ngModel]="n['agent']" (ngModelChange)="set(i, 'agent', $event)"></label>
            <label class="field">Instruction (variables : {{ '{{' }}trigger.x{{ '}}' }}, {{ '{{' }}id_du_noeud.output{{ '}}' }})<textarea rows="2" [ngModel]="n['instruction']" (ngModelChange)="set(i, 'instruction', $event)"></textarea></label> }
          @case ('http') { <div class="row"><label class="field">Méthode<select [ngModel]="n['method'] || 'GET'" (ngModelChange)="set(i, 'method', $event)"><option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option></select></label>
            <label class="field grow">URL<input [ngModel]="n['url']" (ngModelChange)="set(i, 'url', $event)"></label></div>
            <label class="field">Corps (optionnel)<textarea rows="2" [ngModel]="n['body']" (ngModelChange)="set(i, 'body', $event)"></textarea></label> }
          @case ('code') { <label class="field">Code Python (exécuté dans la sandbox, sans réseau)<textarea rows="4" [ngModel]="n['code']" (ngModelChange)="set(i, 'code', $event)"></textarea></label> }
          @case ('transform') { <label class="field">Valeur<input [ngModel]="n['value']" (ngModelChange)="set(i, 'value', $event)"></label> }
          @case ('condition') { <label class="field">Expression (ex. {{ '{{' }}analyse.output{{ '}}' }} contient « urgent »)<input [ngModel]="n['expr']" (ngModelChange)="set(i, 'expr', $event)"></label> }
          @case ('human') { <label class="field">Message affiché à l’approbateur<input [ngModel]="n['message']" (ngModelChange)="set(i, 'message', $event)"></label> }
          @case ('loop') { <label class="field">Agent du corps<input [ngModel]="n['body']?.agent" (ngModelChange)="setBody(i, 'agent', $event)"></label>
            <label class="field">Instruction du corps<input [ngModel]="n['body']?.instruction" (ngModelChange)="setBody(i, 'instruction', $event)"></label>
            <div class="row"><label class="field grow">Jusqu’à (expression)<input [ngModel]="n['until']" (ngModelChange)="set(i, 'until', $event)"></label>
              <label class="field">Itérations max<input type="number" min="1" max="20" [ngModel]="n['max_iterations']" (ngModelChange)="set(i, 'max_iterations', +$event)"></label></div> }
        }
        @if (i > 0) { <fieldset><legend>Dépend de</legend>@for (p of nodes().slice(0, i); track $index) {
          <label class="dep"><input type="checkbox" [checked]="(n['depends_on'] || []).includes(p['id'])" (change)="toggleDep(i, p['id'])"> {{ p['id'] }}</label> }</fieldset> }
        <details><summary>Options (condition d’exécution, reprises, délai)</summary>
          <div class="row"><label class="field grow">Seulement si<input [ngModel]="n['when']" (ngModelChange)="set(i, 'when', $event)"></label>
            <label class="field">Reprises<input type="number" min="0" max="5" [ngModel]="n['retries'] || 0" (ngModelChange)="set(i, 'retries', +$event)"></label>
            <label class="field">Délai (s)<input type="number" min="1" [ngModel]="n['timeout_s']" (ngModelChange)="set(i, 'timeout_s', +$event)"></label>
            <label class="field">En cas d’erreur<select [ngModel]="n['on_error'] || 'fail'" (ngModelChange)="set(i, 'on_error', $event)"><option value="fail">Arrêter</option><option value="continue">Continuer</option></select></label></div></details>
      </div> } @empty { <p class="muted">Ajoutez un premier nœud avec les boutons ci-dessus.</p> }
  </div>`,
  styles: [`.toolbar { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: 1rem; } .graph { width: 100%; max-height: 14rem; background: var(--paper); border: 1px solid var(--rule); margin-bottom: 1rem; }
    .node { margin-bottom: .8rem; } header { display: flex; justify-content: space-between; margin-bottom: .6rem; } .row { display: flex; gap: .8rem; flex-wrap: wrap; } .grow { flex: 1; min-width: 12rem; } .dep { margin-right: 1rem; }
    textarea, input, select { width: 100%; }`],
})
export class WorkflowBuilder {
  definition = input.required<{ nodes?: N[] } | null>();
  changed = output<{ nodes: N[] }>();
  types = NODE_TYPES;
  nodes = signal<N[]>([]);
  lay = computed(() => layoutGraph(Object.fromEntries(this.nodes().filter(n => n['id']).map(n => [n['id'], { id: n['id'], type: n['type'], depends_on: n['depends_on'] ?? [] }]))));
  constructor() { queueMicrotask(() => this.nodes.set(structuredClone(this.definition()?.nodes ?? []))); }
  label = (t: string) => LABEL[t] ?? t;
  short = (t: string) => ({ agent: 'agent', http: 'http', code: 'py', transform: 'fx', condition: 'if', human: 'humain', merge: 'fusion', loop: 'boucle' } as any)[t] ?? t;
  private emit() { this.changed.emit({ nodes: this.nodes().map(n => Object.fromEntries(Object.entries(n).filter(([, v]) => v !== '' && v !== undefined && v !== null && !(Array.isArray(v) && !v.length)))) }); }
  private update(fn: (a: N[]) => N[]) { this.nodes.set(fn(structuredClone(this.nodes()))); this.emit(); }
  add(type: string) {
    const used = new Set(this.nodes().map(n => n['id'])); let k = 1; while (used.has(`${type}${k}`)) k++;
    const n: N = { id: `${type}${k}`, type };
    if (type === 'agent') n['agent'] = 'researcher';
    if (type === 'http') { n['method'] = 'GET'; n['url'] = 'https://'; }
    if (type === 'code') n['code'] = 'print("ok")';
    if (type === 'transform') n['value'] = '{{trigger.input}}';
    if (type === 'human') n['message'] = 'Valider la suite ?';
    if (type === 'loop') { n['body'] = { type: 'agent', agent: 'researcher' }; n['max_iterations'] = 3; }
    const prev = this.nodes().at(-1); if (prev && type !== 'merge') n['depends_on'] = [prev['id']];
    this.update(a => [...a, n]);
  }
  set(i: number, k: string, v: any) { this.update(a => { a[i][k] = v; return a; }); }
  setBody(i: number, k: string, v: any) { this.update(a => { a[i]['body'] = { ...(a[i]['body'] ?? { type: 'agent' }), [k]: v }; return a; }); }
  toggleDep(i: number, id: string) { this.update(a => { const d: string[] = a[i]['depends_on'] ?? []; a[i]['depends_on'] = d.includes(id) ? d.filter(x => x !== id) : [...d, id]; return a; }); }
  remove(i: number) { this.update(a => { const id = a[i]['id']; a.splice(i, 1); a.forEach(n => n['depends_on'] = (n['depends_on'] ?? []).filter((d: string) => d !== id)); return a; }); }
  move(i: number, d: number) { this.update(a => { [a[i], a[i + d]] = [a[i + d], a[i]]; return a; }); }
}
