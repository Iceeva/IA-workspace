# API

Base : `/api`. Authentification : `Authorization: Bearer <access>` ou `X-API-Key: aiw_…`.
Les routes métier exigent `X-Organization-Id` (appartenance vérifiée en base). Docs interactives : `/docs`.

Succès : `{"success": true, "data": …}` — Erreur : `{"success": false, "error": {"code", "message"}}`.
Codes usuels : `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `RESOURCE_NOT_FOUND` 404, `VALIDATION_ERROR` 422,
`QUOTA_EXCEEDED` 402, `RATE_LIMITED` 429, `LLM_NOT_CONFIGURED` / `STORAGE_NOT_CONFIGURED` 503.

| Domaine | Endpoints | Rôle minimum |
|---|---|---|
| Auth | `POST /auth/register, login, refresh, logout, forgot-password, reset-password, verify-email, resend-verification` · `GET /me` | — |
| Organisations | `GET/POST /organizations` | connecté |
| Workspaces / Projets | `GET/POST /workspaces` (ADMIN) · `GET/POST /projects` (MEMBER) | VIEWER lecture |
| Agents | `GET/POST /agents`, `PUT/DELETE /agents/{id}` | MEMBER (DELETE: ADMIN) |
| Exécutions | `POST /executions` (202), `GET /executions/{id}`, `GET /executions/{id}/events?after=<seq>`, `POST /executions/{id}/cancel` | MEMBER |
| Tâches / Messages | `GET /tasks?execution_id=`, `GET /messages?execution_id=` | VIEWER |
| Fichiers | `POST /files` (multipart), `GET /files?project_id=`, `GET /files/{id}/download`, `GET/PUT /files/{id}/content`, `DELETE /files/{id}` | MEMBER pour écrire |
| Mémoire | `GET /memory?scope=&scope_id=&q=`, `POST /memory`, `DELETE /memory/{id}` (scope : conversation, project, agent) | MEMBER pour écrire |
| Chat | `POST /chat` — `mode: single` → flux SSE (`{"delta"}`…`{"done":true}`) ; `mode: team` → `{execution_id}` | MEMBER |
| Usage | `GET /usage`, `GET /dashboard` | VIEWER |
| Clés API | `GET/POST/DELETE /api-keys` (la clé n'est affichée qu'à la création) | MEMBER |
| Notifications | `GET /notifications`, `POST /notifications/{id}/read` | connecté |
| Admin plateforme | `GET /admin/users, organizations, workspaces, agents, executions, usage, audit, providers, models` · `PUT /admin/providers/{name}`, `POST/PUT /admin/models`, `PUT /admin/organizations/{id}/limits`, `POST /admin/users/{id}/disable` | `is_platform_admin` |

Événements d'exécution (`kind`) : `plan.started`, `plan.created`, `plan.fallback`, `graph`, `task.started|completed|failed|debugging|review_required`, `agent.message`, `file.written` (avec diff), `file.rejected`, `sandbox.result`, `execution.completed|failed`.
