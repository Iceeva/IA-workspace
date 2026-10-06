import { Component, inject, signal, ElementRef, viewChild, effect } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Marked } from 'marked';
import hljs from 'highlight.js/lib/common';
import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { streamChat } from '../../core/chat-stream';
import { Toast } from '../../core/toast.service';

interface Msg { role: 'user' | 'assistant'; content: string; }
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
// Le rendu Markdown est ensuite assaini par Angular ([innerHTML]) : aucun HTML brut de l'utilisateur ne passe.
const md = new Marked({ renderer: { html: ({ text }) => esc(text),
  code: ({ text, lang }) => { const l = lang && hljs.getLanguage(lang) ? lang : null;
    return `<pre><code class="hljs">${l ? hljs.highlight(text, { language: l }).value : esc(text)}</code></pre>`; } } });

@Component({
  selector: 'app-chat', imports: [FormsModule],
  template: `
  <div class="page-head"><h1>Chat</h1>
    <div class="bar">
      <label class="sr-only" for="mode">Mode</label>
      <select id="mode" class="input" [(ngModel)]="mode"><option value="single">Agent seul</option><option value="team">Équipe d’agents</option></select>
      @if (mode === 'single') {
        <label class="sr-only" for="agent">Agent</label>
        <select id="agent" class="input" [(ngModel)]="agentId"><option value="">Assistant par défaut</option>@for (a of agents(); track a.id) { <option [value]="a.id">{{ a.name }}</option> }</select>
      }
      <label class="sr-only" for="proj">Projet</label>
      <select id="proj" class="input" [(ngModel)]="projectId"><option value="">{{ mode === 'team' ? 'Choisir un projet' : 'Sans projet' }}</option>@for (p of projects(); track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
    </div></div>
  <div class="log" role="log" aria-live="polite" #log>
    @for (m of msgs(); track $index; let i = $index) {
      <article class="m" [class.user]="m.role === 'user'">
        <header><strong>{{ m.role === 'user' ? 'Vous' : 'Assistant' }}</strong>
          <span class="acts">
            <button type="button" (click)="copy(m.content)">Copier</button>
            @if (m.role === 'user' && i === lastUser()) { <button type="button" (click)="edit(i)">Modifier</button> }
            @if (m.role === 'assistant' && i === msgs().length - 1 && !busy()) { <button type="button" (click)="retry()">Régénérer</button> }
          </span></header>
        <div class="prose" [innerHTML]="render(m.content)"></div>
      </article>
    } @empty { <p class="muted">Posez une question. En mode équipe, la mission est confiée à l’orchestrateur et vous suivez l’exécution.</p> }
  </div>
  <form (ngSubmit)="send()" class="composer">
    <textarea rows="3" [(ngModel)]="draft" name="draft" aria-label="Message" (keydown.control.enter)="send()" placeholder="Votre message (Ctrl+Entrée pour envoyer)"></textarea>
    <div class="row"><label class="btn ghost small">Joindre un fichier<input type="file" hidden (change)="attach($any($event.target).files[0])"></label>
      @if (busy()) { <button type="button" class="btn danger" (click)="stop()">Arrêter</button> } @else { <button class="btn" [disabled]="!draft.trim()">Envoyer</button> }</div>
  </form>`,
  styles: [`.bar { display: flex; gap: .5rem; flex-wrap: wrap; } .log { display: grid; gap: 1rem; margin-bottom: 1rem; max-width: 52rem; }
    .m { background: var(--sheet); border: 1px solid var(--rule); padding: .8rem 1rem; } .m.user { border-left: 3px solid var(--titration); }
    header { display: flex; justify-content: space-between; } .acts button { background: none; border: 0; color: var(--titration); cursor: pointer; font-size: .85rem; }
    .composer { max-width: 52rem; display: grid; gap: .6rem; } textarea { width: 100%; background: var(--sheet); border: 1px solid var(--rule); padding: .6rem; border-radius: 3px; } .row { display: flex; justify-content: space-between; }`],
})
export class Chat {
  private api = inject(ApiService); private auth = inject(AuthService); private router = inject(Router); private toast = inject(Toast);
  agents = signal<any[]>([]); projects = signal<any[]>([]); msgs = signal<Msg[]>([]); busy = signal(false);
  mode: 'single' | 'team' = 'single'; agentId = ''; projectId = ''; draft = '';
  private conv = crypto.randomUUID().replaceAll('-', ''); private ctrl?: AbortController;
  private log = viewChild<ElementRef<HTMLElement>>('log');
  constructor() {
    this.api.get<any[]>('/api/agents').subscribe(r => this.agents.set(r.data));
    this.api.get<any[]>('/api/projects').subscribe(r => this.projects.set(r.data));
    effect(() => { this.msgs(); queueMicrotask(() => this.log()?.nativeElement.lastElementChild?.scrollIntoView({ block: 'end' })); });
  }
  render = (s: string) => md.parse(s, { async: false }) as string;
  lastUser = () => this.msgs().map(m => m.role).lastIndexOf('user');
  copy(t: string) { navigator.clipboard.writeText(t).then(() => this.toast.info('Copié')); }
  edit(i: number) { this.draft = this.msgs()[i].content; this.msgs.update(m => m.slice(0, i)); }
  retry() { const i = this.lastUser(); if (i < 0) return; const t = this.msgs()[i].content; this.msgs.update(m => m.slice(0, i)); this.draft = t; this.send(); }
  stop() { this.ctrl?.abort(); }
  attach(file?: File) {
    if (!file) return;
    const f = new FormData(); f.append('file', file); f.append('path', `attachments/${file.name}`);
    if (this.projectId) f.append('project_id', this.projectId);
    this.api.upload<{ path: string }>('/api/files', f).subscribe(r => { this.draft += `\n[Fichier joint : ${r.data.path}]`; this.toast.info('Fichier ajouté et indexé'); });
  }
  async send() {
    const text = this.draft.trim(); if (!text || this.busy()) return;
    if (this.mode === 'team' && !this.projectId) { this.toast.error('Choisissez un projet pour le mode équipe.'); return; }
    this.draft = ''; this.msgs.update(m => [...m, { role: 'user', content: text }]); this.busy.set(true);
    this.ctrl = new AbortController();
    const body = { mode: this.mode, messages: this.msgs(), agent_id: this.agentId || null, project_id: this.projectId || null, conversation_id: this.conv };
    try {
      let started = false;
      for await (const ev of streamChat(body, this.auth.accessToken!, this.auth.org()!, this.ctrl.signal)) {
        if ((ev as any).execution_id) { this.router.navigate(['/executions', (ev as any).execution_id]); return; }
        if (ev.error) throw new Error(ev.error);
        if (ev.delta) { if (!started) { this.msgs.update(m => [...m, { role: 'assistant', content: '' }]); started = true; }
          this.msgs.update(m => m.map((x, i) => i === m.length - 1 ? { ...x, content: x.content + ev.delta } : x)); }
      }
    } catch (e: any) { if (e.name !== 'AbortError') this.toast.error(e.message); }
    finally { this.busy.set(false); }
  }
}
