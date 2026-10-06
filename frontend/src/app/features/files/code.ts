import { NgTemplateOutlet } from '@angular/common';
import { AfterViewInit, Component, ElementRef, OnDestroy, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import loader from '@monaco-editor/loader';
import { ApiService } from '../../core/api.service';
import { ThemeService } from '../../core/theme.service';
import { Toast } from '../../core/toast.service';

const LANG: Record<string, string> = { ts: 'typescript', js: 'javascript', py: 'python', java: 'java', php: 'php', html: 'html', css: 'css',
  sql: 'sql', json: 'json', md: 'markdown', txt: 'plaintext', csv: 'plaintext' };
interface Node { name: string; path: string; id?: string; children?: Node[]; open?: boolean; }

function tree(files: { id: string; path: string }[]): Node[] {
  const root: Node = { name: '', path: '', children: [] };
  for (const f of files) { let cur = root; const parts = f.path.split('/');
    parts.forEach((p, i) => { const last = i === parts.length - 1; let n = cur.children!.find(c => c.name === p);
      if (!n) { n = { name: p, path: parts.slice(0, i + 1).join('/'), ...(last ? { id: f.id } : { children: [], open: true }) }; cur.children!.push(n); }
      cur = n; }); }
  return root.children!;
}

@Component({
  selector: 'app-code', imports: [FormsModule, NgTemplateOutlet],
  template: `<div class="page-head"><h1>Éditeur de code</h1>
    <select class="input" aria-label="Projet" [ngModel]="projectId" (ngModelChange)="projectId = $event; load()"><option value="">Choisir un projet</option>
      @for (p of projects(); track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select></div>
  <div class="ide">
    <aside aria-label="Arborescence"><ul>
      <ng-template #node let-nodes="nodes"><ng-container>@for (n of nodes; track n.path) {
        <li>@if (n.children) { <button class="dir" (click)="n.open = !n.open">{{ n.open ? '▾' : '▸' }} {{ n.name }}</button>
            @if (n.open) { <ul><ng-container *ngTemplateOutlet="node; context: { nodes: n.children }"/></ul> } }
          @else { <button class="file" [class.on]="n.id === current()?.id" (click)="open(n)">{{ n.name }}</button> }</li> }</ng-container></ng-template>
      <ng-container *ngTemplateOutlet="node; context: { nodes: nodes() }"/>
      @if (!nodes().length) { <li class="muted">Aucun fichier dans ce projet.</li> }</ul></aside>
    <section><div class="bar"><span>{{ current()?.path ?? 'Aucun fichier ouvert' }}</span>
      <button class="btn small" [disabled]="!current()" (click)="save()">Enregistrer</button></div>
      <div #host class="editor" role="region" aria-label="Éditeur Monaco"></div>
      @if (diff()) { <details open><summary>Modifications enregistrées (diff)</summary><pre>{{ diff() }}</pre></details> }</section>
  </div>`,
  styles: [`.ide { display: grid; grid-template-columns: 16rem 1fr; border: 1px solid var(--rule); background: var(--sheet); min-height: 32rem; } aside { border-right: 1px solid var(--rule); padding: .6rem; overflow: auto; }
    ul { list-style: none; padding-left: .8rem; margin: 0; } aside > ul { padding: 0; } button.dir, button.file { background: none; border: 0; cursor: pointer; padding: .15rem .3rem; text-align: left; width: 100%; }
    button.file.on { background: var(--bench); font-weight: 500; } .bar { display: flex; justify-content: space-between; align-items: center; padding: .4rem .8rem; border-bottom: 1px solid var(--rule); }
    .editor { height: 28rem; } pre { margin: 0; padding: .8rem; white-space: pre-wrap; max-height: 12rem; overflow: auto; } @media (max-width: 860px) { .ide { grid-template-columns: 1fr; } }`],
})
export class Code implements AfterViewInit, OnDestroy {
  private api = inject(ApiService); private toast = inject(Toast); private theme = inject(ThemeService);
  host = viewChild.required<ElementRef<HTMLElement>>('host');
  projects = signal<any[]>([]); nodes = signal<Node[]>([]); current = signal<Node | null>(null); diff = signal('');
  projectId = ''; private editor: any; private monaco: any;
  constructor() {
    this.api.get<any[]>('/api/projects').subscribe(r => this.projects.set(r.data));
    effect(() => { const m = this.theme.mode(); this.monaco?.editor.setTheme(this.isDark(m) ? 'vs-dark' : 'vs'); });
  }
  private isDark = (m: string) => m === 'dark' || (m === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  async ngAfterViewInit() { // Monaco est chargé à la demande depuis le CDN jsDelivr (voir docs/DEVELOPMENT.md)
    this.monaco = await loader.init();
    this.editor = this.monaco.editor.create(this.host().nativeElement, { value: '', language: 'plaintext', automaticLayout: true,
      minimap: { enabled: false }, theme: this.isDark(this.theme.mode()) ? 'vs-dark' : 'vs', fontSize: 13 });
    this.editor.addCommand(this.monaco.KeyMod.CtrlCmd | this.monaco.KeyCode.KeyS, () => this.save());
  }
  load() {
    this.current.set(null); this.diff.set('');
    if (!this.projectId) { this.nodes.set([]); return; }
    this.api.get<any[]>('/api/files', { project_id: this.projectId }).subscribe(r => this.nodes.set(tree(r.data)));
  }
  open(n: Node) {
    this.api.get<{ content: string }>(`/api/files/${n.id}/content`).subscribe(r => {
      this.current.set(n); this.diff.set('');
      const ext = n.name.split('.').pop() ?? '';
      const model = this.monaco.editor.createModel(r.data.content, LANG[ext] ?? 'plaintext');
      this.editor.getModel()?.dispose(); this.editor.setModel(model);
    });
  }
  save() {
    const c = this.current(); if (!c) return;
    this.api.put<{ diff: string }>(`/api/files/${c.id}/content`, { content: this.editor.getValue() })
      .subscribe(r => { this.diff.set(r.data.diff || 'Aucun changement.'); this.toast.info('Fichier enregistré'); });
  }
  ngOnDestroy() { this.editor?.dispose(); }
}
