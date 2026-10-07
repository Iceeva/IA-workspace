# Plateforme multi-agents — modules ajoutés

Tout le cœur ci-dessous est en Python pur (testable sans base ni réseau). L'API et le worker s'y branchent.

| Module | Rôle | Fichiers |
|---|---|---|
| Catalogue | 1 096 définitions d'agents (sujets × rôles + spécialistes), index, recherche filtrée (Marketplace) | `app/catalog/` |
| Intention + sélection | Choisit peu d'agents pertinents (un par sujet/rôle) ; rien de pertinent → aucun agent | `app/routing/intent.py`, `selector.py` |
| Model Registry / Router | 3 modes : un modèle, un modèle par agent, routage automatique (qualité/vitesse/coût/contexte/confidentialité) | `app/routing/models.py` |
| Fallback | Chaîne de repli configurable, disjoncteur, événements `model.failed` / `model.fallback` | `app/routing/fallback.py` |
| Fournisseurs | 15 types OpenAI-compatibles + Anthropic, configurables (URL, clé chiffrée, modèles) | `app/llm/providers.py`, `app/api/ai_platform.py` |
| Runtimes | Registre, détection locale (Ollama, LM Studio, llama.cpp/LocalAI, vLLM), capacités | `app/runtimes/registry.py` |
| GGUF | Lecture de l'en-tête : architecture, quantification, contexte, mémoire estimée, compatibilité | `app/runtimes/gguf.py` |
| Matériel | CPU, RAM, GPU NVIDIA / Apple Silicon, disque ; recommandations | `app/runtimes/hardware.py` |
| Quantization Studio | Tailles, mémoire, vitesse relative, qualité indicative par format | `app/runtimes/quantization.py` |
| Benchmark | TTFT, tokens/s, démarrage à froid, stabilité, ressources, contrôle de qualité rapide | `app/runtimes/benchmark.py` |
| Outils + permissions | NONE/READ/WRITE/EXECUTE/ADMIN, validation humaine, audit ; filesystem, calculatrice, git (lecture), python (sandbox) | `app/tools/` |
| Chiffrement | AES-256-GCM, rotation de clés ; clés API jamais en clair | `app/core/crypto.py` |
| Stockage CAS | Hash par organisation, déduplication, compression (zstd/zlib) puis chiffrement, vérification d'intégrité | `app/storage/cas.py` |
| Budget | Plafond mensuel en dollars : bloquer ou demander confirmation (`?confirm_budget=true`) | `app/services/budget.py`, `quota.py` |
| Local Bridge | Passerelle locale sécurisée pour utiliser vos modèles depuis l'app web | `bridge/` |

## API (préfixe `/api`, en-têtes `Authorization` + `X-Organization-Id`)
`GET /catalog/agents?q=&category=&skill=&need=&modality=&sensitive=…` · `GET /catalog/categories` · `POST /catalog/select`
· `GET|POST /providers` · `PATCH|DELETE /providers/{id}` · `GET /providers/presets` · `GET|PUT /ai-settings`
· `POST /models/route` · `GET /tools` · `GET /quantization/compare` — écriture réservée au rôle ADMIN.

## Fournisseurs : exemple
```bash
curl -X POST $API/api/providers -H "Authorization: Bearer $T" -H "X-Organization-Id: $ORG" -H 'Content-Type: application/json' -d '{
  "kind":"mistral","name":"mistral-main","api_key":"…",
  "models":[{"id":"mistral-large-latest","caps":["chat","code"],"quality":0.9,"speed":0.5,"cost_in":2,"cost_out":6,"context":128000}]}'
```
Les prix, qualités et contextes sont **saisis par vous** : l'application n'embarque aucune grille tarifaire qui deviendrait fausse.
Sans fournisseur configuré dans l'interface, le worker retombe sur la configuration d'environnement historique (`LLM_PROVIDER`, `*_API_KEY`).

## Local Bridge (mode hybride)
```bash
PYTHONPATH=backend python -m aiw_bridge --origin https://votre-app.example --models-dir ~/models
```
Il affiche un **jeton d'appairage** (stocké dans `~/.ai-workspace/bridge-token`, droits 600). Routes : `/health`, `/hardware`,
`/runtimes`, `/models`, `/gguf`, `POST /gguf/inspect`, `POST /v1/chat/completions` (proxy, streaming compris).
Garde-fous : 127.0.0.1 uniquement, jeton, contrôle `Origin` et `Host`, proxy limité aux runtimes détectés, GGUF limité aux dossiers autorisés.

**Limite structurante :** le navigateur appelle le bridge directement. Le **worker serveur** ne peut pas, lui, joindre votre
`localhost`. Pour qu'une exécution orchestrée côté serveur utilise vos modèles locaux, il faut un mode « pull » (le bridge se
connecte au serveur et vient chercher les tâches) — voir `docs/ROADMAP.md`.

## Sécurité : à savoir
- `ENCRYPTION_KEY` en production (sinon clé dérivée de `JWT_SECRET`). Plusieurs clés séparées par des virgules = rotation.
- Les URL de fournisseurs sont validées (HTTPS, adresses publiques) ; `ALLOW_PRIVATE_PROVIDER_URLS=true` uniquement en auto-hébergement.
  Une protection DNS-rebinding complète demande un filtrage réseau en sortie côté infrastructure.
- La détection de runtimes locaux n'est volontairement PAS exposée par l'API cloud (SSRF) : elle vit dans le bridge.
