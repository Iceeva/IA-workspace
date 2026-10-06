# Journal des changements

## Non publié
### Corrigé
- Orchestrateur : une tâche de test toujours en échec après les tours de correction reste `REVIEW_REQUIRED`
  (elle était écrasée par `COMPLETED`, donc jamais « À relire » dans l'interface). Test de non-régression ajouté.

### Ajouté
- Dépôt Git, `.gitattributes`, `.editorconfig`, `.dockerignore`, `Makefile`.
- `.gitignore` complété (`.storage/`, caches, variantes de `.env`).

### Documentation
- README : suppression de l'étape de migration obsolète (la migration `0001` existe), section « Suivi avec Git ».

## 0.2.0 — état fourni
Import initial du projet.
