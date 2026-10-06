# Développement

```bash
cp .env.example .env && docker compose up --build        # stack complète
cd backend && pip install -r requirements.txt && pytest  # tests API (SQLite, Redis simulé)
cd frontend && npm install && npm test && npm run build
cd backend && python seed.py                             # compte DEMO (mot de passe affiché une fois)
```
Pour le stockage en local : `STORAGE_PROVIDER=local` (`STORAGE_LOCAL_DIR=./.storage`).
Conventions : routes minces (validation + droits), logique dans `services/` et `orchestration/`, modèles dans `models/`. Toute nouvelle ressource porte `organization_id` et un test d'isolation.
Migrations : modifier les modèles puis `alembic revision --autogenerate -m "..."`.
