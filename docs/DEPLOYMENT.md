# Déploiement

| Composant | Cible | Pourquoi |
|---|---|---|
| Frontend Angular | Vercel (`frontend/vercel.json`, sortie `dist/app/browser`) | statique, réécriture SPA |
| API FastAPI | Vercel Python (`backend/api/index.py`) **ou** conteneur (Fly.io, Render, Railway) | requêtes courtes uniquement |
| Worker | Conteneur longue durée (`worker/Dockerfile`) | orchestrations de plusieurs minutes, **incompatibles serverless** |
| PostgreSQL | Neon, Supabase, RDS | pool de connexions |
| Redis | Upstash, Redis Cloud | file de jobs, limiteur, révocation |
| Stockage | S3 / R2 / MinIO (`STORAGE_PROVIDER=s3`) | le disque serverless n'est pas persistant |

## Étapes
1. Créer PostgreSQL, Redis, un bucket. Renseigner les variables de `.env.example` (secrets JWT ≥ 32 octets aléatoires).
2. `cd backend && alembic upgrade head`.
3. Déployer API et worker avec les mêmes variables ; le worker a besoin du paquet `app` (voir `worker/Dockerfile`).
4. Frontend : définir l'URL de l'API (`window.__API_URL__` dans `index.html` ou variable de build), puis déployer sur Vercel. `CORS_ORIGINS` doit contenir l'URL Vercel.
5. Créer le premier administrateur : `UPDATE users SET is_platform_admin = true WHERE email = '…';`
6. Pour le suivi temps réel, le frontend interroge `GET /executions/{id}/events?after=` (compatible serverless). Le chat en flux SSE nécessite un hébergement qui autorise les réponses en streaming.
7. Sandbox : `SANDBOX_ENABLED=true` uniquement si le worker a accès à Docker.
