import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-memory', imports: [FormsModule, DatePipe],
  template: `<div class="page-head"><h1>Mémoire</h1></div>
  <p class="muted">Trois portées : <em>conversation</em>, <em>projet</em> et <em>agent</em>. Le projet est rappelé automatiquement aux nouvelles missions.</p>
  <form class="panel form" (ngSubmit)="load()">
    <label class="field">Portée<select [(ngModel)]="scope" name="scope"><option value="project">Projet</option><option value="agent">Agent</option><option value="conversation">Conversation</option></select></label>
    <label class="field">Identifiant ({{ scope === 'project' ? 'ID du projet' : scope === 'agent' ? 'rôle ou ID d’agent' : 'ID de conversation' }})<input [(ngModel)]="scopeId" name="sid" required></label>
    <label class="field">Recherche<input [(ngModel)]="q" name="q"></label>
    <button class="btn" [disabled]="!scopeId">Afficher</button></form>
  @if (loaded()) {
    <form class="panel form" (ngSubmit)="add()"><label class="field">Ajouter une note<textarea rows="3" [(ngModel)]="note" name="note"></textarea></label>
      <button class="btn" [disabled]="!note.trim()">Mémoriser</button></form>
    @for (m of items(); track m.id) { <article class="panel item"><pre>{{ m.content }}</pre><footer class="muted">{{ m.created_at | date:'short' }}
      <button class="btn ghost small" (click)="remove(m.id)">Oublier</button></footer></article> } @empty { <p class="muted">Rien en mémoire pour cette portée.</p> }
  }`,
  styles: [`.form { max-width: 34rem; margin-bottom: 1.2rem; } .item { margin-bottom: .8rem; max-width: 50rem; } pre { white-space: pre-wrap; margin: 0 0 .5rem; } footer { display: flex; justify-content: space-between; align-items: center; }`],
})
export class MemoryPage {
  private api = inject(ApiService); private toast = inject(Toast);
  scope = 'project'; scopeId = ''; q = ''; note = ''; items = signal<any[]>([]); loaded = signal(false);
  load() { this.api.get<any[]>('/api/memory', { scope: this.scope, scope_id: this.scopeId, q: this.q }).subscribe(r => { this.items.set(r.data); this.loaded.set(true); }); }
  add() { this.api.post('/api/memory', { scope: this.scope, scope_id: this.scopeId, content: this.note }).subscribe(() => { this.note = ''; this.toast.info('Mémorisé'); this.load(); }); }
  remove(id: string) { this.api.delete(`/api/memory/${id}`).subscribe(() => this.load()); }
}
