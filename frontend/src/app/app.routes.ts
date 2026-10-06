import { Routes } from '@angular/router';
import { authGuard } from './core/auth.guard';
import { adminGuard } from './core/admin.guard';

const lazy = (f: () => Promise<any>) => ({ loadComponent: f });

export const routes: Routes = [
  { path: 'login', ...lazy(() => import('./features/auth/login').then(m => m.Login)) },
  { path: 'register', ...lazy(() => import('./features/auth/register').then(m => m.Register)) },
  { path: 'forgot-password', ...lazy(() => import('./features/auth/recovery').then(m => m.ForgotPassword)) },
  { path: 'reset-password', ...lazy(() => import('./features/auth/recovery').then(m => m.ResetPassword)) },
  { path: 'verify-email', ...lazy(() => import('./features/auth/recovery').then(m => m.VerifyEmail)) },
  { path: '', canActivate: [authGuard], loadComponent: () => import('./features/shell/shell').then(m => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      { path: 'dashboard', ...lazy(() => import('./features/dashboard/dashboard').then(m => m.Dashboard)) },
      { path: 'workspaces', ...lazy(() => import('./features/workspaces/workspaces').then(m => m.Workspaces)) },
      { path: 'projects', ...lazy(() => import('./features/projects/projects').then(m => m.Projects)) },
      { path: 'agents', ...lazy(() => import('./features/agents/agents').then(m => m.Agents)) },
      { path: 'tasks', ...lazy(() => import('./features/tasks/tasks').then(m => m.Tasks)) },
      { path: 'executions', ...lazy(() => import('./features/executions/executions').then(m => m.Executions)) },
      { path: 'executions/:id', ...lazy(() => import('./features/executions/execution-detail').then(m => m.ExecutionDetail)) },
      { path: 'chat', ...lazy(() => import('./features/chat/chat').then(m => m.Chat)) },
      { path: 'files', ...lazy(() => import('./features/files/files').then(m => m.Files)) },
      { path: 'code', ...lazy(() => import('./features/files/code').then(m => m.Code)) },
      { path: 'memory', ...lazy(() => import('./features/memory/memory').then(m => m.MemoryPage)) },
      { path: 'workflows', ...lazy(() => import('./features/workflows/workflows').then(m => m.Workflows)) },
      { path: 'usage', ...lazy(() => import('./features/usage/usage').then(m => m.Usage)) },
      { path: 'settings', ...lazy(() => import('./features/settings/settings').then(m => m.Settings)) },
      { path: 'admin', canActivate: [adminGuard], ...lazy(() => import('./features/admin/admin').then(m => m.Admin)) },
    ] },
  { path: '**', redirectTo: '' },
];
