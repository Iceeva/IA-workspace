import { Component, OnDestroy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { BridgeClient } from '../../core/bridge-client';
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
  <section class="panel" style="margin: 1.5rem 0"><h2>Quantifier un fichier local</h2>
    <p class="muted">Exécute <code>llama-quantize</code> (llama.cpp) sur votre machine via le Local Bridge ; le fichier ne quitte pas votre ordinateur. Le résultat est écrit à côté de l’original, sans jamais le remplacer.</p>
    <button type="button" class="btn ghost" (click)="refresh()">Actualiser</button>
    @if (qerr()) { <p class="err" role="alert">{{ qerr() }}</p> }
    @if (q(); as qs) {
      @if (!qs.available) { <p class="err">llama-quantize est introuvable sur cette machine : installez llama.cpp ou définissez <code>AIW_LLAMA_QUANTIZE</code>.</p> }
      <div class="bar"><label class="field">Fichier<select [(ngModel)]="file"><option value="">—</option>@for (g of ggufs(); track g.path) { <option [value]="g.path">{{ g.file_name }} ({{ g.quantization }}, {{ g.size_gb }} Go)</option> }</select></label>
        <label class="field">Vers<select [(ngModel)]="target">@for (t of qs.types; track t) { <option>{{ t }}</option> }</select></label>
        <label class="field"><span><input type="checkbox" [(ngModel)]="requant"> Requantifier (qualité réduite)</span></label>
        <button type="button" class="btn" [disabled]="!file || !qs.available" (click)="start()">Quantifier</button></div>
      @for (j of qs.jobs; track j.id) { <p>{{ j.file }} → <strong>{{ j.status }}</strong> · {{ j.elapsed_s }} s @if (j.output_mb) { · {{ j.output_mb }} Mo } @if (j.error) { <span class="err">{{ j.error }}</span> }
        @if (j.status === 'running') { <button type="button" class="btn ghost small" (click)="cancel(j.id)">Annuler</button> }</p> }
    }
  </section>
  @if (rows().length) {
    @if (best()) { <p>Meilleur compromis pour votre machine : <strong>{{ best() }}</strong></p> }
    <table class="tbl"><thead><tr><th>Format</th><th>Taille</th><th>Mémoire</th><th>Vitesse (× FP16)</th><th>Qualité</th><th>GPU</th><th>RAM</th></tr></thead>
      <tbody>@for (r of rows(); track r.fmt) { <tr [class.best]="r.fmt === best()"><td>{{ r.fmt }}</td><td>{{ r.size_gb }} Go</td><td>{{ r.memory_gb }} Go</td>
        <td>{{ r.speed_x }}</td><td><div class="meter"><div [style.width.%]="r.quality * 100"></div></div></td><td>{{ mark(r.fits_gpu) }}</td><td>{{ mark(r.fits_ram) }}</td></tr> }</tbody></table>
  }`,
  styles: [`.bar { display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; margin: 1rem 0; } .tbl { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); }
    .best { background: color-mix(in srgb, var(--titration) 12%, transparent); } .meter { height: .5rem; width: 6rem; background: var(--rule); } .meter div { height: 100%; background: var(--titration); }`],
})
export class Quantization implements OnDestroy {
  private api = inject(ApiService); private toast = inject(Toast); private bridge = inject(BridgeClient);
  q = signal<{ types: string[]; available: boolean; jobs: any[] } | null>(null); ggufs = signal<any[]>([]); qerr = signal(''); file = ''; target = 'Q4_K_M'; requant = false;
  private poll?: ReturnType<typeof setInterval>;
  async refresh() {
    this.qerr.set('');
    try { this.q.set(await this.bridge.quantizeStatus()); this.ggufs.set((await this.bridge.gguf()).filter(g => !g.error)); }
    catch (e: any) { this.q.set(null); this.qerr.set(e?.message ?? 'Bridge injoignable : connectez-le dans « Modèles locaux ».'); }
    const running = this.q()?.jobs.some(j => j.status === 'running');
    if (running && !this.poll) this.poll = setInterval(() => this.refresh(), 3000);
    if (!running && this.poll) { clearInterval(this.poll); this.poll = undefined; }
  }
  async start() { try { await this.bridge.quantizeStart(this.file, this.target, this.requant); this.toast.info('Quantification lancée'); await this.refresh(); } catch (e: any) { this.toast.error(e?.message ?? 'Refusé'); } }
  async cancel(id: string) { await this.bridge.quantizeCancel(id); await this.refresh(); }
  ngOnDestroy() { if (this.poll) clearInterval(this.poll); }
  params = 8; ctx = 4096; vram: number | null = null; ram: number | null = null;
  rows = signal<any[]>([]); best = signal<string | null>(null);
  constructor() { this.go(); }
  mark = (v: boolean | null) => v === null || v === undefined ? '—' : v ? '✓' : '✗';
  go() {
    this.api.get<any[]>('/api/quantization/compare', { params_b: this.params, ctx_len: this.ctx, vram_gb: this.vram ?? undefined, ram_gb: this.ram ?? undefined }).subscribe({
      next: (r: any) => { this.rows.set(r.data); this.best.set(r.best ?? null); }, error: () => this.toast.error('Comparaison impossible') });
  }
}
