# Installation et installeurs

## Application de bureau (recommandé pour un usage local)
Paquets produits par `.github/workflows/release.yml` à chaque tag `vX.Y.Z` (brouillon de release GitHub) :

| OS | Paquet |
|----|--------|
| Windows | `.exe` (NSIS, installation par utilisateur) et `.msi` |
| macOS | `.dmg` (Apple Silicon et Intel) |
| Linux | `.deb` et `.AppImage` |

Chaque paquet embarque le **Local Bridge** comme exécutable autonome (PyInstaller, sans Python chez l'utilisateur) ; l'application
le lance et l'arrête. Les exécutables du bridge sont aussi joints à la release (`aiw-bridge-<triplet>`) pour l'usage
« application web + modèles locaux » : lancez-le, copiez le jeton affiché dans la page *Bridge*.

**Statut** : le workflow n'a pas été exécuté là où il a été écrit. Premier essai : poussez un tag `v0.0.0-test`, lisez les journaux.
**Signature** : non configurée. Sans certificat, Windows SmartScreen et macOS Gatekeeper avertissent à l'ouverture. Pour signer,
renseignez les secrets du dépôt `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
`APPLE_PASSWORD`, `APPLE_TEAM_ID` (notarisation) ; pour Windows, un certificat de signature de code (voir la documentation Tauri).

## Construire soi-même
```bash
pip install pyinstaller && python bridge/build_bridge.py      # → frontend/src-tauri/binaries/aiw-bridge-<triplet>
cd frontend && npm ci && cargo tauri build                    # paquets de l'OS courant
```
PyInstaller et Tauri ne compilent pas en croisé : un OS = une machine (ou un runner CI).

## Serveur (cloud / équipe)
`docker compose up --build` (PostgreSQL + pgvector, Redis, API, worker, front) ; voir DEPLOYMENT.md. Vercel pour l'interface.

## Runtimes optionnels
- **Phonon** (voix) : `fermion serve` (127.0.0.1:8000) ; renseignez `STT_URL`, `STT_MODEL=phonon-2` (+ `STT_API_KEY` si `--api-key`).
- **Sana** (image/vidéo) : `python -m app.runtimes.servers.sana_server --port 8020` (GPU NVIDIA, diffusers) ; `VIDEO_GEN_URL=http://127.0.0.1:8020`.
- **Index vectoriel** : `EMBEDDING_DIM` (défaut 1536) puis `alembic upgrade head` ; autre dimension : `python -m app.services.vector_index --dim N`.
