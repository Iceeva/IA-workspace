// Empêche l'ouverture d'une console supplémentaire sous Windows en version release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    ai_workspace_lib::run()
}
