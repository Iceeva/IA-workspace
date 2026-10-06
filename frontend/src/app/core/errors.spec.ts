import { HttpErrorResponse } from '@angular/common/http';
import { errorMessage } from './errors';

describe('errorMessage', () => {
  it('lit le format d’erreur de l’API', () => {
    expect(errorMessage(new HttpErrorResponse({ status: 404, error: { success: false, error: { code: 'X', message: 'Projet introuvable' } } }))).toBe('Projet introuvable');
  });
  it('retombe sur un message lisible par statut', () => {
    expect(errorMessage(new HttpErrorResponse({ status: 0 }))).toContain('serveur');
    expect(errorMessage(new HttpErrorResponse({ status: 429 }))).toContain('Trop');
  });
});
