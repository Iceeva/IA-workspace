import { Component, computed, inject, OnInit } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { LucideAngularModule, LayoutDashboard, Boxes, FolderGit2, Bot, ListChecks, Activity, MessageSquare, Files,
  Code2, Brain, Workflow, Gauge, Settings, ShieldCheck, Sun, Moon, Monitor, LogOut, Zap, Store, Users, Plug, Cpu, Scale, HardDrive, Timer, Radar, Lock } from 'lucide-angular';
import { AuthService } from '../../core/auth.service';
import { ThemeService } from '../../core/theme.service';

@Component({
  selector: 'app-shell', imports: [RouterOutlet, RouterLink, RouterLinkActive, LucideAngularModule],
  template: `
  <div class="frame">
    <nav aria-label="Navigation principale">
      <a class="brand" routerLink="/">AI Workspace</a>
      @if (auth.me(); as me) {
        <label class="org">Organisation
          <select class="input" (change)="switchOrg($any($event.target).value)" [value]="auth.org()">
            @for (o of me.organizations; track o.id) { <option [value]="o.id" [selected]="o.id === auth.org()">{{ o.name }}</option> }
          </select>
        </label>
      }
      <ul>
        @for (l of links(); track l.path) {
          <li><a [routerLink]="l.path" routerLinkActive="on"><lucide-icon [img]="l.icon" [size]="16" aria-hidden="true" />{{ l.label }}</a></li>
        }
      </ul>
      <div class="foot">
        <div class="theme" role="group" aria-label="Thème">
          @for (t of themes; track t.mode) {
            <button type="button" [class.on]="theme.mode() === t.mode" (click)="theme.set(t.mode)" [attr.aria-label]="t.label" [attr.aria-pressed]="theme.mode() === t.mode">
              <lucide-icon [img]="t.icon" [size]="15" /></button>
          }
        </div>
        <button class="btn ghost small" (click)="logout()"><lucide-icon [img]="logoutIcon" [size]="14" /> Déconnexion</button>
      </div>
    </nav>
    <main><router-outlet /></main>
  </div>`,
  styles: [`
    .frame { display: grid; grid-template-columns: 15.5rem 1fr; min-height: 100vh; }
    nav { border-right: 1px solid var(--rule); padding: 1.4rem 1rem; display: flex; flex-direction: column; gap: 1.2rem; background: var(--sheet); position: sticky; top: 0; height: 100vh; overflow-y: auto; }
    .brand { font-family: var(--serif); font-size: 1.5rem; color: var(--ink); text-decoration: none; }
    .org { display: grid; gap: .2rem; font-size: .8rem; color: var(--ink-soft); } .org select { width: 100%; }
    ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .05rem; flex: 1; align-content: start; }
    li a { display: flex; align-items: center; gap: .6rem; padding: .35rem .6rem; color: var(--ink-soft); text-decoration: none; border-left: 3px solid transparent; }
    li a.on { color: var(--ink); border-left-color: var(--titration); font-weight: 500; }
    .foot { display: grid; gap: .6rem; }
    .theme { display: flex; border: 1px solid var(--rule); width: fit-content; }
    .theme button { background: none; border: 0; padding: .3rem .5rem; cursor: pointer; color: var(--ink-soft); }
    .theme button.on { background: var(--bench); color: var(--ink); }
    main { padding: 2rem min(4vw, 3.5rem); min-width: 0; }
    @media (max-width: 860px) { .frame { grid-template-columns: 1fr; } nav { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--rule); } ul { display: flex; flex-wrap: wrap; } }
  `],
})
export class Shell implements OnInit {
  auth = inject(AuthService); theme = inject(ThemeService); private router = inject(Router);
  logoutIcon = LogOut;
  themes = [{ mode: 'light' as const, label: 'Clair', icon: Sun }, { mode: 'system' as const, label: 'Système', icon: Monitor }, { mode: 'dark' as const, label: 'Sombre', icon: Moon }];
  private all = [
    { path: '/dashboard', label: 'Tableau de bord', icon: LayoutDashboard }, { path: '/workspaces', label: 'Espaces', icon: Boxes },
    { path: '/projects', label: 'Projets', icon: FolderGit2 }, { path: '/agents', label: 'Agents', icon: Bot },
    { path: '/tasks', label: 'Tâches', icon: ListChecks }, { path: '/executions', label: 'Exécutions', icon: Activity },
    { path: '/chat', label: 'Chat', icon: MessageSquare }, { path: '/files', label: 'Fichiers', icon: Files },
    { path: '/code', label: 'Code', icon: Code2 }, { path: '/memory', label: 'Mémoire', icon: Brain },
    { path: '/workflows', label: 'Workflows', icon: Workflow },
    { path: '/automations', label: 'Automatisations', icon: Zap }, { path: '/marketplace', label: 'Marketplace', icon: Store },
    { path: '/teams', label: 'Équipes', icon: Users }, { path: '/providers', label: 'Fournisseurs', icon: Plug },
    { path: '/runtimes', label: 'Runtimes locaux', icon: Cpu }, { path: '/quantization', label: 'Quantification', icon: Scale },
    { path: '/local-models', label: 'Modèles locaux', icon: HardDrive }, { path: '/benchmarks', label: 'Benchmarks', icon: Timer },
    { path: '/monitoring', label: 'Monitoring', icon: Radar }, { path: '/security', label: 'Sécurité', icon: Lock }, { path: '/usage', label: 'Usage', icon: Gauge },
    { path: '/settings', label: 'Paramètres', icon: Settings },
  ];
  links = computed(() => this.auth.me()?.is_platform_admin ? [...this.all, { path: '/admin', label: 'Administration', icon: ShieldCheck }] : this.all);
  ngOnInit() { if (!this.auth.me()) this.auth.loadMe().then(() => { if (!this.auth.org()) this.auth.switchOrg(this.auth.me()!.organizations[0]?.id); }); }
  switchOrg(id: string) { this.auth.switchOrg(id); this.router.navigateByUrl('/dashboard').then(() => location.reload()); }
  logout() { this.auth.logout(); this.router.navigateByUrl('/login'); }
}
