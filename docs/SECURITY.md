# Sécurité

- **Mots de passe** : scrypt (stdlib), sel aléatoire, comparaison à temps constant.
- **Jetons** : JWT access 15 min / refresh 14 j, secrets distincts, `jti` unique. Refresh à **rotation** ; logout et refresh révoquent les `jti` dans Redis. Si Redis est indisponible, la révocation est ignorée et un avertissement est journalisé.
- **Réinitialisation / vérification e-mail** : jetons à usage ciblé ; le lien de réinitialisation embarque une empreinte du mot de passe actuel, donc inutilisable une seconde fois. Réponse identique que le compte existe ou non.
- **Isolation de tenant** : `organization_id` sur chaque ressource, filtré dans chaque requête ; l'en-tête d'organisation est validé contre `organization_members` (404 sinon). Les clés étrangères entrantes (workspace, projet) sont revérifiées.
- **RBAC** : OWNER > ADMIN > MEMBER > VIEWER, `Ctx.require`.
- **Clés API** : stockées sous forme SHA-256, affichées une seule fois.
- **Fichiers** : liste blanche d'extensions, taille max, vérification des signatures, UTF-8 pour le texte, chemins virtuels normalisés (`safe_path` : pas de `..`, absolu, NUL, antislash), zip jamais extrait sur disque (plafonds d'entrées et de taille), téléchargement forcé avec `nosniff`.
- **Code utilisateur** : jamais dans l'API ; sandbox Docker (`--network none`, `--read-only`, CPU/RAM/PID limités, `--cap-drop ALL`, utilisateur non-root, délai strict), activable via `SANDBOX_ENABLED=true` côté worker.
- **En-têtes** : CSP, HSTS, nosniff, X-Frame-Options, `no-store`. CORS restreint à `CORS_ORIGINS`.
- **Limitation de débit** : Redis, par IP, sur `/api/auth/*`.
- **Logs** : JSON structurés ; JWT, clés `sk-…` et paires password/token/secret sont masqués.
- **Audit** : table `audit_logs` (inscription, connexion, exécutions, fichiers, clés API, actions admin).
- **Injection SQL** : SQLAlchemy paramétré uniquement. **XSS** : Angular échappe par défaut ; aucune injection de HTML brut côté frontend.

## Limites connues
Pas de 2FA, pas de verrouillage de compte après N échecs (seulement le limiteur par IP), pas de scan antivirus des fichiers, jetons front stockés en `sessionStorage` (vulnérables à une XSS ; cookies httpOnly à envisager).
