# Journal des changements

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
