import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { BridgeClient } from '../../core/bridge-client';
import { Toast } from '../../core/toast.service';

@Component({
  selector: 'app-local-models', imports: [FormsModule],
  template: `<div class="page-head"><h1>Modèles locaux</h1></div>
  <section class="panel"><h2>Connexion au Local Bridge</h2>
    <div class="bar"><label class="field">Adresse<input [(ngModel)]="url"></label>
      <label class="field">Jeton (fichier <code>~/.ai-workspace/bridge-token</code>)<input type="password" [(ngModel)]="token" autocomplete="off"></label>
      <button class="btn" (click)="connect()">Se connecter</button></div>
    @if (error()) { <p class="err">{{ error() }}</p> }
  </section>
  @if (hw(); as h) {
    <section class="panel" style="margin-top:1.5rem"><h2>Votre machine</h2>
      <p>{{ h.os }} {{ h.arch }} · {{ h.cpu }} ({{ h.threads }} threads) · RAM {{ (h.ram_total_mb / 1024).toFixed(0) }} Go ·
        VRAM {{ (h.vram_mb / 1024).toFixed(0) }} Go · disque libre {{ h.disk_free_gb }} Go</p>
      <p class="muted">GPU : @for (g of h.gpus; track g.name) { {{ g.name }} } @empty { aucun détecté } · accélération : {{ h.acceleration.join(', ') || '—' }}</p>
      <h3>Modèles recommandés</h3>
      <table class="tbl"><thead><tr><th>Modèle</th><th>Mémoire</th><th>Exécution</th></tr></thead><tbody>
        @for (m of reco(); track m.name) { <tr><td>{{ m.name }}</td><td>{{ m.memory_needed_gb }} Go</td><td><span class="fit" [class]="m.fit">{{ label(m.fit) }}</span></td></tr> }</tbody></table>
    </section>
    <section class="panel" style="margin-top:1.5rem"><h2>Fichiers GGUF</h2>
      @if (!gguf().length) { <p class="muted">Aucun fichier dans les dossiers autorisés (<code>--models-dir</code>).</p> }
      <table class="tbl"><thead><tr><th>Fichier</th><th>Architecture</th><th>Quantification</th><th>Contexte</th><th>Taille</th><th>Mémoire</th><th>Exécution</th></tr></thead><tbody>
        @for (g of gguf(); track g.path ?? g.file_name) { <tr><td>{{ g.file_name }}</td>
          @if (g.error) { <td colspan="6" class="err">{{ g.error }}</td> } @else {
          <td>{{ g.architecture }}</td><td>{{ g.quantization }}</td><td>{{ g.context_length }}</td><td>{{ g.size_gb }} Go</td><td>{{ g.memory_needed_gb }} Go</td>
          <td><span class="fit" [class]="g.fit">{{ label(g.fit) }}</span></td> }</tr> }</tbody></table>
      <p class="muted">Pour les attribuer à un agent : démarrez le fichier dans un runtime (llama.cpp, Ollama, LM Studio), puis choisissez-le dans « Fournisseurs » (un modèle par agent).</p>
    </section>
  }`,
  styles: [`.bar { display: flex; gap: 1rem; flex-wrap: wrap; align-items: end; } .err { color: #b91c1c; } .tbl { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); }
    .fit { padding: .1rem .5rem; border: 1px solid var(--rule); } .fit.gpu_full { border-color: #16a34a; } .fit.too_large { border-color: #b91c1c; }`],
})
export class LocalModels {
  private bridge = inject(BridgeClient); private api = inject(ApiService); private toast = inject(Toast);
  url = this.bridge.conf().url; token = this.bridge.conf().token;
  hw = signal<any>(null); gguf = signal<any[]>([]); reco = signal<any[]>([]); error = signal('');
  label = (f: string) => ({ gpu_full: 'GPU complet', gpu_partial: 'GPU + CPU', cpu: 'CPU', too_large: 'Trop volumineux' } as any)[f] ?? f;
  async connect() {
    this.error.set(''); this.bridge.save({ url: this.url, token: this.token });
    try {
      const hw = await this.bridge.hardware(); this.hw.set(hw);
      this.gguf.set(await this.bridge.gguf());
      this.api.post<any>('/api/hardware/recommend', { profile: hw }).subscribe(r => this.reco.set(r.data.models));
    } catch (e: any) { this.hw.set(null); this.error.set(e?.message ?? 'Bridge injoignable : est-il démarré (python -m aiw_bridge) ?'); this.toast.error('Connexion au bridge impossible'); }
  }
}
