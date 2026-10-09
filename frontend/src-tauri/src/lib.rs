//! Coque de bureau d'AI Workspace (mode local, §13/§43).
//!
//! Elle charge l'interface Angular et pilote le Local Bridge (processus Python `aiw_bridge`) : démarrage, arrêt, état et
//! lecture du jeton d'appairage. Le bridge n'écoute que sur 127.0.0.1 ; aucune commande ici n'exécute de texte fourni par
//! la page : les arguments sont fixes ou validés, jamais passés à un shell.

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::State;

#[derive(Default)]
struct BridgeState(Mutex<Option<Child>>);

fn home() -> Option<PathBuf> {
    std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from)
}

/// Origine autorisée à parler au bridge : schéma http(s) et caractères d'URL usuels uniquement.
fn valid_origin(o: &str) -> bool {
    (o.starts_with("http://") || o.starts_with("https://"))
        && o.len() <= 200
        && o.chars().all(|c| c.is_ascii_alphanumeric() || ":/.-_".contains(c))
}

fn running(child: &mut Option<Child>) -> bool {
    match child {
        Some(c) => matches!(c.try_wait(), Ok(None)),
        None => false,
    }
}

#[tauri::command]
fn start_bridge(state: State<BridgeState>, models_dir: Option<String>, origin: Option<String>) -> Result<bool, String> {
    let mut guard = state.0.lock().map_err(|_| "état verrouillé".to_string())?;
    if running(&mut guard) {
        return Ok(true);
    }
    let python = if cfg!(windows) { "python" } else { "python3" };
    let mut cmd = Command::new(python);
    cmd.args(["-m", "aiw_bridge"]);
    // L'application de bureau charge l'interface depuis son propre schéma : on autorise ces origines et le serveur de dev.
    for o in ["tauri://localhost", "http://tauri.localhost", "http://localhost:4200"] {
        cmd.args(["--origin", o]);
    }
    if let Some(o) = origin {
        if !valid_origin(&o) {
            return Err("origine invalide".into());
        }
        cmd.args(["--origin", &o]);
    }
    if let Some(d) = models_dir {
        if d.is_empty() || d.len() > 400 || d.contains('\0') {
            return Err("dossier de modèles invalide".into());
        }
        cmd.args(["--models-dir", &d]);
    }
    let child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("impossible de lancer le bridge ({python} -m aiw_bridge) : {e}"))?;
    *guard = Some(child);
    Ok(true)
}

#[tauri::command]
fn stop_bridge(state: State<BridgeState>) -> Result<bool, String> {
    let mut guard = state.0.lock().map_err(|_| "état verrouillé".to_string())?;
    if let Some(mut c) = guard.take() {
        let _ = c.kill();
        let _ = c.wait();
    }
    Ok(false)
}

#[tauri::command]
fn bridge_running(state: State<BridgeState>) -> bool {
    state.0.lock().map(|mut g| running(&mut g)).unwrap_or(false)
}

/// Jeton d'appairage créé par le bridge au premier lancement (~/.ai-workspace/bridge-token).
#[tauri::command]
fn bridge_token() -> Result<String, String> {
    let path = home().ok_or("dossier personnel introuvable")?.join(".ai-workspace").join("bridge-token");
    std::fs::read_to_string(&path).map(|s| s.trim().to_string()).map_err(|_| "jeton absent : démarrez le bridge d'abord".into())
}

pub fn run() {
    tauri::Builder::default()
        .manage(BridgeState::default())
        .invoke_handler(tauri::generate_handler![start_bridge, stop_bridge, bridge_running, bridge_token])
        .build(tauri::generate_context!())
        .expect("erreur au lancement d'AI Workspace")
        .run(|app, event| {
            // À la fermeture, ne laisse pas de bridge orphelin.
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = tauri::Manager::try_state::<BridgeState>(app) {
                    if let Ok(mut g) = state.0.lock() {
                        if let Some(mut c) = g.take() {
                            let _ = c.kill();
                        }
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::valid_origin;

    #[test]
    fn origin_validation() {
        assert!(valid_origin("https://ai-workspace.example.com"));
        assert!(valid_origin("http://localhost:4200"));
        assert!(!valid_origin("file:///etc/passwd"));
        assert!(!valid_origin("https://a.com; rm -rf /"));
        assert!(!valid_origin("javascript:alert(1)"));
    }
}
