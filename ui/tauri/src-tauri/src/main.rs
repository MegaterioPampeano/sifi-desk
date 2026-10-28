//! Launcher mínimo de siFi Desk.
//!
//! Responsabilidades y nada más:
//!   1. arrancar el sidecar `sifid` (binario empaquetado junto al ejecutable),
//!   2. abrir la ventana con el frontend estático de `ui/`,
//!   3. matar el sidecar cuando se cierra la app.
//!
//! La UI habla por HTTP con `127.0.0.1:<puerto>`; este proceso no implementa
//! lógica de negocio ni toca el core científico.

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

/// Puerto fijo de la primera versión. El contrato de `sifid` (M3) prevé puerto
/// efímero + token de sesión; cuando eso exista, acá se lee el puerto que
/// anuncie el sidecar y se inyecta en la UI (ver ui/TODO.md).
const SIFID_PORT: u16 = 8791;

struct Sidecar(Mutex<Option<Child>>);

fn sidecar_path() -> std::path::PathBuf {
    let exe = std::env::current_exe().expect("no se pudo resolver el ejecutable actual");
    let dir = exe.parent().expect("el ejecutable no tiene directorio padre");
    let nombre = if cfg!(windows) { "sifid.exe" } else { "sifid" };
    dir.join(nombre)
}

fn spawn_sidecar() -> std::io::Result<Child> {
    let path = sidecar_path();
    Command::new(&path)
        .env("SIFID_PORT", SIFID_PORT.to_string())
        .arg("serve")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(SIFID_PORT.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
}

fn main() {
    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(None)))
        .setup(|app| {
            match spawn_sidecar() {
                Ok(child) => {
                    if let Ok(mut slot) = app.state::<Sidecar>().0.lock() {
                        *slot = Some(child);
                    }
                }
                // En desarrollo es normal correr la UI contra `ui/mock/server.py`
                // y no tener `sifid` al lado del ejecutable: se avisa y sigue.
                Err(err) => eprintln!(
                    "sifid no arrancó ({}): {}. La UI va a mostrar el servicio caído.",
                    sidecar_path().display(),
                    err
                ),
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir siFi Desk")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Ok(mut slot) = app.state::<Sidecar>().0.lock() {
                    if let Some(mut child) = slot.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}
