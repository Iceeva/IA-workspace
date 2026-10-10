import { Component, ElementRef, computed, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { layoutGraph } from '../../core/graph-layout';
import { Pt, cardPositions, canLink, linkCurve } from './canvas-math';

type N = Record<string, any>;
export const NODE_TYPES = ['agent', 'http', 'code', 'transform', 'condition', 'human', 'merge', 'loop'] as const;
const LABEL: Record<string, string> = { agent: 'Agent', http: 'Appel HTTP', code: 'Code Python', transform: 'Transformation', condition: 'Condition', human: 'Validation humaine', merge: 'Fusion', loop: 'Boucle' };

/** Éditeur visuel : canvas glisser-déposer (positionner, relier) + formulaire par nœud. Produit la même définition JSON que celle acceptée par l'API. */
@Component({
  selector: 'app-workflow-builder', imports: [FormsModule],
  template: `
  <div class="wb">
    <div class="toolbar">@for (t of types; track t) { <button type="button" class="btn ghost small" (click)="add(t)">+ {{ label(t) }}</button> }</div>
    <p class="muted hint">Glissez les nœuds pour les placer ; tirez depuis le point de droite d’un nœud vers un autre nœud pour créer une dépendance ; cliquez sur un lien pour le supprimer.</p>
    <svg #cv [attr.viewBox]="'0 0 ' + W + ' ' + H" class="graph" role="application" aria-label="Canvas du workflow" (pointermove)="onMove($event)" (pointerup)="onUp($event)" (pointerleave)="onUp($event)">
      <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--ink-soft)"/></marker></defs>
      @for (l of links(); track l.key) {
        <g class="link" (click)="unlink(l.from, l.to)"><path [attr.d]="curve(l)" fill="none" stroke="var(--ink-soft)" stroke-width="2" marker-end="url(#arr)"/>
          <path [attr.d]="curve(l)" fill="none" stroke="transparent" stroke-width="14"><title>Supprimer le lien {{ l.from }} → {{ l.to }}</title></path></g> }
      @if (drag()?.kind === 'link') { <path [attr.d]="tempCurve()" fill="none" stroke="var(--titration)" stroke-width="2" stroke-dasharray="5 4"/> }
      @for (c of cards(); track c.id) {
        <g [attr.transform]="'translate(' + c.x + ',' + c.y + ')'" class="card" [class.sel]="sel() === c.id" [class.target]="hover() === c.id && drag()?.kind === 'link'">
          <rect [attr.width]="NW" [attr.height]="NH" rx="8" fill="var(--sheet)" stroke="var(--titration)" stroke-width="2" (pointerdown)="down($event, c.id, 'move')"/>
          <text x="10" y="19" font-size="10" class="kind" pointer-events="none">{{ label(c.type) }}</text>
          <text x="10" y="35" font-size="12" font-weight="600" pointer-events="none">{{ c.id }}</text>
          <circle cx="0" [attr.cy]="NH / 2" r="6" fill="var(--paper)" stroke="var(--ink-soft)"/>
          <circle [attr.cx]="NW" [attr.cy]="NH / 2" r="7" fill="var(--titration)" class="port" (pointerdown)="down($event, c.id, 'link')"><title>Tirer vers un autre nœud</title></circle>
        </g> }
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
        @if (nodes().length > 1) { <fieldset><legend>Dépend de</legend>@for (p of nodes(); track $index; let j = $index) { @if (j !== i) {
          <label class="dep"><input type="checkbox" [checked]="(n['depends_on'] || []).includes(p['id'])" [disabled]="!hasDep(n, p['id']) && !ok(p['id'], n['id'])" (change)="toggleDep(i, p['id'])"> {{ p['id'] }}</label> } }</fieldset> }
        <details><summary>Options (condition d’exécution, reprises, délai)</summary>
          <div class="row"><label class="field grow">Seulement si<input [ngModel]="n['when']" (ngModelChange)="set(i, 'when', $event)"></label>
            <label class="field">Reprises<input type="number" min="0" max="5" [ngModel]="n['retries'] || 0" (ngModelChange)="set(i, 'retries', +$event)"></label>
            <label class="field">Délai (s)<input type="number" min="1" [ngModel]="n['timeout_s']" (ngModelChange)="set(i, 'timeout_s', +$event)"></label>
            <label class="field">En cas d’erreur<select [ngModel]="n['on_error'] || 'fail'" (ngModelChange)="set(i, 'on_error', $event)"><option value="fail">Arrêter</option><option value="continue">Continuer</option></select></label></div></details>
      </div> } @empty { <p class="muted">Ajoutez un premier nœud avec les boutons ci-dessus.</p> }
  </div>`,
  styles: [`.toolbar { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: 1rem; } .hint { font-size: .85rem; margin: 0 0 .4rem; } .card rect { cursor: grab; } .card.sel rect { stroke-width: 3; } .card.target rect { stroke: var(--ink); } .port { cursor: crosshair; } .link { cursor: pointer; } .kind { fill: var(--ink-soft); }
    .graph { touch-action: none; width: 100%; max-height: 32rem; background: var(--paper); border: 1px solid var(--rule); margin-bottom: 1rem; }
    .node { margin-bottom: .8rem; } header { display: flex; justify-content: space-between; margin-bottom: .6rem; } .row { display: flex; gap: .8rem; flex-wrap: wrap; } .grow { flex: 1; min-width: 12rem; } .dep { margin-right: 1rem; }
    textarea, input, select { width: 100%; }`],
})
export class WorkflowBuilder {
  definition = input.required<{ nodes?: N[] } | null>();
  changed = output<{ nodes: N[] }>();
  types = NODE_TYPES;
  nodes = signal<N[]>([]);
  readonly W = 900; readonly H = 460; readonly NW = 150; readonly NH = 50;
  svg = viewChild<ElementRef<SVGSVGElement>>('cv');
  sel = signal<string | null>(null); hover = signal<string | null>(null);
  drag = signal<{ kind: 'move' | 'link'; id: string; dx: number; dy: number; at: Pt } | null>(null);
  lay = computed(() => layoutGraph(Object.fromEntries(this.nodes().filter(n => n['id']).map(n => [n['id'], { id: n['id'], type: n['type'], depends_on: n['depends_on'] ?? [] }]))));
  /** Positions : celles posées à la souris (`ui`) ou, à défaut, la disposition automatique. */
  cards = computed(() => cardPositions(this.nodes(), this.lay().wells, this.W - this.NW, this.H - this.NH));
  links = computed(() => {
    const pos = new Map(this.cards().map(c => [c.id, c]));
    return this.nodes().flatMap(n => (n['depends_on'] ?? []).filter((d: string) => pos.has(d) && pos.has(n['id'])).map((d: string) => ({ key: d + '>' + n['id'], from: d, to: n['id'],
      x1: pos.get(d)!.x + this.NW, y1: pos.get(d)!.y + this.NH / 2, x2: pos.get(n['id'])!.x, y2: pos.get(n['id'])!.y + this.NH / 2 })));
  });
  curve = (l: { x1: number; y1: number; x2: number; y2: number }) => linkCurve(l.x1, l.y1, l.x2, l.y2);
  tempCurve = () => { const d = this.drag(); const c = d && this.cards().find(k => k.id === d.id); return c && d ? linkCurve(c.x + this.NW, c.y + this.NH / 2, d.at.x, d.at.y) : ''; };
  private pt(e: PointerEvent): Pt {
    const el = this.svg()!.nativeElement, m = el.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse()); return { x: p.x, y: p.y };
  }
  down(e: PointerEvent, id: string, kind: 'move' | 'link') {
    e.preventDefault(); e.stopPropagation(); const at = this.pt(e), c = this.cards().find(k => k.id === id)!;
    this.sel.set(id); this.drag.set({ kind, id, dx: at.x - c.x, dy: at.y - c.y, at });
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }
  private nodeAt(p: Pt, except: string): string | null {
    return this.cards().find(c => c.id !== except && p.x >= c.x && p.x <= c.x + this.NW && p.y >= c.y && p.y <= c.y + this.NH)?.id ?? null;
  }
  onMove(e: PointerEvent) {
    const d = this.drag(); if (!d) return; const at = this.pt(e);
    if (d.kind === 'move') {
      const x = Math.max(0, Math.min(this.W - this.NW, at.x - d.dx)), y = Math.max(0, Math.min(this.H - this.NH, at.y - d.dy));
      this.nodes.update(a => a.map(n => n['id'] === d.id ? { ...n, ui: { x: Math.round(x), y: Math.round(y) } } : n));
    } else this.hover.set(this.nodeAt(at, d.id));
    this.drag.set({ ...d, at });
  }
  onUp(e: PointerEvent) {
    const d = this.drag(); if (!d) return;
    if (d.kind === 'link') { const to = this.nodeAt(this.pt(e), d.id); if (to && this.ok(d.id, to)) this.link(d.id, to); }
    this.drag.set(null); this.hover.set(null); this.emit();
  }
  hasDep = (n: N, id: string) => (n['depends_on'] ?? []).includes(id);
  /** Un lien from → to est permis s’il ne crée pas de cycle. */
  ok = (from: string, to: string) => canLink(this.nodes(), from, to);
  link(from: string, to: string) { this.update(a => { const n = a.find(x => x['id'] === to)!; const d: string[] = n['depends_on'] ?? []; if (!d.includes(from)) n['depends_on'] = [...d, from]; return a; }); }
  unlink(from: string, to: string) { this.update(a => { const n = a.find(x => x['id'] === to)!; n['depends_on'] = (n['depends_on'] ?? []).filter((x: string) => x !== from); return a; }); }
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
    if (type === 'code') { n['language'] = 'python'; n['code'] = 'print("ok")'; }
    if (type === 'transform') n['value'] = '{{trigger.input}}';
    if (type === 'human') n['message'] = 'Valider la suite ?';
    if (type === 'loop') { n['body'] = { type: 'agent', agent: 'researcher' }; n['max_iterations'] = 3; }
    const prev = this.nodes().at(-1); if (prev && type !== 'merge') n['depends_on'] = [prev['id']];
    n['ui'] = { x: 20 + (this.nodes().length % 5) * 170, y: 20 + Math.floor(this.nodes().length / 5) * 110 };
    this.update(a => [...a, n]);
  }
  set(i: number, k: string, v: any) { this.update(a => { a[i][k] = v; return a; }); }
  setBody(i: number, k: string, v: any) { this.update(a => { a[i]['body'] = { ...(a[i]['body'] ?? { type: 'agent' }), [k]: v }; return a; }); }
  toggleDep(i: number, id: string) { this.update(a => { const d: string[] = a[i]['depends_on'] ?? []; a[i]['depends_on'] = d.includes(id) ? d.filter(x => x !== id) : [...d, id]; return a; }); }
  remove(i: number) { this.update(a => { const id = a[i]['id']; a.splice(i, 1); if (this.sel() === id) this.sel.set(null); a.forEach(n => n['depends_on'] = (n['depends_on'] ?? []).filter((d: string) => d !== id)); return a; }); }
  move(i: number, d: number) { /* ordre de la liste uniquement */ this.update(a => { [a[i], a[i + d]] = [a[i + d], a[i]]; return a; }); }
}
