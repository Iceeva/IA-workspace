import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-quantization', imports: [FormsModule],
  template: `<div class="page-head"><h1>Quantization Studio</h1></div>
  <p class="muted">La quantification est une compression <strong>avec perte</strong> des poids du modèle (à ne pas confondre avec la compression sans perte des fichiers).
    Les valeurs sont des estimations : confirmez par un benchmark sur votre machine.</p>
  <form class="panel bar" (ngSubmit)="go()">
    <label class="field">Paramètres (milliards)<input type="number" min="0.1" step="0.1" name="p" [(ngModel)]="params"></label>
    <label class="field">Contexte (tokens)<input type="number" min="128" step="128" name="c" [(ngModel)]="ctx"></label>
    <label class="field">VRAM (Go, optionnel)<input type="number" min="0" name="v" [(ngModel)]="vram"></label>
    <label class="field">RAM (Go, optionnel)<input type="number" min="0" name="r" [(ngModel)]="ram"></label>
    <button class="btn" type="submit">Comparer</button>
  </form>
  @if (rows().length) {
    @if (best()) { <p>Meilleur compromis pour votre machine : <strong>{{ best() }}</strong></p> }
    <table class="tbl"><thead><tr><th>Format</th><th>Taille</th><th>Mémoire</th><th>Vitesse (× FP16)</th><th>Qualité</th><th>GPU</th><th>RAM</th></tr></thead>
      <tbody>@for (r of rows(); track r.fmt) { <tr [class.best]="r.fmt === best()"><td>{{ r.fmt }}</td><td>{{ r.size_gb }} Go</td><td>{{ r.memory_gb }} Go</td>
        <td>{{ r.speed_x }}</td><td><div class="meter"><div [style.width.%]="r.quality * 100"></div></div></td><td>{{ mark(r.fits_gpu) }}</td><td>{{ mark(r.fits_ram) }}</td></tr> }</tbody></table>
  }`,
  styles: [`.bar { display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; margin: 1rem 0; } .tbl { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); }
    .best { background: color-mix(in srgb, var(--titration) 12%, transparent); } .meter { height: .5rem; width: 6rem; background: var(--rule); } .meter div { height: 100%; background: var(--titration); }`],
})
export class Quantization {
  private api = inject(ApiService); private toast = inject(Toast);
  params = 8; ctx = 4096; vram: number | null = null; ram: number | null = null;
  rows = signal<any[]>([]); best = signal<string | null>(null);
  constructor() { this.go(); }
  mark = (v: boolean | null) => v === null || v === undefined ? '—' : v ? '✓' : '✗';
  go() {
    this.api.get<any[]>('/api/quantization/compare', { params_b: this.params, ctx_len: this.ctx, vram_gb: this.vram ?? undefined, ram_gb: this.ram ?? undefined }).subscribe({
      next: (r: any) => { this.rows.set(r.data); this.best.set(r.best ?? null); }, error: () => this.toast.error('Comparaison impossible') });
  }
}
