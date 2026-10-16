import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-teams', imports: [FormsModule, RouterLink],
  template: `<div class="page-head"><h1>Équipes</h1></div>
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
  <section class="panel"><h2>Composer une équipe</h2><p class="muted">Une équipe regroupe des agents du catalogue ou vos agents personnalisés. L’orchestrateur la dirige selon la mission.</p>
    <p class="muted">Pour créer vos propres agents, ouvrez l’<a routerLink="/agent-builder">Agent Builder</a>.</p></section></div>`,
  styles: [`.row { display: flex; justify-content: space-between; gap: 1rem; border-bottom: 1px solid var(--rule); padding: .6rem 0; }
    .chip { display: inline-block; border: 1px solid var(--rule); padding: .1rem .5rem; margin: 0 .3rem .3rem 0; } .x { border: 0; background: none; cursor: pointer; }
    .found { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .6rem; }`],
})
export class Teams {
  private api = inject(ApiService); private toast = inject(Toast);
  teams = signal<any[]>([]); found = signal<any[]>([]); members = signal<any[]>([]);
  team = { name: '', description: '' }; q = '';
  constructor() { this.load(); }
  load() { this.api.get<any[]>('/api/teams').subscribe(r => this.teams.set(r.data)); }
  find() { if (this.q.trim().length < 2) { this.found.set([]); return; } this.api.get<any[]>('/api/catalog/agents', { q: this.q, limit: 8 }).subscribe(r => this.found.set(r.data)); }
  addMember(a: any) { if (!this.members().some(m => m.id === a.id)) this.members.set([...this.members(), a]); }
  dropMember(a: any) { this.members.set(this.members().filter(m => m.id !== a.id)); }
  private err = (e: any) => this.toast.error(e?.error?.error?.message ?? 'Opération impossible');
  createTeam() { this.api.post('/api/teams', { ...this.team, agent_ids: this.members().map(m => m.id) }).subscribe({
    next: () => { this.toast.info('Équipe créée'); this.members.set([]); this.team = { name: '', description: '' }; this.load(); }, error: this.err }); }
  delTeam(t: any) { if (confirm(`Supprimer l’équipe « ${t.name} » ?`)) this.api.delete(`/api/teams/${t.id}`).subscribe(() => this.load()); }
}
