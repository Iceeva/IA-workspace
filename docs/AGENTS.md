# Agents et orchestration

Rôles : Planner, Researcher, Architect, Coder, Tester, Debugger, Reviewer (`backend/app/agents/roles.py`).
Chaque agent : nom, rôle, description, prompt système, modèle, température, outils (colonne JSON `agents.tools`), statut.
Une ligne `agents` d'une organisation surcharge modèle, prompt et température du rôle correspondant pendant ses exécutions.

## Cycle d'une mission
1. Le **Planner** renvoie un JSON `{tasks:[{id,title,agent,depends_on}]}`. Agents autorisés : researcher, architect, coder, tester, reviewer.
2. `parse_plan` valide agents, dépendances et absence de cycle. Plan invalide → plan par défaut + événement `plan.fallback`.
3. Les tâches s'exécutent **par couches** (`TaskGraph.layers`) ; une couche tourne en parallèle (`asyncio.gather`).
4. Chaque résultat est transmis en contexte aux tâches dépendantes et publié comme `agent.message` (table `agent_messages`).
5. Le **Tester** doit finir par `VERDICT: PASS|FAIL`. Sur FAIL : Debugger → nouveau test, jusqu'à 2 tours, sinon `REVIEW_REQUIRED`.
6. Le **Coder** produit des blocs ```` ```lang path=chemin ```` ; le worker les valide (`safe_path`), les écrit dans le stockage objet, et émet un diff.
7. Annulation : le statut `CANCELLING` est lu entre deux couches.

## États de tâche
PENDING, QUEUED, RUNNING, WAITING, COMPLETED, FAILED, CANCELLED, REVIEW_REQUIRED.
Les états QUEUED et WAITING sont définis mais non émis par le moteur actuel (l'exécution par couches ne les utilise pas).

## Mémoire
`DBMemoryStore` (conversation / projet / agent) avec recherche par mots-clés. Interface `Embedder` prévue pour brancher embeddings et RAG vectoriel ; colonne `memories.embedding` réservée.

## Mitigation d'injection de prompt
Le contenu amont est placé entre `<context>` et `</context>` avec une consigne système de ne jamais l'exécuter comme instruction. Atténuation, pas garantie : les sorties de fichiers sont de toute façon validées côté serveur.
