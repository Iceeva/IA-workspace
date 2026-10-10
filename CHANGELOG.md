# Journal des changements

## [Non publié] — plateforme multi-agents
- Catalogue de 1 096 agents, sélection d'agents pertinents branchée dans l'orchestrateur, équipes et agents personnalisés.
- Routage de modèles (3 modes), fallback avec disjoncteur, budgets ; fournisseurs OpenAI-compatibles, Anthropic, Azure OpenAI, Bedrock.
- Local Bridge (CORS/PNA, appairage, GGUF, runtimes, voix/image) et mode pull pour les workers serveur.
- 17 outils avec permissions NONE→ADMIN, validation humaine stockée, boucle d'appel d'outils, terminal Docker isolé.
- Workflows (parallélisme, conditions, boucles, validation humaine, HTTP, code), déclencheurs cron/webhook/GitHub/événements.
- RAG (découpage, embeddings, recherche hybride), mémoire à 6 portées, stockage CAS (dédup + zstd + AES-GCM).
- Pages Angular : Marketplace, Fournisseurs, Équipes/Agent Builder, Automatisations, Quantification, Runtimes.
- Protocole inter-agents + replanification ; benchmarks et recommandation matériel ; pipelines voix/image ; CAS branché sur les fichiers ; pgvector (migration 0004) ; éditeur visuel de workflows ; pages Modèles locaux, Benchmarks, Monitoring, Sécurité ; coque Tauri ; CI Windows/macOS.
- Vidéo (analyse et génération), éditeur de workflows glisser-déposer, prompts détaillés pour les 1 096 agents, icônes Tauri.
- Correctif : `S3Storage.exists` était mal indenté (S3 inutilisable).
- Voir docs/ROADMAP.md pour ce qui est vérifié, non lancé ou non fait.

## Non publié
### Corrigé
- Orchestrateur : une tâche de test toujours en échec après les tours de correction reste `REVIEW_REQUIRED`
  (elle était écrasée par `COMPLETED`, donc jamais « À relire » dans l'interface). Test de non-régression ajouté.

### Ajouté — plateforme multi-agents
- Catalogue de 1 096 agents, recherche filtrée, analyse d'intention et sélection ciblée (`app/catalog`, `app/routing`).
- Routage de modèles (3 modes), fallback avec disjoncteur, 15 types de fournisseurs OpenAI-compatibles + Anthropic.
- Fournisseurs par organisation (API `/api/providers`), clés chiffrées AES-256-GCM, préférences `/api/ai-settings`,
  aperçu `/api/models/route`, budget mensuel en dollars (`?confirm_budget=true`).
- Runtimes locaux : détection, lecture GGUF, profil matériel, Quantization Studio, benchmark.
- Outils avec niveaux de permission et validation humaine ; stockage adressable par contenu (dédup + compression + chiffrement).
- Local Bridge (`bridge/`) : appairage par jeton, contrôle Origin/Host, proxy des runtimes locaux, GGUF, matériel.
- Usage détaillé : tokens entrée/sortie, modèle réellement utilisé, coût (migration `0002`).
- Worker : utilise les fournisseurs configurés et le routage ; événements `model.routing`/`model.failed`/`model.fallback`.
- `docs/PLATFORM.md`, `docs/ROADMAP.md` (couverture honnête du cahier des charges).

### Ajouté
- Dépôt Git, `.gitattributes`, `.editorconfig`, `.dockerignore`, `Makefile`.
- `.gitignore` complété (`.storage/`, caches, variantes de `.env`).

### Documentation
- README : suppression de l'étape de migration obsolète (la migration `0001` existe), section « Suivi avec Git ».

## 0.2.0 — état fourni
Import initial du projet.
