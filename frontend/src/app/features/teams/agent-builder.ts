import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-agent-builder', imports: [FormsModule, RouterLink],
  template: `<div class="page-head"><h1>Agent Builder</h1></div>
  <div class="grid-2">
  <section class="panel"><h2>Mes agents</h2>
    @for (a of custom(); track a.id) { <div class="row"><div><strong>{{ a.name }}</strong> <span class="muted">{{ a.id }}</span></div>
      <button class="btn ghost small" (click)="delAgent(a)">Supprimer</button></div> } @empty { <p class="muted">Aucun agent personnalisé.</p> }
    <h3>Nouvel agent</h3>
    <label class="field">Identifiant (custom-xxx)<input [(ngModel)]="ag.agent_id" placeholder="custom-juriste"></label>
    <label class="field">Nom<input [(ngModel)]="ag.name"></label>
    <label class="field">Description<input [(ngModel)]="ag.description"></label>
    <label class="field">Compétences (virgules)<input [(ngModel)]="ag.skills"></label>
    <label class="field">Mots-clés de sélection (virgules)<input [(ngModel)]="ag.keywords"></label>
    <label class="field">Instructions (prompt système)<textarea rows="5" [(ngModel)]="ag.instructions"></textarea></label>
    <fieldset><legend>Outils autorisés</legend>
      @for (t of toolNames(); track t) { <label class="tool">{{ t }}
        <select [(ngModel)]="ag.tools[t]"><option value="">NONE</option><option value="READ">READ</option><option value="WRITE">WRITE</option><option value="EXECUTE">EXECUTE</option></select></label> }
    </fieldset>
    <label class="check"><input type="checkbox" [(ngModel)]="ag.sensitive"> Domaine sensible (traité en local si la politique l’exige)</label>
    <button class="btn" [disabled]="!ag.agent_id || !ag.name" (click)="createAgent()">Créer l’agent</button>
  </section>
  <p class="muted">Regroupez ensuite vos agents dans une <a routerLink="/teams">équipe</a>.</p></div>`,
  styles: [`.row { display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--rule); padding: .6rem 0; }
    .tool { display: inline-flex; gap: .4rem; margin: 0 1rem .4rem 0; align-items: center; } .check { display: block; margin: .6rem 0; }`],
})
export class AgentBuilder {
  private api = inject(ApiService); private toast = inject(Toast);
  custom = signal<any[]>([]); toolNames = signal<string[]>([]);
  ag: any = { agent_id: '', name: '', description: '', skills: '', keywords: '', instructions: '', tools: {} as Record<string, string>, sensitive: false };
  constructor() { this.load(); this.api.get<any[]>('/api/tools').subscribe(r => this.toolNames.set(r.data.map(t => t.name))); }
  load() { this.api.get<any[]>('/api/custom-agents').subscribe(r => this.custom.set(r.data)); }
  private err = (e: any) => this.toast.error(e?.error?.error?.message ?? 'Opération impossible');
  createAgent() {
    const csv = (s: string) => String(s).split(',').map(x => x.trim()).filter(Boolean);
    const tools = Object.fromEntries(Object.entries(this.ag.tools as Record<string, string>).filter(([, v]) => v));
    this.api.post('/api/custom-agents', { agent_id: this.ag.agent_id, name: this.ag.name, description: this.ag.description, skills: csv(this.ag.skills),
      keywords: csv(this.ag.keywords), instructions: this.ag.instructions, tools, sensitive: this.ag.sensitive }).subscribe({
      next: () => { this.toast.info('Agent créé'); this.load(); }, error: this.err });
  }
  delAgent(a: any) { if (confirm(`Supprimer « ${a.name} » ?`)) this.api.delete(`/api/custom-agents/${a.id}`).subscribe(() => this.load()); }
}
