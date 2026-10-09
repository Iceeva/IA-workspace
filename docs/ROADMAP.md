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
| 15 | Mode hybride | 🟡 | ✅ Bridge navigateur→local et **mode pull** (le bridge appelle le serveur, courtier mémoire/Redis, annulation, délai). 🟡 page « Runtimes » = état + instructions (pas d'appairage en un clic) |
| 2, 45 | Séparation agents / modèles / fournisseurs / runtimes / outils | ✅ | Les agents déclarent des capacités (`needs`) |
| 3, 4 | Intention, sélection d'agents pertinents | 🟡 | ✅ analyseur + sélecteur, **branchés dans l'orchestrateur** (le planificateur reçoit la short-list ; agents du catalogue exécutables ; testeurs → boucle de correction). ❌ replanification en cours d'exécution |
| 5, 6 | Catalogue > 1 000 agents | ✅ | 1 096 définitions. **Prompts génériques** : à affiner |
| 7, 8 | Fournisseurs, clés chiffrées | ✅ | 15+ types compatibles OpenAI, Anthropic, **Azure OpenAI, AWS Bedrock** ; AES-256-GCM avec rotation ; clés masquées ; page « Fournisseurs » (non lancée) |
| 9 | 3 stratégies de modèles | ✅ | Routeur + préférences par organisation + simulation de routage |
| 10, 11 | Modèles locaux, GGUF | 🟡 | Détection runtimes, lecture GGUF via le bridge. ❌ écran de sélection d'un fichier GGUF |
| 12, 32, 42 | Local Runtime, profil matériel, multiplateforme | 🟡 | ✅ Bridge + profil (NVIDIA, Apple Silicon). ❌ GPU AMD/Intel ; ❌ installeur ; CI Linux seulement |
| 16 | Multimodalité | 🟡 | Modalités déclarées et routables ; passthrough voix/image du bridge. ❌ pipelines complets (image→vision→agent, micro→STT→orchestrateur) |
| 17, 18 | Phonon, Sana | 🟡 | Adaptateurs HTTP configurables (convention OpenAI par défaut). **Non vérifiés contre les vrais Phonon/Sana** |
| 19 | Runtime Registry | 🟡 | En mémoire (bridge). ❌ persistance côté cloud |
| 20, 21 | Outils et permissions | ✅ | 17 outils, niveaux NONE→ADMIN (agents plafonnés à EXECUTE), audit, boucle d'appel d'outils. Terminal = conteneur Docker isolé (jamais l'hôte). Nécessite un démon Docker |
| 22 | Validation humaine | 🟡 | ✅ mécanisme + stockage + API + panneau « validation requise ». Non lancé |
| 23 | Mémoire multi-niveaux | 🟡 | 6 portées + rappel sémantique. Non lancé sur PostgreSQL |
| 24 | RAG | 🟡 | Découpage, embeddings (lexical hors-ligne ou API compatible), recherche hybride RRF **en Python**. ❌ pgvector |
| 25, 26 | Workflows, automatisations | 🟡 | ✅ moteur (parallélisme, conditions, boucles, fusion, retries, timeouts, validation humaine, HTTP, code), déclencheurs (cron, webhook HMAC, GitHub, événements), API. 🟡 page Automatisations = édition JSON. ❌ éditeur graphique de nœuds |
| 27 | Sandbox | ✅ | Docker, sans réseau, CPU/RAM/PIDs bornés ; erreur explicite si le démon est absent |
| 28, 29 | Stockage dédupliqué, compressé, chiffré | 🟡 | ✅ module CAS testé. ❌ pas branché sur l'upload ; ❌ pas de ramasse-miettes |
| 30 | Quantization Studio | 🟡 | ✅ calculs + API + page (valeurs indicatives, « avec perte »). ❌ quantification réelle |
| 31 | Benchmarks | 🟡 | ✅ module. ❌ endpoint/écran |
| 33–35 | Interface, dashboard, Marketplace | 🟡 | ✅ pages : Marketplace, Fournisseurs/stratégie, Équipes + Agent Builder, Automatisations, Quantification, Runtimes. Endpoint `/api/dashboard/overview` (coûts, fournisseurs, bridge, approbations). ❌ pages Benchmarks, Monitoring, Sécurité dédiées ; le tableau de bord Angular n'affiche pas encore ces nouvelles données |
| 36, 37 | Création d'agents, équipes | 🟡 | ✅ API + page. Les équipes restreignent le pool de sélection |
| 38 | Communication entre agents | 🟡 | Messages enregistrés ; protocole étendu non ajouté |
| 39 | Coûts et budgets | ✅ | Tokens entrée/sortie, modèle réel, coût ; plafond mensuel (bloquer / confirmer) |
| 40 | Fallback automatique | ✅ | Chaîne configurable + disjoncteur |
| 41 | Observabilité | 🟡 | Événements de routage et d'agents sélectionnés ; ❌ écran de trace dédié |
| 43, 44 | Architecture technique | 🟡 | FastAPI, Python, Postgres, Redis ✅. ❌ Tauri ; ❌ pgvector |
| 46, 47 | Objectif final | 🟡 | Chaîne complète câblée dans le code (sélecteur → routeur → outils → mémoire/RAG → validation) mais **jamais exécutée de bout en bout** |

## Ordre conseillé pour la suite
1. Lancer `make test` et `docker compose up`, corriger les écarts d'intégration (base, migrations, worker).
2. Exécuter les tests d'API et compiler le frontend (`npm ci && ng build`).
3. pgvector pour le RAG ; brancher le CAS sur l'upload.
4. Éditeur graphique de workflows, écrans Benchmarks/Monitoring/Sécurité, appairage du bridge.
5. Tauri, GPU AMD/Intel, CI Windows/macOS.
