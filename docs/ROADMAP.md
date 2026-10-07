# Couverture du cahier des charges (47 sections)

Légende : ✅ fait et testé · 🟡 partiel / non branché · ❌ à faire. « Testé » = tests exécutés ; les tests d'API
(`backend/tests/test_platform_api.py`) sont écrits mais n'ont pas pu être exécutés là où le code a été produit.

| § | Sujet | État | Détail |
|---|---|---|---|
| 1, 13, 14 | Modes local / cloud (Vercel) | 🟡 | Docker Compose et `api/index.py` existaient déjà ; pas de paquet desktop |
| 15 | Mode hybride | 🟡 | Bridge ✅ (navigateur → modèles locaux). ❌ mode « pull » pour que le worker serveur utilise vos modèles ; ❌ écran d'appairage dans l'UI |
| 2, 45 | Séparation agents / modèles / fournisseurs / runtimes / outils | ✅ | Les agents déclarent des capacités (`needs`), jamais un fournisseur |
| 3, 4 | Intention, sélection d'agents pertinents | 🟡 | ✅ analyseur + sélecteur (heuristique FR/EN, raffinement LLM optionnel). ❌ l'orchestrateur planifie encore avec ses 7 rôles fixes : le sélecteur n'est exposé qu'en aperçu (`POST /catalog/select`). ❌ replanification en cours d'exécution |
| 5, 6 | Catalogue > 1 000 agents | ✅ | 1 096 définitions générées depuis une taxonomie. **Leurs prompts sont génériques** : à affiner agent par agent |
| 7, 8 | Fournisseurs, clés chiffrées | 🟡 | ✅ 15 types compatibles OpenAI + Anthropic, AES-256-GCM, clés masquées. ❌ Azure OpenAI, AWS Bedrock (protocoles différents). ❌ écrans de gestion (API seulement) |
| 9 | 3 stratégies de modèles | ✅ | Routeur + préférences par organisation, branché dans le worker |
| 10, 11 | Modèles locaux, GGUF | ✅ | Détection Ollama / LM Studio / llama.cpp / vLLM ; lecture d'en-tête GGUF. ❌ écrans |
| 12, 32, 42 | Local Runtime, profil matériel, multiplateforme | 🟡 | ✅ Bridge + profil (NVIDIA, Apple Silicon). ❌ GPU AMD/Intel ; ❌ installeur ; CI Linux seulement |
| 16 | Multimodalité | 🟡 | Modalités et capacités déclarées et routables. ❌ aucun pipeline d'exécution image/audio/vidéo |
| 17, 18 | Phonon, Sana | 🟡 | Enregistrables comme runtimes déclarés (`speech-to-text`, `text-to-image`). ❌ adaptateurs d'appel : leur protocole n'est pas connu du projet |
| 19 | Runtime Registry | 🟡 | ✅ en mémoire (bridge). ❌ persistance et API côté cloud |
| 20, 21 | Outils et permissions | 🟡 | ✅ registre, niveaux, audit ; filesystem, calculatrice, git (lecture), python (sandbox Docker). ❌ terminal, navigateur, recherche web, GitHub, base de données, HTTP, e-mail… (déclarés `planned`). ❌ boucle d'appel d'outils par les agents |
| 22 | Validation humaine | 🟡 | ✅ mécanisme (refus par défaut, délai = refus). ❌ stockage en base et écran d'approbation |
| 23 | Mémoire multi-niveaux | 🟡 | Mémoire projet existante ; niveaux utilisateur/agent/organisation non ajoutés |
| 24 | RAG | ❌ | pgvector, découpage, embeddings : non commencé |
| 25, 26 | Éditeur de workflows, automatisations | ❌ | Seuls les workflows préréglés existaient ; pas d'éditeur ni de déclencheurs |
| 27 | Sandbox | ✅ | Existante (Docker, sans réseau, CPU/RAM/PIDs bornés) |
| 28, 29 | Stockage dédupliqué, compressé, chiffré | 🟡 | ✅ module CAS testé (hash par organisation, zstd/zlib, AES-GCM, intégrité). ❌ pas branché sur l'upload ; ❌ pas de comptage de références ni de ramasse-miettes |
| 30 | Quantization Studio | 🟡 | ✅ calculs + API (valeurs indicatives, étiquetées « avec perte »). ❌ écran ; ❌ quantification réelle de modèles |
| 31 | Benchmarks | 🟡 | ✅ module (TTFT, tokens/s, démarrage à froid, stabilité, ressources, qualité rapide). ❌ endpoint/écran |
| 33–35 | Interface, tableau de bord temps réel, Marketplace | ❌ | Frontend Angular non modifié. L'API de recherche du Marketplace existe |
| 36, 37 | Création d'agents, équipes | ❌ | Agents personnalisables via JSON (`Catalog.load_json`) ; pas d'éditeur ni d'équipes |
| 38 | Communication entre agents | 🟡 | Messages enregistrés (existant) ; protocole étendu non ajouté |
| 39 | Coûts et budgets | ✅ | Tokens entrée/sortie, modèle réel, coût par tâche ; plafond mensuel (bloquer / confirmer) |
| 40 | Fallback automatique | ✅ | Chaîne configurable + disjoncteur |
| 41 | Observabilité | 🟡 | Événements `model.routing`, `model.failed`, `model.fallback` ; modèle et tokens par tâche. ❌ écran de trace |
| 43, 44 | Architecture technique, Control/Execution Plane | 🟡 | FastAPI, Python, Postgres, Redis ✅. ❌ Tauri ; ❌ pgvector |
| 46, 47 | Objectif final | 🟡 | Les briques sont là ; l'intégration complète (sélecteur → orchestrateur → outils) reste à faire |

## Ordre conseillé pour la suite
1. Brancher le sélecteur dans l'orchestrateur (le Planner reçoit la short-list d'agents ; l'engine exécute des agents du catalogue).
2. Boucle d'appel d'outils (function calling) avec `ToolBox` et approbations en base.
3. Mode « pull » du Local Bridge (files Redis par utilisateur) + écran d'appairage.
4. Écrans Angular : fournisseurs, modèles/routage, Marketplace, tableau de bord.
5. RAG (pgvector), puis éditeur de workflows et déclencheurs.
