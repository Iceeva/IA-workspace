import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Toast } from '../../core/toast.service';
import { BridgeClient } from '../../core/bridge-client';
import { LABELS, formatResource, summarizeSamples, Sample } from '../../core/resources';

@Component({
  selector: 'app-benchmarks', imports: [FormsModule],
  template: `<div class="page-head"><h1>Benchmarks</h1></div>
  <p class="muted">Mesure la latence, le débit, la stabilité et un contrôle de qualité rapide. Les appels à un fournisseur cloud sont facturés.</p>
  <form class="panel bar" (ngSubmit)="run()">
    <label class="field">Fournisseur<select class="input" name="p" [(ngModel)]="provider" (ngModelChange)="model = ''">@for (p of providers(); track p.name) { <option [value]="p.name">{{ p.name }}</option> }</select></label>
    <label class="field">Modèle<select class="input" name="m" [(ngModel)]="model">@for (m of models(); track m.id) { <option [value]="m.id">{{ m.id }}</option> }</select></label>
    <label class="field">Essais<input type="number" min="1" max="8" name="r" [(ngModel)]="runs"></label>
    <label class="check"><input type="checkbox" name="q" [(ngModel)]="quality"> Contrôle de qualité</label>
    <button class="btn" type="submit" [disabled]="busy() || !provider || !model">{{ busy() ? 'Mesure en cours…' : 'Lancer' }}</button>
  </form>
  @if (rows().length) {
    <table class="tbl"><thead><tr><th>Modèle</th><th>Succès</th><th>1er token</th><th>Total</th><th>Tokens/s</th><th>Démarrage à froid</th><th>Écart-type</th><th>Qualité</th></tr></thead><tbody>
      @for (r of rows(); track $index) { <tr><td>{{ r.provider }}:{{ r.model }}</td><td>{{ (r.success_rate * 100).toFixed(0) }} %</td><td>{{ f(r.ttft_ms_median) }} ms</td><td>{{ f(r.total_ms_median) }} ms</td>
        <td>{{ r.tokens_per_s ?? '—' }}</td><td>{{ f(r.cold_start_ms) }} ms</td><td>{{ f(r.latency_stdev_ms) }} ms</td><td>{{ r.quality_pass_rate === null ? '—' : (r.quality_pass_rate * 100).toFixed(0) + ' %' }}</td></tr> }</tbody></table>
    @if (resKeys(rows()[0]).length) {
      <p class="muted">Ressources ({{ rows()[0].resources_scope === 'server' ? 'machine du serveur' : 'votre machine, via le bridge' }}) :
        @for (k of resKeys(rows()[0]); track k) { <span class="res">{{ LABELS[k] ?? k }} repos {{ fmt(k, rows()[0].baseline[k]) }} → pic {{ fmt(k, rows()[0].peak[k]) }} (+{{ fmt(k, rows()[0].delta[k] ?? 0) }})</span> }</p>
    } @else { <p class="muted">Ressources non mesurées : fournisseur distant et bridge local non joignable.</p> }
    @if (rows()[0].errors?.length) { <p class="muted">Erreurs : {{ rows()[0].errors.join(' ; ') }}</p> }
  }`,
  styles: [`.bar { display: flex; gap: 1rem; flex-wrap: wrap; align-items: end; margin: 1rem 0; } .tbl { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); } .check { margin-bottom: 1rem; } .res { margin-right: 1rem; }`],
})
export class Benchmarks {
  private api = inject(ApiService); private toast = inject(Toast); private bridge = inject(BridgeClient);
  LABELS = LABELS; fmt = formatResource;
  resKeys = (r: any): string[] => Object.keys(r?.peak ?? {});
  providers = signal<any[]>([]); rows = signal<any[]>([]); busy = signal(false);
  provider = ''; model = ''; runs = 3; quality = true;
  constructor() { this.api.get<any[]>('/api/providers').subscribe(r => { this.providers.set(r.data.filter(p => p.enabled)); this.provider = this.providers()[0]?.name ?? ''; }); }
  models = () => this.providers().find(p => p.name === this.provider)?.models ?? [];
  f = (v: number | null) => v === null || v === undefined ? '—' : Math.round(v);
  /** Pendant un benchmark que le serveur ne peut pas mesurer (fournisseur distant ou bridge), on échantillonne le bridge local. */
  private async sampleBridge(stop: () => boolean): Promise<Sample[]> {
    const out: Sample[] = [];
    try {
      out.push(await this.bridge.resources());
      while (!stop()) { await new Promise(r => setTimeout(r, 500)); out.push(await this.bridge.resources()); }
    } catch { /* bridge injoignable : pas de mesure */ }
    return out;
  }
  async run() {
    this.busy.set(true);
    let done = false;
    const sampling = this.sampleBridge(() => done);
    this.api.post<any>('/api/benchmarks', { provider: this.provider, model: this.model, runs: this.runs, quality: this.quality }).subscribe({
      next: async r => {
        done = true;
        const row = r.data;
        if (row.resources_scope === 'none') { const s = summarizeSamples(await sampling); if (Object.keys(s.peak).length) { Object.assign(row, s, { resources_scope: 'bridge' }); } }
        this.rows.set([row, ...this.rows()]); this.busy.set(false); },
      error: e => { done = true; this.busy.set(false); this.toast.error(e?.error?.error?.message ?? 'Benchmark impossible'); } });
  }
}
