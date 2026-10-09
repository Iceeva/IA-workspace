import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-marketplace', imports: [FormsModule],
  template: `<div class="page-head"><h1>Marketplace d’agents</h1><span class="muted">{{ total() }} agents</span></div>
  <section class="panel" aria-label="Aperçu de la sélection">
    <h2>Quels agents pour ma mission ?</h2>
    <p class="muted">Aperçu de la sélection : seuls les agents pertinents seraient activés. Aucun modèle n’est appelé.</p>
    <label class="field">Mission<textarea rows="2" [(ngModel)]="mission" placeholder="Ex. : créer une API FastAPI avec PostgreSQL et la sécuriser"></textarea></label>
    <button class="btn" [disabled]="!mission.trim()" (click)="preview()">Voir la sélection</button>
    @if (sel(); as s) {
      <p class="muted">{{ s.agents.length }} retenus sur {{ s.catalog_size }} (candidats examinés : {{ s.considered }})</p>
      <ol>@for (a of s.agents; track a.id) { <li><strong>{{ a.name }}</strong> — {{ a.reason }} <span class="muted">({{ a.score }})</span></li> }</ol>
    }
  </section>
  <form class="filters" (ngSubmit)="search(true)">
    <input class="input" name="q" [(ngModel)]="q" placeholder="Rechercher (Python, sécurité, OCR…)" aria-label="Recherche">
    <select class="input" name="cat" [(ngModel)]="category" aria-label="Catégorie"><option value="">Toutes catégories</option>
      @for (c of cats(); track c.name) { <option [value]="c.name">{{ c.name }} ({{ c.count }})</option> }</select>
    <select class="input" name="mod" [(ngModel)]="modality" aria-label="Modalité"><option value="">Toutes modalités</option>
      @for (m of mods; track m) { <option [value]="m">{{ m }}</option> }</select>
    <select class="input" name="where" [(ngModel)]="where" aria-label="Exécution"><option value="">Local ou cloud</option><option value="local">Local seulement</option><option value="cloud">Cloud seulement</option></select>
    <button class="btn" type="submit">Filtrer</button>
  </form>
  <div class="cards">
    @for (a of items(); track a.id) {
      <article class="panel"><h3>{{ a.name }}</h3><p class="muted">{{ a.category }}{{ a.subcategory ? ' · ' + a.subcategory : '' }}</p>
        <p>{{ a.description }}</p>
        <p class="tags">@for (s of (a.skills || []).slice(0, 4); track s) { <span class="chip">{{ s }}</span> }
          @if (a.sensitive) { <span class="chip warn">sensible</span> }</p>
        <p class="muted">≈ {{ a.est_tokens }} tokens · {{ a.local_ok ? 'local' : '' }} {{ a.cloud_ok ? 'cloud' : '' }}</p>
      </article>
    } @empty { <p class="muted">Aucun agent ne correspond.</p> }
  </div>
  @if (items().length < total()) { <button class="btn ghost" (click)="search(false)">Charger plus</button> }`,
  styles: [`.filters { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1.5rem 0; } .filters input { flex: 1; min-width: 14rem; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
    .chip { display: inline-block; border: 1px solid var(--rule); padding: .1rem .5rem; margin: 0 .3rem .3rem 0; font-size: .8rem; } .chip.warn { border-color: #b45309; }`],
})
export class Marketplace {
  private api = inject(ApiService); private toast = inject(Toast);
  items = signal<any[]>([]); total = signal(0); cats = signal<any[]>([]); sel = signal<any>(null);
  q = ''; category = ''; modality = ''; where = ''; mission = '';
  mods = ['text', 'code', 'image', 'audio', 'video', 'document', 'data'];
  constructor() { this.api.get<any[]>('/api/catalog/categories').subscribe(r => this.cats.set(r.data)); this.search(true); }
  search(reset: boolean) {
    const offset = reset ? 0 : this.items().length;
    this.api.get<any[]>('/api/catalog/agents', { q: this.q, category: this.category, modality: this.modality, offset, limit: 30,
      local_only: this.where === 'local' ? 'true' : undefined, cloud_only: this.where === 'cloud' ? 'true' : undefined }).subscribe({
      next: (r: any) => { this.items.set(reset ? r.data : [...this.items(), ...r.data]); this.total.set(r.total ?? r.data.length); },
      error: () => this.toast.error('Recherche impossible') });
  }
  preview() { this.api.post<any>('/api/catalog/select', { mission: this.mission }).subscribe(r => this.sel.set(r.data)); }
}
