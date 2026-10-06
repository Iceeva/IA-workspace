import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-projects', imports: [ReactiveFormsModule, RouterLink],
  template: `<div class="page-head"><h1>Projets</h1></div>
  <form [formGroup]="form" (ngSubmit)="create()" class="panel form">
    <label class="field">Espace<select formControlName="workspace_id">
      <option value="" disabled>Choisir</option>@for (w of ws(); track w.id) { <option [value]="w.id">{{ w.name }}</option> }</select></label>
    <label class="field">Nom<input formControlName="name"></label>
    <label class="field">Description<textarea rows="2" formControlName="description"></textarea></label>
    @if (!ws().length) { <p class="muted">Créez d’abord un <a routerLink="/workspaces">espace de travail</a>.</p> }
    <button class="btn" [disabled]="form.invalid">Créer le projet</button></form>
  <div class="table-wrap"><table class="ledger"><thead><tr><th>Nom</th><th>Description</th></tr></thead><tbody>
    @for (p of items(); track p.id) { <tr><td>{{ p.name }}</td><td class="muted">{{ p.description }}</td></tr> } @empty { <tr><td class="muted" colspan="2">Aucun projet.</td></tr> }</tbody></table></div>`,
  styles: [`.form { max-width: 34rem; margin-bottom: 2rem; }`],
})
export class Projects {
  private api = inject(ApiService); private fb = inject(FormBuilder); private toast = inject(Toast);
  ws = signal<{ id: string; name: string }[]>([]); items = signal<any[]>([]);
  form = this.fb.nonNullable.group({ workspace_id: ['', Validators.required], name: ['', Validators.required], description: [''] });
  constructor() { this.api.get<any[]>('/api/workspaces').subscribe(r => this.ws.set(r.data)); this.load(); }
  load() { this.api.get<any[]>('/api/projects').subscribe(r => this.items.set(r.data)); }
  create() { this.api.post('/api/projects', this.form.getRawValue()).subscribe(() => { this.form.patchValue({ name: '', description: '' }); this.toast.info('Projet créé'); this.load(); }); }
}
