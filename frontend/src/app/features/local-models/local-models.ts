import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { BridgeClient } from '../../core/bridge-client';
import { Toast } from '../../core/toast.service';
import { GgufInfo, fit, launchCommands, memoryNeededGb, readGgufFile } from '../../core/gguf-header';

@Component({
  selector: 'app-local-models', imports: [FormsModule],
  template: `<div class="page-head"><h1>Modèles locaux</h1></div>
  <section class="panel"><h2>Connexion au Local Bridge</h2>
    <div class="bar"><label class="field">Adresse<input [(ngModel)]="url"></label>
      <label class="field">Jeton (fichier <code>~/.ai-workspace/bridge-token</code>)<input type="password" [(ngModel)]="token" autocomplete="off"></label>
      <button class="btn" (click)="connect()">Se connecter</button></div>
    @if (error()) { <p class="err">{{ error() }}</p> }
  </section>
  <section class="panel" style="margin-top:1.5rem"><h2>Analyser un fichier GGUF de votre ordinateur</h2>
    <p class="muted">Choisissez un fichier <code>.gguf</code> : seul son en-tête est lu dans votre navigateur, le fichier n’est jamais envoyé.</p>
    <label class="btn">Choisir un fichier .gguf<input type="file" accept=".gguf" hidden (change)="pick($any($event.target).files[0]); $any($event.target).value = ''"></label>
    @if (pickErr()) { <p class="err" role="alert">{{ pickErr() }}</p> }
    @if (picked(); as g) {
      <table class="tbl"><tbody>
        <tr><th>Nom</th><td>{{ g.name }} <span class="muted">({{ g.fileName }})</span></td></tr>
        <tr><th>Architecture</th><td>{{ g.architecture }} · {{ g.tensorCount }} tenseurs · GGUF v{{ g.version }}</td></tr>
        <tr><th>Quantification</th><td>{{ g.quantization }}</td></tr>
        <tr><th>Taille</th><td>{{ g.sizeGb.toFixed(2) }} Go</td></tr>
        <tr><th>Capacités</th><td>{{ g.capabilities.join(', ') }}</td></tr>
        <tr><th>Contexte</th><td>max {{ g.contextLength ?? '?' }} · <label>utilisé <input type="number" min="512" step="512" [ngModel]="ctx()" (ngModelChange)="ctx.set(+$event || 4096)" style="width:6rem"></label></td></tr>
        <tr><th>Mémoire nécessaire</th><td>{{ mem() }} Go
          @if (hw(); as h) { · <span class="fit" [class]="fitOf(h)">{{ label(fitOf(h)) }}</span> } @else { <span class="muted">· connectez le bridge pour l’ajustement à votre machine</span> }</td></tr>
        <tr><th>Runtimes compatibles</th><td>llama.cpp, Ollama, LM Studio, LocalAI</td></tr>
      </tbody></table>
      <h3>Le servir à un agent</h3>
      <p class="muted">Un agent utilise un modèle servi par un runtime. Lancez-le avec l’une de ces commandes (adaptez le chemin), puis ajoutez le runtime dans « Fournisseurs » et choisissez ce modèle pour l’agent voulu.</p>
      @for (c of cmds(); track c.runtime) { <p><strong>{{ c.runtime }}</strong> <button type="button" class="btn ghost small" (click)="copy(c.command)">Copier</button><br><code>{{ c.command }}</code></p> }
    }
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
  picked = signal<GgufInfo | null>(null); pickErr = signal(''); ctx = signal(4096);
  mem = computed(() => { const g = this.picked(); return g ? memoryNeededGb(g, this.ctx()) : 0; });
  cmds = computed(() => { const g = this.picked(); return g ? launchCommands(g, this.ctx()) : []; });
  fitOf = (h: any) => fit(h, this.mem());
  async pick(f?: File) {
    this.pickErr.set(''); if (!f) return;
    try { const g = await readGgufFile(f); this.picked.set(g); this.ctx.set(Math.min(g.contextLength ?? 4096, 8192)); }
    catch (e: any) { this.picked.set(null); this.pickErr.set(e?.message ?? 'Fichier illisible'); }
  }
  copy(t: string) { navigator.clipboard.writeText(t).then(() => this.toast.info('Copié')); }
  hw = signal<any>(null); gguf = signal<any[]>([]); reco = signal<any[]>([]); error = signal('');
  label = (f: string) => ({ gpu_full: 'GPU complet', gpu_partial: 'GPU + CPU', cpu: 'CPU', too_large: 'Trop volumineux' } as any)[f] ?? f;
  async connect() {
    this.error.set(''); this.bridge.save({ url: this.url, token: this.token });
    try {
      const hw = await this.bridge.hardware(); this.hw.set(hw);
      this.gguf.set(await this.bridge.gguf());
      this.bridge.runtimes().then(rt => this.api.post('/api/runtimes/report', { runtimes: rt }).subscribe({ error: () => {} })).catch(() => {});   // registre persistant (§19)
      this.api.post<any>('/api/hardware/recommend', { profile: hw }).subscribe(r => this.reco.set(r.data.models));
    } catch (e: any) { this.hw.set(null); this.error.set(e?.message ?? 'Bridge injoignable : est-il démarré (python -m aiw_bridge) ?'); this.toast.error('Connexion au bridge impossible'); }
  }
}
