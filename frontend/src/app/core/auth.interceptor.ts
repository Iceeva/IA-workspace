import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, from, switchMap, throwError } from 'rxjs';
import { AuthService } from './auth.service';

const withAuth = (req: any, a: AuthService) => req.clone({ setHeaders: {
  ...(a.accessToken ? { Authorization: `Bearer ${a.accessToken}` } : {}),
  ...(a.org() ? { 'X-Organization-Id': a.org()! } : {}) } });

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService), router = inject(Router);
  if (req.url.includes('/api/auth/') && !req.url.endsWith('/logout')) return next(req);
  return next(withAuth(req, auth)).pipe(catchError((e: HttpErrorResponse) => {
    if (e.status !== 401) return throwError(() => e);
    return from(auth.refresh()).pipe(switchMap(ok => {
      if (!ok) { router.navigateByUrl('/login'); return throwError(() => e); }
      return next(withAuth(req, auth));
    }));
  }));
};
