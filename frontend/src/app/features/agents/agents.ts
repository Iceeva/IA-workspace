import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

const ROLES = ['planner', 'researcher', 'architect', 'coder', 'tester', 'debugger', 'reviewer'];

@Component({
  selector: 'app-agents', imports: [ReactiveFormsModule],
  template: `<div class="page-head"><h1>Agents</h1></div>
  <p class="muted">Un agent configuré remplace le modèle, le prompt et la température du rôle correspondant dans vos exécutions.</p>
  <div class="grid-2">
    <form [formGroup]="form" (ngSubmit)="save()" class="panel">
      <h2>{{ editing() ? 'Modifier l’agent' : 'Nouvel agent' }}</h2>
      <label class="field">Nom<input formControlName="name"></label>
      <label class="field">Rôle<select formControlName="role">@for (r of roles; track r) { <option [value]="r">{{ r }}</option> }</select></label>
      <label class="field">Modèle (vide = modèle par défaut)<input formControlName="model" placeholder="anthropic/claude-sonnet-4"></label>
      <label class="field">Température ({{ form.value.temperature }})<input type="range" min="0" max="1" step="0.05" formControlName="temperature"></label>
      <label class="field">Prompt système<textarea rows="6" formControlName="system_prompt"></textarea></label>
      <button class="btn" [disabled]="form.invalid">{{ editing() ? 'Enregistrer' : 'Créer' }}</button>
      @if (editing()) { <button type="button" class="btn ghost" (click)="reset()">Annuler</button> }
    </form>
    <div class="table-wrap"><table class="ledger"><thead><tr><th>Nom</th><th>Rôle</th><th>Modèle</th><th></th></tr></thead><tbody>
      @for (a of items(); track a.id) { <tr><td>{{ a.name }}</td><td>{{ a.role }}</td><td class="muted">{{ a.model }}</td>
        <td><button class="btn ghost small" (click)="edit(a)">Éditer</button> <button class="btn danger small" (click)="remove(a)">Supprimer</button></td></tr> }
      @empty { <tr><td colspan="4" class="muted">Aucun agent configuré : les rôles par défaut sont utilisés.</td></tr> }</tbody></table></div>
  </div>`,
})
export class Agents {
  private api = inject(ApiService); private fb = inject(FormBuilder); private toast = inject(Toast);
  roles = ROLES; items = signal<any[]>([]); editing = signal<string | null>(null);
  form = this.fb.nonNullable.group({ name: ['', Validators.required], role: ['coder', Validators.required], model: [''],
    temperature: [0.2], system_prompt: ['', Validators.required] });
  constructor() { this.load(); }
  load() { this.api.get<any[]>('/api/agents').subscribe(r => this.items.set(r.data)); }
  edit(a: any) { this.editing.set(a.id); this.form.patchValue({ name: a.name, role: a.role, model: a.model, temperature: a.temperature, system_prompt: '' }); }
  reset() { this.editing.set(null); this.form.reset({ role: 'coder', temperature: 0.2 }); }
  save() {
    const body = { ...this.form.getRawValue(), model: this.form.value.model || null, tools: [] }, id = this.editing();
    (id ? this.api.put(`/api/agents/${id}`, body) : this.api.post('/api/agents', body)).subscribe(() => { this.toast.info('Agent enregistré'); this.reset(); this.load(); });
  }
  remove(a: any) { if (confirm(`Supprimer l’agent « ${a.name} » ?`)) this.api.delete(`/api/agents/${a.id}`).subscribe(() => this.load()); }
}
