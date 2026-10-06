import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-files', imports: [FormsModule, DatePipe],
  template: `<div class="page-head"><h1>Fichiers</h1>
    <div class="bar"><select class="input" aria-label="Projet" [ngModel]="projectId" (ngModelChange)="projectId = $event; load()"><option value="">Tous les fichiers</option>
      @for (p of projects(); track p.id) { <option [value]="p.id">{{ p.name }}</option> }</select>
      <label class="btn">Téléverser<input type="file" hidden multiple (change)="upload($any($event.target).files)"></label></div></div>
  <p class="muted">PDF, DOCX, XLSX, CSV, JSON, TXT, ZIP, images (PNG/JPG/WEBP) et code (TS, JS, PY, JAVA, PHP, HTML, CSS, SQL). Les contenus texte sont découpés et indexés.</p>
  <div class="table-wrap"><table class="ledger"><thead><tr><th>Chemin</th><th>Taille</th><th>Indexé</th><th>Date</th><th></th></tr></thead><tbody>
    @for (f of items(); track f.id) { <tr><td>{{ f.path }}</td><td>{{ size(f.size) }}</td><td>{{ f.indexed ? 'oui' : 'non' }}</td><td>{{ f.created_at | date:'short' }}</td>
      <td><button class="btn ghost small" (click)="download(f)">Télécharger</button> <button class="btn danger small" (click)="remove(f)">Supprimer</button></td></tr> }
    @empty { <tr><td colspan="5" class="muted">Aucun fichier.</td></tr> }</tbody></table></div>`,
  styles: [`.bar { display: flex; gap: .6rem; }`],
})
export class Files {
  private api = inject(ApiService); private toast = inject(Toast);
  projects = signal<any[]>([]); items = signal<any[]>([]); projectId = '';
  constructor() { this.api.get<any[]>('/api/projects').subscribe(r => this.projects.set(r.data)); this.load(); }
  load() { this.api.get<any[]>('/api/files', { project_id: this.projectId }).subscribe(r => this.items.set(r.data)); }
  size = (n: number) => n > 1048576 ? (n / 1048576).toFixed(1) + ' Mo' : n > 1024 ? (n / 1024).toFixed(1) + ' Ko' : n + ' o';
  upload(files: FileList) {
    for (const file of Array.from(files)) {
      const f = new FormData(); f.append('file', file); if (this.projectId) f.append('project_id', this.projectId);
      this.api.upload('/api/files', f).subscribe(() => { this.toast.info(`${file.name} téléversé`); this.load(); });
    }
  }
  download(f: any) {
    this.api.blob(`/api/files/${f.id}/download`).subscribe(b => { const a = document.createElement('a');
      a.href = URL.createObjectURL(b); a.download = f.path.split('/').pop(); a.click(); URL.revokeObjectURL(a.href); });
  }
  remove(f: any) { if (confirm(`Supprimer « ${f.path} » ?`)) this.api.delete(`/api/files/${f.id}`).subscribe(() => this.load()); }
}
