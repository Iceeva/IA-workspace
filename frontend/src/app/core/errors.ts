import { HttpErrorResponse } from '@angular/common/http';

const FALLBACK: Record<number, string> = {
  0: 'Impossible de joindre le serveur. Vérifiez votre connexion.', 401: 'Session expirée, reconnectez-vous.',
  403: 'Vous n’avez pas les droits nécessaires.', 404: 'Ressource introuvable.', 413: 'Fichier trop volumineux.',
  429: 'Trop de requêtes, patientez un instant.', 500: 'Erreur interne du serveur.', 503: 'Service momentanément indisponible.',
};

/** Message utilisateur lisible depuis le format {success:false, error:{code,message}}. */
export function errorMessage(e: unknown): string {
  if (e instanceof HttpErrorResponse) return e.error?.error?.message ?? FALLBACK[e.status] ?? `Erreur ${e.status}`;
  return e instanceof Error ? e.message : 'Une erreur est survenue.';
}
