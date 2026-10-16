import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
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
      <table class="tbl"><thead><tr><th>Fichier</th><th>Architecture</th><th>Quantification</th><th>Contexte</th><th>Taille</th><th>Mémoire</th><th>Exécution</th><th>Utiliser</th></tr></thead><tbody>
        @for (g of gguf(); track g.path ?? g.file_name) { <tr><td>{{ g.file_name }}</td>
          @if (g.error) { <td colspan="6" class="err">{{ g.error }}</td> } @else {
          <td>{{ g.architecture }}</td><td>{{ g.quantization }}</td><td>{{ g.context_length }}</td><td>{{ g.size_gb }} Go</td><td>{{ g.memory_needed_gb }} Go</td>
          <td><span class="fit" [class]="g.fit">{{ label(g.fit) }}</span></td>
          <td>@if (served(g); as sv) {
                <span class="muted">{{ sv.status === 'ready' ? 'servi' : sv.status === 'loading' ? 'chargement…' : sv.status }}</span>
                @if (sv.status === 'ready') { <button type="button" class="btn small" (click)="openAssign(g, sv)">Attribuer à un agent</button> }
                <button type="button" class="btn ghost small" (click)="stopServe(sv.id)">Arrêter</button>
                @if (sv.error) { <span class="err">{{ sv.error }}</span> }
              } @else { <button type="button" class="btn small" [disabled]="!serveOk()" (click)="serve(g)">Servir</button> }</td> }</tr> }</tbody></table>
      @if (!serveOk()) { <p class="muted">« Servir » demande <code>llama-server</code> (llama.cpp) sur cette machine : installez-le ou définissez <code>AIW_LLAMA_SERVER</code>.</p> }
      @if (assigning(); as a) {
        <div class="panel" role="dialog" aria-label="Attribuer un modèle à un agent"><h3>Attribuer {{ a.sv.model }} à un agent</h3>
          <label class="field">Rechercher un agent<input [(ngModel)]="agentQ" (input)="findAgents()" placeholder="Python, Security, Research…"></label>
          <div class="found">@for (x of agentHits(); track x.id) { <button type="button" class="btn ghost small" [class.on]="agentId === x.id" (click)="agentId = x.id">{{ x.name }}</button> }</div>
          <div class="row2"><label class="field">Contexte<input type="number" min="512" step="512" [(ngModel)]="a.ctx"></label>
            <label class="field"><span><input type="checkbox" [(ngModel)]="a.code"> Bon en code</span></label></div>
          <button type="button" class="btn" [disabled]="!agentId" (click)="confirmAssign()">Attribuer</button>
          <button type="button" class="btn ghost" (click)="assigning.set(null)">Annuler</button>
          <p class="muted">Le modèle est utilisé pour cet agent, quelle que soit la politique générale (sauf « un seul modèle »). Il ne répond que si votre bridge est connecté en mode pull (<code>--server</code>) et sert ce fichier.</p>
        </div>
      }
      <h3>Agents avec un modèle local</h3>
      <ul>@for (x of assigned(); track x.agent_id) { <li><strong>{{ x.agent_id }}</strong> → <code>{{ x.model }}</code> <button type="button" class="btn ghost small" (click)="unassign(x.agent_id)">Retirer</button></li> }
        @empty { <li class="muted">Aucun pour l’instant.</li> }</ul>
    </section>
  }`,
  styles: [`.bar { display: flex; gap: 1rem; flex-wrap: wrap; align-items: end; } .err { color: #b91c1c; } .tbl { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); }
    .found { display: flex; flex-wrap: wrap; gap: .4rem; margin: .5rem 0; } .found .on { border-color: var(--titration); } .row2 { display: flex; gap: 1rem; align-items: end; } .fit { padding: .1rem .5rem; border: 1px solid var(--rule); } .fit.gpu_full { border-color: #16a34a; } .fit.too_large { border-color: #b91c1c; }`],
})
export class LocalModels implements OnDestroy {
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
  servers = signal<any[]>([]); serveOk = signal(false); assigning = signal<{ g: any; sv: any; ctx: number; code: boolean } | null>(null);
  agentQ = ''; agentId = ''; agentHits = signal<any[]>([]); assigned = signal<any[]>([]); private poll?: ReturnType<typeof setInterval>;
  served = (g: any) => this.servers().find(x => x.file === g.file_name);
  async refreshServe() {
    try { const r = await this.bridge.serveStatus(); this.servers.set(r.servers); this.serveOk.set(r.available); } catch { /* bridge injoignable */ }
    const loading = this.servers().some(x => x.status === 'loading');
    if (loading && !this.poll) this.poll = setInterval(() => this.refreshServe(), 2000);
    if (!loading && this.poll) { clearInterval(this.poll); this.poll = undefined; }
  }
  async serve(g: any) {
    try { await this.bridge.serveStart(g.path, Math.min(g.context_length ?? 4096, 8192)); this.toast.info('Chargement du modèle…'); await this.refreshServe(); }
    catch (e: any) { this.toast.error(e?.message ?? 'Refusé'); }
  }
  async stopServe(id: string) { await this.bridge.serveStop(id); await this.refreshServe(); }
  openAssign(g: any, sv: any) { this.assigning.set({ g, sv, ctx: sv.ctx, code: (g.capabilities ?? []).includes('code') }); this.agentId = ''; this.agentQ = ''; this.agentHits.set([]); }
  findAgents() { if (this.agentQ.trim().length < 2) { this.agentHits.set([]); return; }
    this.api.get<any[]>('/api/catalog/agents', { q: this.agentQ, limit: 12 }).subscribe(r => this.agentHits.set(r.data)); }
  confirmAssign() {
    const a = this.assigning(); if (!a || !this.agentId) return;
    this.api.put('/api/local-model-assignments', { agent_id: this.agentId, runtime_id: a.sv.id, model: a.sv.model, caps: a.code ? ['chat', 'code'] : ['chat'], context: a.ctx })
      .subscribe({ next: () => { this.toast.info('Modèle attribué'); this.assigning.set(null); this.loadAssigned(); } });
  }
  loadAssigned() { this.api.get<any[]>('/api/local-model-assignments').subscribe({ next: r => this.assigned.set(r.data), error: () => {} }); }
  unassign(id: string) { this.api.delete(`/api/local-model-assignments/${id}`).subscribe(() => this.loadAssigned()); }
  ngOnDestroy() { if (this.poll) clearInterval(this.poll); }
  hw = signal<any>(null); gguf = signal<any[]>([]); reco = signal<any[]>([]); error = signal('');
  label = (f: string) => ({ gpu_full: 'GPU complet', gpu_partial: 'GPU + CPU', cpu: 'CPU', too_large: 'Trop volumineux' } as any)[f] ?? f;
  async connect() {
    this.error.set(''); this.bridge.save({ url: this.url, token: this.token });
    try {
      const hw = await this.bridge.hardware(); this.hw.set(hw);
      this.gguf.set(await this.bridge.gguf()); await this.refreshServe(); this.loadAssigned();
      this.bridge.runtimes().then(rt => this.api.post('/api/runtimes/report', { runtimes: rt }).subscribe({ error: () => {} })).catch(() => {});   // registre persistant (§19)
      this.api.post<any>('/api/hardware/recommend', { profile: hw }).subscribe(r => this.reco.set(r.data.models));
    } catch (e: any) { this.hw.set(null); this.error.set(e?.message ?? 'Bridge injoignable : est-il démarré (python -m aiw_bridge) ?'); this.toast.error('Connexion au bridge impossible'); }
  }
}
