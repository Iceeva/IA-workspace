# AI Workspace

Plateforme multi-agents : une mission en langage naturel est décomposée par un Planner en graphe de tâches,
exécutée en parallèle par couches (Researcher, Architect, Coder, Tester, Reviewer), avec boucle test → debug → re-test.

## Architecture
```
Angular (Vercel) → FastAPI → PostgreSQL
                      │
                      └→ Redis (file) → Worker Python → Orchestrator → Agents → LLM
```
L'API ne fait jamais tourner d'orchestration : `POST /api/executions` enregistre la mission et l'enfile dans Redis.
Le worker écrit des `execution_events` ; le frontend les lit par `GET /api/executions/{id}/events?after=<seq>`
(interrogation incrémentale, compatible serverless).

## Démarrage local
```bash
cp .env.example .env        # renseigner JWT_SECRET, JWT_REFRESH_SECRET et une clé LLM
docker compose up --build   # postgres, redis, backend (:8000), worker, frontend (:4200)
```
Première fois, générer la migration initiale (non fournie, voir Limitations) :
```bash
cd backend && alembic revision --autogenerate -m "initial" && alembic upgrade head
```
Tests : `cd backend && pytest`. Santé : `GET /health`. Docs OpenAPI : `/docs`.

## Choix techniques documentés
- Hachage scrypt (stdlib), JWT access (15 min) et refresh (14 j) signés avec deux secrets distincts.
- Isolation de tenant : chaque ressource porte `organization_id` ; le contexte (`X-Organization-Id`) est validé contre `organization_members` à chaque requête.
- Un workspace d'une autre organisation répond 404 (pas de fuite d'existence).
- Mitigation d'injection de prompt : sorties amont encadrées par `<context>` et déclarées comme données.
- Si le Planner renvoie un plan invalide, un plan par défaut est utilisé et l'événement `plan.fallback` est journalisé.

## Déploiement
Frontend → Vercel (`frontend/vercel.json` réécrit toutes les routes vers `index.html`).
Backend + worker → hébergeur de processus longs (Fly.io, Render, Railway). Le worker ne doit pas tourner en serverless.

## Fonctionnalités
Auth complète (inscription, connexion, refresh à rotation, logout avec révocation, mot de passe oublié, vérification e-mail, clés API),
multi-tenant avec RBAC, workspaces/projets, agents configurables, orchestrateur (plan, graphe, parallélisme, boucle test/debug, annulation),
workflows personnalisés (éditeur glisser-déposer), bus de messages inter-agents, mémoire (conversation/projet/agent), fichiers (validation,
stockage objet, extraction PDF/DOCX/XLSX/CSV/JSON/ZIP, indexation), Code Agent (écriture de fichiers + diffs, éditeur Monaco),
chat en streaming (Markdown, coloration, copie, régénération, modification, pièces jointes), usage et quotas, administration, audit, notifications.

## Documentation
`docs/API.md`, `AGENTS.md`, `SECURITY.md`, `DEPLOYMENT.md`, `DEVELOPMENT.md`, `ARCHITECTURE.md`.

## État de vérification (honnête)
- **Exécuté et réussi** : tests du moteur d'orchestration (8), des chemins/validation/extraction/sandbox/logs (17), de la mise en page du graphe (Node).
- **Écrit, jamais exécuté** (environnement sans réseau) : API FastAPI, worker, migrations, tests d'API (`pytest`), build Angular, tests Karma, Docker Compose.
  Les tests d'API couvrent l'isolation de tenant, le RBAC, les fichiers, la mémoire, les clés API et la réinitialisation de mot de passe.
- **Premier lancement** : attendez-vous à quelques erreurs de compilation Angular ou d'import à corriger (versions de `lucide-angular`, API Material).

## Limitations connues
- Le moteur n'émet pas les états QUEUED et WAITING (exécution par couches).
- Mémoire : recherche par mots-clés ; l'interface `Embedder` est prête mais aucun fournisseur d'embeddings n'est branché (pas de RAG vectoriel).
- Les agents n'ont pas d'outils appelables dynamiquement : le Coder émet des blocs de fichiers validés côté serveur ; la colonne `tools` est stockée mais non exploitée.
- Sandbox : nécessite Docker côté worker (`SANDBOX_ENABLED=true`), exécute uniquement `main.py`.
- Pas de 2FA, pas de verrouillage de compte, pas d'antivirus de fichiers. Jetons front en `sessionStorage`.
- Gestion des membres d'une organisation (invitations, changement de rôle) : non implémentée.
- Tailwind est chargé mais les écrans reposent surtout sur le CSS maison ; Material sert aux notifications.
- Monaco est chargé depuis le CDN jsDelivr (connexion requise).
- Le suivi d'exécution utilise l'interrogation (2 s), pas de SSE pour les événements.
