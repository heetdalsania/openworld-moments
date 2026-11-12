// SPDX-License-Identifier: AGPL-3.0-or-later
//! Desktop host for OpenWorld Moments.
//!
//! Opens the UI, supervises the Python media worker (M03), and watches
//! user-approved folders for new captures (M07). The UI reaches the worker through
//! allow-listed routes and plays media over the `owm-media://` protocol (M09). Phone
//! uploads arrive through a temporary, separate LAN gateway process (M10).

use serde::Serialize;

pub mod calibration;
mod host;
pub mod media;
pub mod phone;
pub mod reveal;
pub mod watch;
pub mod worker;

/// Lifecycle stage reported to the UI until a release exists.
pub const STAGE: &str = "planning";

/// Basic identity of the running host, shown in the placeholder window.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AppInfo {
    pub name: &'static str,
    pub version: String,
    pub stage: &'static str,
}

/// Returns the host's identity. Kept free of Tauri types so it is unit-testable.
pub fn app_info() -> AppInfo {
    AppInfo {
        name: "OpenWorld Moments",
        version: env!("CARGO_PKG_VERSION").to_owned(),
        stage: STAGE,
    }
}

mod commands {
    /// Exposed to the UI as `invoke("app_info")`.
    #[tauri::command]
    pub fn app_info(app: tauri::AppHandle) -> super::AppInfo {
        let mut info = super::app_info();
        info.version = app.package_info().version.to_string();
        if cfg!(target_os = "windows") && !cfg!(debug_assertions) {
            info.stage = "unsigned alpha candidate";
        }
        info
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .register_asynchronous_uri_scheme_protocol(media::SCHEME, |ctx, request, responder| {
            host::media_protocol(ctx.app_handle(), request, responder)
        })
        .setup(|app| host::setup(app.handle()))
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            host::worker_status,
            host::worker_start_diagnostic,
            host::worker_cancel_job,
            host::worker_list_jobs,
            host::worker_api,
            host::project_export,
            host::render_manifest_export,
            host::diagnostics_export,
            host::render_reveal,
            host::library_reveal,
            host::calibration_export_patch,
            host::calibration_export_sample,
            host::phone_interfaces,
            host::phone_status,
            host::phone_start,
            host::phone_stop,
            host::watched_folders_list,
            host::watched_folder_add,
            host::watched_folder_update,
            host::watched_folder_remove,
            host::watched_folder_files,
        ])
        .build(tauri::generate_context!())
        .expect("error while building OpenWorld Moments")
        .run(host::on_run_event);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn app_info_reports_planning_stage() {
        let info = app_info();
        assert_eq!(info.name, "OpenWorld Moments");
        assert_eq!(info.stage, "planning");
        assert_eq!(info.version, env!("CARGO_PKG_VERSION"));
    }

    #[test]
    fn app_info_serializes_with_ui_field_names() {
        let value = serde_json::to_value(app_info()).expect("AppInfo serializes");
        assert_eq!(value["name"], "OpenWorld Moments");
        assert_eq!(value["stage"], STAGE);
        assert!(value["version"].is_string());
    }
}
