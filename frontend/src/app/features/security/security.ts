import { Component, inject, signal } from '@angular/core';
import { DatePipe, JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-security', imports: [DatePipe, JsonPipe, FormsModule],
  template: `<div class="page-head"><h1>Sécurité</h1></div>
  @if (o(); as o) {
    <div class="grid-2">
      <section class="panel"><h2>Fournisseurs</h2>
        <p>{{ o.providers.total }} configurés · {{ o.providers.with_key }} avec clé (chiffrée AES-256-GCM) · {{ o.providers.local }} locaux</p>
        @if (o.providers.cloud_without_key.length) { <p class="warn">Cloud sans clé : {{ o.providers.cloud_without_key.join(', ') }}</p> }</section>
      <section class="panel"><h2>Surfaces exposées</h2>
        <p>{{ o.api_keys }} clé(s) API active(s)</p><p>{{ o.public_webhooks }} webhook(s) public(s) actif(s) <span class="muted">(signés HMAC)</span></p></section>
      <section class="panel"><h2>Validations humaines (24 h)</h2>
        <p>Autorisées : {{ o.approvals_24h.approved }} · Refusées : {{ o.approvals_24h.denied }} · En attente : {{ o.approvals_24h.pending }}</p></section>
      <section class="panel"><h2>Agents personnalisés à privilèges</h2>
        @for (a of o.custom_agents_with_risky_tools; track a.id) { <p><strong>{{ a.id }}</strong> <span class="muted">{{ a.tools | json }}</span></p> } @empty { <p class="muted">Aucun agent avec outil en écriture ou exécution.</p> }</section>
    </div> }
  <section class="panel" style="margin-top:1.5rem"><h2>Journal d’audit</h2>
    <label class="field">Filtrer par action (préfixe)<input [(ngModel)]="filter" (change)="load()" placeholder="provider., file., trigger.…"></label>
    <table class="tbl"><thead><tr><th>Date</th><th>Action</th><th>Ressource</th><th>IP</th></tr></thead><tbody>
      @for (a of logs(); track a.id) { <tr><td>{{ a.created_at | date:'short' }}</td><td>{{ a.action }}</td><td>{{ a.resource }} {{ a.resource_id }}</td><td>{{ a.ip }}</td></tr> }</tbody></table>
  </section>`,
  styles: [`.warn { color: #b45309; } .tbl { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--rule); }`],
})
export class Security {
  private api = inject(ApiService);
  o = signal<any>(null); logs = signal<any[]>([]); filter = '';
  constructor() { this.api.get<any>('/api/security/overview').subscribe(r => this.o.set(r.data)); this.load(); }
  load() { this.api.get<any[]>('/api/security/audit', { action: this.filter, limit: 100 }).subscribe(r => this.logs.set(r.data)); }
}
