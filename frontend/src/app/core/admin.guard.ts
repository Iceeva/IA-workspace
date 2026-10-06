import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

export const adminGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  if (!auth.me()) { try { await auth.loadMe(); } catch { /* géré par le guard d'auth */ } }
  return auth.me()?.is_platform_admin ? true : inject(Router).createUrlTree(['/dashboard']);
};
