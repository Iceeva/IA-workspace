import { Component, OnDestroy, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-bridge', imports: [DatePipe],
  template: `<div class="page-head"><h1>Runtimes et Local Bridge</h1></div>
  <section class="panel"><h2>État</h2>
    @if (st(); as s) {
      <p><span class="dot" [class.on]="s.online"></span> {{ s.online ? 'Bridge connecté' : 'Aucun bridge connecté' }}
        @if (s.online) { <span class="muted"> · version {{ s.version }}</span> }</p>
      @if (s.online) {
        <h3>Runtimes détectés</h3>
        <ul>@for (r of s.runtimes ?? []; track r) { <li>{{ r }}</li> } @empty { <li class="muted">Aucun</li> }</ul>
        <h3>Modèles locaux utilisables</h3>
        <ul>@for (m of s.models ?? []; track m) { <li><code>{{ m }}</code></li> } @empty { <li class="muted">Aucun</li> }</ul>
      }
    } @else { <p>Chargement…</p> }
  </section>
  <section class="panel" style="margin-top:1.5rem"><h2>Registre des runtimes</h2>
    <p class="muted">Dernier état connu des runtimes déclarés par vos bridges (mis à jour depuis « Modèles locaux »).</p>
    <table class="tbl"><thead><tr><th>Runtime</th><th>Type</th><th>Capacités</th><th>Modèles</th><th>Vu</th><th></th></tr></thead><tbody>
      @for (r of reg(); track r.id) { <tr [class.stale]="r.stale"><td>{{ r.name }}</td><td>{{ r.kind }}</td><td>{{ r.capabilities.join(', ') }}</td><td>{{ r.models.length }}</td>
        <td>{{ r.last_seen | date:'short' }} @if (r.stale || r.status === 'unreachable') { <span class="muted">· hors ligne</span> }</td>
        <td><button type="button" class="btn ghost small" (click)="forget(r.id)">Oublier</button></td></tr> }
      @empty { <tr><td colspan="6" class="muted">Aucun runtime enregistré.</td></tr> }</tbody></table>
  </section>
  <section class="panel" style="margin-top:1.5rem"><h2>Connecter votre ordinateur</h2>
    <p>Le Local Bridge s’installe sur votre machine. Il n’écoute que sur <code>127.0.0.1</code> et n’expose que les runtimes qu’il détecte
      (Ollama, llama.cpp, LM Studio, vLLM…) ou que vous déclarez (Phonon pour la voix, Sana pour l’image).</p>
    <p><strong>Mode pull (recommandé pour l’application en ligne)</strong> : le bridge se connecte <em>vers</em> le serveur, aucune ouverture de port.</p>
    <pre>pip install ./bridge
python -m aiw_bridge --server {{ origin }} --org &lt;ID_ORGANISATION&gt; --models-dir ~/models</pre>
    <p>Avec une clé API créée dans les paramètres (variable <code>AIW_API_KEY</code>). Ajoutez ensuite un fournisseur de type <code>bridge</code> dans « Fournisseurs ».</p>
  </section>`,
  styles: [`.dot { display: inline-block; width: .7rem; height: .7rem; border-radius: 50%; background: #9ca3af; margin-right: .4rem; } .dot.on { background: #16a34a; } pre { overflow: auto; background: var(--paper); padding: .8rem; }`],
})
export class BridgePage implements OnDestroy {
  private api = inject(ApiService);
  st = signal<any>(null); reg = signal<any[]>([]); origin = typeof location !== 'undefined' ? location.origin : '';
  private t = setInterval(() => this.load(), 5000);
  constructor() { this.load(); }
  load() { this.api.get<any>('/api/bridge/status').subscribe(r => this.st.set(r.data)); this.api.get<any[]>('/api/runtimes').subscribe(r => this.reg.set(r.data)); }
  forget(id: string) { this.api.delete(`/api/runtimes/${id}`).subscribe(() => this.load()); }
  ngOnDestroy() { clearInterval(this.t); }
}
