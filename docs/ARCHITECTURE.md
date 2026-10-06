# Architecture
- `backend/app/orchestration/graph.py` : TaskGraph, tri topologique par couches, détection de cycles (testé).
- `backend/app/orchestration/engine.py` : Orchestrator (plan, exécution parallèle, boucle test/debug, annulation) (testé).
- `backend/app/llm/` : LLMProvider + OpenRouter/OpenAI/Anthropic/Ollama (erreur claire si clé absente).
- `backend/app/api/` : auth, ressources, dépendances de contexte d'organisation.
- `worker/main.py` : consommateur Redis, persistance des événements.
