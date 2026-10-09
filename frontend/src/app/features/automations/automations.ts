import { Component, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DatePipe, JsonPipe } from '@angular/common';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

const SAMPLE = `{
  "nodes": [
    {"id": "recherche", "type": "agent", "agent": "researcher", "prompt": "Résume : {{input.sujet}}"},
    {"id": "revue", "type": "human", "depends_on": ["recherche"], "message": "Valider le résumé ?"}
  ]
}`;

@Component({
  selector: 'app-automations', imports: [FormsModule, DatePipe, JsonPipe],
  template: `<div class="page-head"><h1>Automatisations</h1></div>
  @if (approvals().length) {
    <section class="panel warn" aria-label="Validations en attente"><h2>Validation humaine requise</h2>
      @for (a of approvals(); track a.id) { <div class="row"><div><strong>{{ a.tool }}.{{ a.action }}</strong> — agent « {{ a.agent }} »<br><span class="muted">{{ a.summary }}</span></div>
        <div><button class="btn small" (click)="decide(a, true)">Autoriser</button> <button class="btn ghost small" (click)="decide(a, false)">Refuser</button></div></div> }
    </section> }
  <div class="grid-2">
  <section class="panel"><h2>Workflows</h2>
    @for (w of workflows(); track w.id) { <div class="row"><div><strong>{{ w.name }}</strong><br><span class="muted">{{ w.definition.nodes.length }} étapes</span></div>
      <div><button class="btn small" (click)="run(w)">Lancer</button> <button class="btn ghost small" (click)="open(w)">Déclencheurs</button>
      <button class="btn ghost small" (click)="del(w)">Supprimer</button></div></div> } @empty { <p class="muted">Aucun workflow.</p> }
    <h3>Nouveau workflow</h3>
    <label class="field">Nom<input [(ngModel)]="nf.name"></label>
    <label class="field">Définition (JSON : séquences, parallélisme, conditions, boucles, validation humaine, HTTP, code…)<textarea rows="9" [(ngModel)]="nf.json" spellcheck="false"></textarea></label>
    <button class="btn ghost" (click)="validate()">Valider</button> <button class="btn" [disabled]="!nf.name" (click)="create()">Créer</button>
    @if (msg()) { <p class="muted">{{ msg() }}</p> }
  </section>
  <section class="panel"><h2>Déclencheurs {{ current() ? '— ' + current().name : '' }}</h2>
    @if (current()) {
      @for (t of triggers(); track t.id) { <div class="row"><div><strong>{{ t.type }}</strong> <span class="muted">{{ t.config | json }}</span>
        @if (t.hook_path) { <br><code>{{ t.hook_path }}</code> } @if (t.next_run_at) { <br><span class="muted">prochain : {{ t.next_run_at | date:'short' }}</span> }</div>
        <button class="btn ghost small" (click)="delTrigger(t)">Supprimer</button></div> } @empty { <p class="muted">Aucun déclencheur : lancement manuel uniquement.</p> }
      @if (secret()) { <p class="panel warn">Secret (affiché une seule fois) : <code>{{ secret() }}</code></p> }
      <h3>Ajouter</h3>
      <label class="field">Type<select class="input" [(ngModel)]="tr.type"><option value="schedule">Horaire (cron)</option><option value="webhook">Webhook</option>
        <option value="github">Événement GitHub</option><option value="event">Événement interne (fichier ajouté, agent…)</option></select></label>
      @if (tr.type === 'schedule') { <label class="field">Cron (5 champs)<input [(ngModel)]="tr.cron" placeholder="0 8 * * 1-5"></label> }
      @if (tr.type === 'event') { <label class="field">Événement<input [(ngModel)]="tr.event" placeholder="file_added"></label> }
      <button class="btn" (click)="addTrigger()">Ajouter le déclencheur</button>
    } @else { <p class="muted">Choisissez « Déclencheurs » sur un workflow.</p> }
  </section></div>
  <section class="panel" style="margin-top:1.5rem"><h2>Exécutions récentes</h2>
    @for (r of runs(); track r.id) { <div class="row"><div><span class="status">{{ r.status }}</span> {{ r.workflow_name || r.workflow_id }} <span class="muted">{{ r.created_at | date:'short' }}</span></div>
      @if (r.status === 'RUNNING' || r.status === 'PENDING') { <button class="btn ghost small" (click)="cancel(r)">Annuler</button> }</div> } @empty { <p class="muted">Aucune exécution.</p> }
  </section>`,
  styles: [`.row { display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--rule); padding: .6rem 0; align-items: center; }
    .warn { border-color: #b45309; margin-bottom: 1.5rem; } textarea { font-family: monospace; font-size: .85rem; width: 100%; } .status { font-weight: 600; margin-right: .5rem; }`],
})
export class Automations implements OnDestroy {
  private api = inject(ApiService); private toast = inject(Toast);
  workflows = signal<any[]>([]); runs = signal<any[]>([]); approvals = signal<any[]>([]); triggers = signal<any[]>([]);
  current = signal<any>(null); secret = signal(''); msg = signal('');
  nf = { name: '', json: SAMPLE }; tr: any = { type: 'schedule', cron: '0 8 * * *', event: 'file_added' };
  private timer = setInterval(() => this.poll(), 5000);
  constructor() { this.load(); this.poll(); }
  ngOnDestroy() { clearInterval(this.timer); }
  load() { this.api.get<any[]>('/api/workflows').subscribe(r => this.workflows.set(r.data)); }
  poll() { this.api.get<any[]>('/api/approvals').subscribe(r => this.approvals.set(r.data)); this.api.get<any[]>('/api/workflow-runs').subscribe(r => this.runs.set(r.data)); }
  private err = (e: any) => this.toast.error(e?.error?.error?.message ?? 'Opération impossible');
  private parse() { try { return JSON.parse(this.nf.json); } catch { this.msg.set('JSON invalide'); return null; } }
  validate() { const d = this.parse(); if (d) this.api.post('/api/workflows/validate', d).subscribe({ next: () => this.msg.set('Définition valide'), error: e => this.msg.set(e?.error?.error?.message ?? 'Invalide') }); }
  create() { const d = this.parse(); if (d) this.api.post('/api/workflows', { name: this.nf.name, definition: d }).subscribe({ next: () => { this.toast.info('Workflow créé'); this.load(); }, error: this.err }); }
  run(w: any) { this.api.post(`/api/workflows/${w.id}/run`, { payload: {} }).subscribe({ next: () => { this.toast.info('Workflow lancé'); this.poll(); }, error: this.err }); }
  del(w: any) { if (confirm(`Supprimer « ${w.name} » ?`)) this.api.delete(`/api/workflows/${w.id}`).subscribe(() => { this.load(); if (this.current()?.id === w.id) this.current.set(null); }); }
  open(w: any) { this.current.set(w); this.secret.set(''); this.loadTriggers(); }
  loadTriggers() { this.api.get<any[]>(`/api/workflows/${this.current().id}/triggers`).subscribe(r => this.triggers.set(r.data)); }
  addTrigger() {
    const config = this.tr.type === 'schedule' ? { cron: this.tr.cron } : this.tr.type === 'event' ? { event: this.tr.event } : {};
    this.api.post<any>(`/api/workflows/${this.current().id}/triggers`, { type: this.tr.type, config }).subscribe({
      next: r => { this.secret.set(r.data.secret ?? ''); this.loadTriggers(); }, error: this.err });
  }
  delTrigger(t: any) { this.api.delete(`/api/triggers/${t.id}`).subscribe(() => this.loadTriggers()); }
  cancel(r: any) { this.api.post(`/api/workflow-runs/${r.id}/cancel`, {}).subscribe({ next: () => this.poll(), error: this.err }); }
  decide(a: any, approved: boolean) { this.api.post(`/api/approvals/${a.id}/decision`, { approved }).subscribe({ next: () => this.poll(), error: this.err }); }
}
