// SPDX-License-Identifier: AGPL-3.0-or-later
//! Desktop host for OpenWorld Moments.
//!
//! Opens the UI and supervises the Python media worker (M03). Watched folders
//! and other OS integration arrive in later milestones (see MILESTONES.md).

use serde::Serialize;

mod host;
pub mod worker;

/// Lifecycle stage reported to the UI until a release exists.
pub const STAGE: &str = "planning";

/// Basic identity of the running host, shown in the placeholder window.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AppInfo {
    pub name: &'static str,
    pub version: &'static str,
    pub stage: &'static str,
}

/// Returns the host's identity. Kept free of Tauri types so it is unit-testable.
pub fn app_info() -> AppInfo {
    AppInfo {
        name: "OpenWorld Moments",
        version: env!("CARGO_PKG_VERSION"),
        stage: STAGE,
    }
}

mod commands {
    /// Exposed to the UI as `invoke("app_info")`.
    #[tauri::command]
    pub fn app_info() -> super::AppInfo {
        super::app_info()
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| host::setup(app.handle()))
        .invoke_handler(tauri::generate_handler![
            commands::app_info,
            host::worker_status,
            host::worker_start_diagnostic,
            host::worker_cancel_job,
            host::worker_list_jobs,
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
