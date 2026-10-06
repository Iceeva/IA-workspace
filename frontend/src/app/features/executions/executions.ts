import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-executions', imports: [ReactiveFormsModule, RouterLink, DatePipe],
  template: `
  <h1>Exécutions</h1>
  <form [formGroup]="form" (ngSubmit)="launch()" class="panel launch">
    <h2>Nouvelle mission</h2>
    <label class="field">Projet<select formControlName="project_id"><option value="" disabled>Choisir un projet</option>
      @for (p of projects(); track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select></label>
    <label class="field">Mission<textarea rows="4" formControlName="mission" placeholder="Ex. Une API de gestion immobilière avec Angular, FastAPI et PostgreSQL."></textarea></label>
    <button class="btn" [disabled]="form.invalid || busy()">Lancer l’équipe d’agents</button>
    @if (!projects().length) { <p class="muted">Aucun projet : <a routerLink="/projects">créez-en un</a>.</p> }
  </form>
  <h2>Historique</h2>
  <div class="table-wrap"><table class="ledger"><thead><tr><th>Mission</th><th>État</th><th>Tokens</th><th>Date</th></tr></thead><tbody>
    @for (e of items(); track e.id) { <tr><td><a [routerLink]="[e.id]">{{ e.mission }}</a></td><td><span class="status" [class]="e.status">{{ e.status }}</span></td>
      <td>{{ e.tokens }}</td><td>{{ e.created_at | date:'short' }}</td></tr> } @empty { <tr><td colspan="4" class="muted">Aucune exécution.</td></tr> }</tbody></table></div>`,
  styles: [`.launch { max-width: 40rem; margin: 1.5rem 0 2rem; }`],
})
export class Executions {
  private api = inject(ApiService); private fb = inject(FormBuilder); private router = inject(Router);
  projects = signal<{ id: string; name: string }[]>([]); items = signal<any[]>([]); busy = signal(false);
  form = this.fb.nonNullable.group({ project_id: ['', Validators.required], mission: ['', [Validators.required, Validators.minLength(5)]] });
  constructor() {
    this.api.get<any[]>('/api/projects').subscribe(r => this.projects.set(r.data));
    this.api.get<any[]>('/api/executions').subscribe(r => this.items.set(r.data));
  }
  launch() {
    this.busy.set(true);
    this.api.post<{ id: string }>('/api/executions', this.form.getRawValue()).subscribe({
      next: r => this.router.navigate(['/executions', r.data.id]), error: () => this.busy.set(false) });
  }
}
