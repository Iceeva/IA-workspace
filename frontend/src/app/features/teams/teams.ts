import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-teams', imports: [FormsModule],
  template: `<div class="page-head"><h1>Équipes et agents personnalisés</h1></div>
  <div class="grid-2">
  <section class="panel"><h2>Équipes</h2>
    @for (t of teams(); track t.id) { <div class="row"><div><strong>{{ t.name }}</strong><br><span class="muted">{{ t.description }} · {{ t.agent_ids.length }} agents</span></div>
      <button class="btn ghost small" (click)="delTeam(t)">Supprimer</button></div> } @empty { <p class="muted">Aucune équipe.</p> }
    <h3>Nouvelle équipe</h3>
    <label class="field">Nom<input [(ngModel)]="team.name"></label>
    <label class="field">Description<input [(ngModel)]="team.description"></label>
    <label class="field">Rechercher un agent<input [(ngModel)]="q" (input)="find()" placeholder="Python, Security…"></label>
    <div class="found">@for (a of found(); track a.id) { <button type="button" class="btn ghost small" (click)="addMember(a)">+ {{ a.name }}</button> }</div>
    <p>@for (m of members(); track m.id) { <span class="chip">{{ m.name }} <button type="button" class="x" (click)="dropMember(m)" [attr.aria-label]="'Retirer ' + m.name">×</button></span> }</p>
    <button class="btn" [disabled]="!team.name || !members().length" (click)="createTeam()">Créer l’équipe</button>
  </section>
  <section class="panel"><h2>Agent Builder</h2>
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
  </section></div>`,
  styles: [`.row { display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--rule); padding: .6rem 0; }
    .chip { display: inline-block; border: 1px solid var(--rule); padding: .1rem .5rem; margin: 0 .3rem .3rem 0; } .x { border: 0; background: none; cursor: pointer; }
    .found { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .6rem; } .tool { display: inline-flex; gap: .4rem; margin: 0 1rem .4rem 0; align-items: center; } .check { display: block; margin: .6rem 0; }`],
})
export class Teams {
  private api = inject(ApiService); private toast = inject(Toast);
  teams = signal<any[]>([]); custom = signal<any[]>([]); found = signal<any[]>([]); members = signal<any[]>([]); toolNames = signal<string[]>([]);
  team = { name: '', description: '' }; q = '';
  ag: any = { agent_id: '', name: '', description: '', skills: '', keywords: '', instructions: '', tools: {} as Record<string, string>, sensitive: false };
  constructor() { this.load(); this.api.get<any[]>('/api/tools').subscribe(r => this.toolNames.set(r.data.map(t => t.name))); }
  load() { this.api.get<any[]>('/api/teams').subscribe(r => this.teams.set(r.data)); this.api.get<any[]>('/api/custom-agents').subscribe(r => this.custom.set(r.data)); }
  find() { if (this.q.trim().length < 2) { this.found.set([]); return; } this.api.get<any[]>('/api/catalog/agents', { q: this.q, limit: 8 }).subscribe(r => this.found.set(r.data)); }
  addMember(a: any) { if (!this.members().some(m => m.id === a.id)) this.members.set([...this.members(), a]); }
  dropMember(a: any) { this.members.set(this.members().filter(m => m.id !== a.id)); }
  private err = (e: any) => this.toast.error(e?.error?.error?.message ?? 'Opération impossible');
  createTeam() { this.api.post('/api/teams', { ...this.team, agent_ids: this.members().map(m => m.id) }).subscribe({
    next: () => { this.toast.info('Équipe créée'); this.members.set([]); this.team = { name: '', description: '' }; this.load(); }, error: this.err }); }
  delTeam(t: any) { if (confirm(`Supprimer l’équipe « ${t.name} » ?`)) this.api.delete(`/api/teams/${t.id}`).subscribe(() => this.load()); }
  createAgent() {
    const csv = (s: string) => String(s).split(',').map(x => x.trim()).filter(Boolean);
    const tools = Object.fromEntries(Object.entries(this.ag.tools as Record<string, string>).filter(([, v]) => v));
    this.api.post('/api/custom-agents', { agent_id: this.ag.agent_id, name: this.ag.name, description: this.ag.description, skills: csv(this.ag.skills),
      keywords: csv(this.ag.keywords), instructions: this.ag.instructions, tools, sensitive: this.ag.sensitive }).subscribe({
      next: () => { this.toast.info('Agent créé'); this.load(); }, error: this.err });
  }
  delAgent(a: any) { if (confirm(`Supprimer « ${a.name} » ?`)) this.api.delete(`/api/custom-agents/${a.id}`).subscribe(() => this.load()); }
}
