import { Component, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-tasks', imports: [],
  template: `<div class="page-head"><h1>Tâches et messages</h1></div>
  <label class="field" style="max-width:30rem">Exécution
    <select (change)="select($any($event.target).value)"><option value="">Choisir une exécution</option>
      @for (e of execs(); track e.id) { <option [value]="e.id">{{ e.mission }} — {{ e.status }}</option> }</select></label>
  @if (tasks().length) {
    <h2>Tâches</h2>
    <div class="table-wrap"><table class="ledger"><thead><tr><th>Tâche</th><th>Agent</th><th>État</th><th>Tokens</th><th>Durée</th></tr></thead><tbody>
      @for (t of tasks(); track t.id) { <tr><td>{{ t.title }}</td><td>{{ t.agent }}</td><td><span class="status" [class]="t.status">{{ t.status }}</span></td>
        <td>{{ t.tokens }}</td><td>{{ t.duration_ms ? (t.duration_ms / 1000).toFixed(1) + ' s' : '—' }}</td></tr> }</tbody></table></div>
    <h2 style="margin-top:2rem">Bus de messages entre agents</h2>
    @for (m of messages(); track m.id) { <article class="panel msg"><strong>{{ m.sender }} → {{ m.recipient }}</strong><pre>{{ m.content }}</pre></article> }
    @empty { <p class="muted">Aucun message.</p> }
  }`,
  styles: [`.msg { margin-bottom: .8rem; } pre { white-space: pre-wrap; margin: .4rem 0 0; max-height: 10rem; overflow: auto; }`],
})
export class Tasks {
  private api = inject(ApiService);
  execs = signal<any[]>([]); tasks = signal<any[]>([]); messages = signal<any[]>([]);
  constructor() { this.api.get<any[]>('/api/executions').subscribe(r => this.execs.set(r.data)); }
  select(id: string) {
    if (!id) { this.tasks.set([]); return; }
    this.api.get<any[]>('/api/tasks', { execution_id: id }).subscribe(r => this.tasks.set(r.data));
    this.api.get<any[]>('/api/messages', { execution_id: id }).subscribe(r => this.messages.set(r.data));
  }
}
