# Application de bureau (Tauri 2)

Coque native autour de l'interface Angular, avec pilotage du Local Bridge (`start_bridge`, `stop_bridge`,
`bridge_running`, `bridge_token`). **Non compilée ni lancée là où elle a été écrite** (pas d'accès aux dépendances Rust).

```bash
cargo install tauri-cli --version "^2"
cd frontend && npm ci
cargo tauri dev                           # développement
cargo tauri build                         # .msi/.exe (Windows), .dmg (macOS), .deb/.AppImage (Linux)
```

Les icônes (`icons/`) sont fournies ; pour utiliser votre logo : `cargo tauri icon icons/logo-source.png` (remplacez le fichier source).

Prérequis : Rust, les dépendances système de Tauri (https://tauri.app/start/prerequisites/) et Python 3.10+ avec `pip install ./bridge`.
