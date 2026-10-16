# Couverture du cahier des charges (47 sections)

Légende : ✅ fait et testé · 🟡 partiel / non vérifié de bout en bout · ❌ à faire.

**Ce que « testé » veut dire ici.** Les modules purs (catalogue, routage, runtimes, outils, workflows, RAG, bridge, crypto, CAS)
sont couverts par ~120 tests qui ont été exécutés. Le code qui dépend de PostgreSQL/SQLAlchemy/Redis — `services/assembly.py`,
`services/workflow_exec.py`, `worker/main.py`, les routeurs `api/ai_platform.py`, `api/automation.py`, `api/bridge.py`, les
migrations 0002/0003 — et le **frontend Angular** ont seulement été compilés/analysés statiquement, **jamais lancés** là où ils ont
été écrits (pas de réseau, pas de base). Les tests `backend/tests/test_platform_api.py` sont écrits mais n'ont pas été exécutés.
Premier réflexe sur votre machine : `make test` puis `docker compose up`, et corriger ce qui casse.

| § | Sujet | État | Détail |
|---|---|---|---|
| 1, 13, 14 | Modes local / cloud (Vercel) | 🟡 | Docker Compose et `api/index.py` existaient ; Control/Execution Plane décrit dans PLATFORM.md ; pas de paquet desktop |
| 15 | Mode hybride | 🟡 | ✅ Bridge navigateur→local et **mode pull** (le bridge appelle le serveur, courtier mémoire/Redis, annulation, délai). 🟡 page « Runtimes » = état + instructions (pas d'appairage en un clic ; le registre persistant est visible dans la page et alimenté aussi par le mode pull : le bridge envoie sa fiche à chaque poll) |
| 2, 45 | Séparation agents / modèles / fournisseurs / runtimes / outils | ✅ | Les agents déclarent des capacités (`needs`) |
| 3, 4 | Intention, sélection d'agents pertinents | ✅ | Analyseur + sélecteur branchés dans l'orchestrateur ; **replanification en cours d'exécution** (un agent peut demander un autre agent, borné à 3) ; testeurs → boucle de correction |
| 5, 6 | Catalogue > 1 000 agents | ✅ | 1 096 définitions. ✅ prompts spécialisés par agent (mission, pratiques, livrable, garde-fous, outils selon permission), tous distincts, testés |
| 7, 8 | Fournisseurs, clés chiffrées | ✅ | 15+ types compatibles OpenAI, Anthropic, **Azure OpenAI, AWS Bedrock** ; AES-256-GCM avec rotation ; clés masquées ; page « Fournisseurs » (non lancée) |
| 9 | 3 stratégies de modèles | ✅ | Routeur + préférences par organisation + simulation de routage |
| 10, 11 | Modèles locaux, GGUF | 🟡 | ✅ Détection runtimes, lecture GGUF via le bridge, **sélecteur de fichier .gguf** (en-tête lu dans le navigateur : architecture, quantification, contexte, mémoire, ajustement à la machine, commandes llama.cpp/Ollama/LM Studio). ✅ attribution en un clic : le bridge sert le fichier via `llama-server` (2 serveurs max, binaire à fournir), enregistre un runtime, et `PUT /api/local-model-assignments` lie le modèle à l'agent. 🟡 non lancé avec un vrai `llama-server` ; l'attribution est au niveau de l'organisation mais seul le bridge de l'utilisateur qui exécute répond (portée org:user) |
| 12, 32, 42 | Local Runtime, profil matériel, multiplateforme | 🟡 | ✅ Bridge + profil (NVIDIA, Apple Silicon, **AMD et Intel** : rocm-smi, sysfs, PowerShell/registre Windows ; iGPU = mémoire partagée). ❌ AMD/Intel jamais testés sur du vrai matériel (analyseurs testés sur des sorties types). CI Linux + job Windows/macOS (non exécuté). ✅ installeurs (PyInstaller + Tauri, workflow `release.yml`, non exécuté, non signés) |
| 16 | Multimodalité | 🟡 | ✅ pipelines voix→STT→mission et image→vision→mission (`/api/multimodal/prepare`, images dans les messages OpenAI/Anthropic/Bedrock), génération d'image via adaptateur. ✅ vidéo : analyse (images clés + piste audio via ffmpeg → vision + STT, `/api/multimodal/prepare`) et génération (`VideoSpec`, `/api/multimodal/generate-video`, capacité `text-to-video`) — adaptateur au format générique, **non vérifié contre un vrai serveur** ; ✅ images aussi en mode pull (data: seulement) |
| 17, 18 | Phonon, Sana | 🟡 | **Phonon** : adaptateur aligné sur la doc publiée de `fermion serve` (Whisper-compatible, `phonon-2`, WAV/FLAC/OGG, 32 Mo, clé Bearer ; conversion ffmpeg des autres formats) — non essayé contre un serveur lancé. **Sana** : pas de serveur HTTP officiel → `runtimes/servers/sana_server.py` (diffusers `SanaPipeline`/`SanaVideoPipeline`, appels conformes à la doc) — non exécuté (pas de GPU) |
| 19 | Runtime Registry | ✅ | Registre du bridge + **persistance côté serveur** (`runtime_records`, migration 0006, `/api/runtimes`, assainissement des rapports : adresses locales seulement, aucune clé) — non exécuté sur PostgreSQL |
| 20, 21 | Outils et permissions | ✅ | 17 outils, niveaux NONE→ADMIN (agents plafonnés à EXECUTE), audit, boucle d'appel d'outils. Terminal = conteneur Docker isolé (jamais l'hôte). Nécessite un démon Docker |
| 22 | Validation humaine | 🟡 | ✅ mécanisme + stockage + API + panneau « validation requise ». Non lancé |
| 23 | Mémoire multi-niveaux | 🟡 | 6 portées + rappel sémantique. Non lancé sur PostgreSQL |
| 24 | RAG | 🟡 | Découpage, embeddings, recherche hybride RRF ; pré-sélection **pgvector + plein texte** côté PostgreSQL (migration 0004, repli Python). **index HNSW** sur `embedding_vec vector(EMBEDDING_DIM)` (migration 0005, `python -m app.services.vector_index`), repli automatique si la dimension diffère — non exécuté sur PostgreSQL |
| 25, 26 | Workflows, automatisations | 🟡 | ✅ moteur, déclencheurs, API, **éditeur visuel** (nœuds typés, dépendances, aperçu du graphe) + mode JSON. ✅ canevas glisser-déposer (déplacer, relier, supprimer un lien, anti-cycle ; positions dans `ui`) — non exécuté dans un navigateur|
| 27 | Sandbox | ✅ | Docker, sans réseau, CPU/RAM/PIDs bornés ; erreur explicite si le démon est absent |
| 28, 29 | Stockage dédupliqué, compressé, chiffré | ✅ | CAS **branché sur l'upload/lecture/suppression** (objets hérités toujours lisibles), suppression des orphelins ; testé sur le disque local. S3 : bug d'instanciation corrigé, non testé en réel |
| 30 | Quantization Studio | 🟡 | ✅ calculs + API + page (valeurs indicatives, « avec perte »). ✅ **quantification réelle** d'un GGUF local via `llama-quantize` (bridge : liste blanche de types, jamais d'écrasement, disque vérifié, annulable, requantification refusée sauf confirmation) — testée avec un faux binaire, jamais avec llama.cpp |
| 31 | Benchmarks | 🟡 | ✅ module + `POST /api/benchmarks` + page. ✅ CPU/RAM/VRAM (repos, pic, écart) : côté serveur si l'endpoint est en boucle locale, sinon échantillonnés par le navigateur via `GET /resources` du bridge. 🟡 VRAM : NVIDIA seulement (nvidia-smi) |
| 33–35 | Interface, dashboard, Marketplace | 🟡 | ✅ pages : Marketplace, Fournisseurs/stratégie, Équipes + Agent Builder, Automatisations, Quantification, Runtimes, Modèles locaux (matériel, GGUF, recommandations), Benchmarks, Monitoring, Sécurité. Aucune n'a été compilée ni lancée. ✅ courbes temps réel (rafraîchissement 5 s) ; ✅ Équipes (`/teams`) et Agent Builder (`/agent-builder`) sont deux pages distinctes |
| 36, 37 | Création d'agents, équipes | 🟡 | ✅ API + page. Les équipes restreignent le pool de sélection |
| 38 | Communication entre agents | ✅ | Protocole typé (7 types), journal reconstructible, délégation → replanification ; testé |
| 39 | Coûts et budgets | ✅ | Tokens entrée/sortie, modèle réel, coût ; plafond mensuel (bloquer / confirmer) |
| 40 | Fallback automatique | ✅ | Chaîne configurable + disjoncteur |
| 41 | Observabilité | ✅ | Écran **Trace** dans le détail d'une exécution : agent, raison du choix, modèle réel et bascules, outils appelés (sans arguments ni résultats), tokens, durée, étape suivante, replanifications (`/api/executions/{id}/trace`, `orchestration/trace.py`, testé) — l'écran n'a pas été lancé |
| 43, 44 | Architecture technique | 🟡 | FastAPI, Python, Postgres+pgvector, Redis ✅ ; Control/Execution Plane documenté ; **coque Tauri écrite, non compilée** (icônes fournies, pas de paquet) |
| 46, 47 | Objectif final | 🟡 | Chaîne complète câblée dans le code (sélecteur → routeur → outils → mémoire/RAG → validation) mais **jamais exécutée de bout en bout** |

## Ordre conseillé pour la suite
1. Lancer `make test` et `docker compose up`, corriger les écarts d'intégration (base, migrations, worker).
2. Exécuter les tests d'API et compiler le frontend (`npm ci && ng build`) ; compiler la coque Tauri.
3. Essayer Phonon (`fermion serve`) et le serveur Sana sur une vraie machine.
4. Premier tag de test pour la CI de release (installeurs) ; signature Windows/macOS ; tester HNSW sur PostgreSQL.
5. Matériel AMD/Intel réel pour valider la détection.
