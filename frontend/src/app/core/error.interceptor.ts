import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { errorMessage } from './errors';
import { Toast } from './toast.service';

/** Affiche une notification pour toute erreur sauf 401 (géré par l'intercepteur d'authentification). */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const toast = inject(Toast);
  return next(req).pipe(catchError((e: HttpErrorResponse) => {
    if (e.status !== 401 && !req.headers.has('X-Silent')) toast.error(errorMessage(e));
    return throwError(() => e);
  }));
};
