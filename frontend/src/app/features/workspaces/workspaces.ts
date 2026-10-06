import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-workspaces', imports: [ReactiveFormsModule],
  template: `<div class="page-head"><h1>Espaces de travail</h1></div>
  <form [formGroup]="form" (ngSubmit)="create()" class="row"><label class="field">Nom<input formControlName="name"></label>
    <button class="btn" [disabled]="form.invalid">Créer</button></form>
  <table class="ledger"><thead><tr><th>Nom</th></tr></thead><tbody>
    @for (w of items(); track w.id) { <tr><td>{{ w.name }}</td></tr> } @empty { <tr><td class="muted">Aucun espace.</td></tr> }</tbody></table>`,
  styles: [`.row { display: flex; gap: 1rem; align-items: end; max-width: 32rem; margin-bottom: 1.5rem; } .row .field { flex: 1; margin: 0; }`],
})
export class Workspaces {
  private api = inject(ApiService); private fb = inject(FormBuilder); private toast = inject(Toast);
  items = signal<{ id: string; name: string }[]>([]);
  form = this.fb.nonNullable.group({ name: ['', Validators.required] });
  constructor() { this.load(); }
  load() { this.api.get<any[]>('/api/workspaces').subscribe(r => this.items.set(r.data)); }
  create() { this.api.post('/api/workspaces', this.form.getRawValue()).subscribe(() => { this.form.reset(); this.toast.info('Espace créé'); this.load(); }); }
}
