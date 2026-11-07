// SPDX-License-Identifier: AGPL-3.0-or-later
//! M15 real worker through the same allow-listed routes as the calibration UI.
use openworld_moments_desktop_lib::calibration::write_export;
use openworld_moments_desktop_lib::media::api_route_allowed;
use openworld_moments_desktop_lib::worker::{Supervisor, SupervisorConfig, WorkerCommand};
use serde_json::{Value, json};
use std::path::PathBuf;

async fn ui(s: &Supervisor, method: &str, path: &str, body: Option<Value>) -> Value {
    assert!(api_route_allowed(method, path));
    s.request(method.parse().unwrap(), path, body.as_ref(), None)
        .await
        .unwrap()
}
#[tokio::test(flavor = "multi_thread")]
async fn save_export_import_reset_and_restart() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap();
    let python = if cfg!(windows) {
        root.join(".venv/Scripts/python.exe")
    } else {
        root.join(".venv/bin/python")
    };
    let temp = tempfile::tempdir().unwrap();
    let worker = WorkerCommand {
        program: python,
        args: vec!["-m".into(), "openworld_moments.worker".into()],
        cwd: Some(root.join("services/media-worker")),
    };
    let config = SupervisorConfig::new(worker, temp.path().join("library"));
    let supervisor = Supervisor::new(config.clone());
    let catalog = root.join("profiles/generic-open-world/profile.json");
    let original = std::fs::read(&catalog).unwrap();
    supervisor.start().await.unwrap();
    let path = "/v1/profiles/generic-open-world/calibration";
    let base = ui(&supervisor, "GET", path, None).await;
    let saved = ui(
        &supervisor,
        "PUT",
        path,
        Some(json!({"base_key":base["base_key"],"regions":{"signal":[0.2,0.2,0.5,0.5]}})),
    )
    .await;
    let exported = serde_json::to_vec_pretty(&saved["patch"]).unwrap();
    let export_path = temp.path().join("patch.json");
    write_export(&export_path, &exported, "json").unwrap();
    let reset = ui(
        &supervisor,
        "POST",
        "/v1/profiles/generic-open-world/reset",
        None,
    )
    .await;
    assert_eq!(reset["effective"], base["base"]);
    let patch: Value = serde_json::from_slice(&std::fs::read(export_path).unwrap()).unwrap();
    let imported = ui(
        &supervisor,
        "POST",
        "/v1/profiles/generic-open-world/patch",
        Some(patch.clone()),
    )
    .await;
    assert_eq!(imported["patch"], patch);
    assert!(
        supervisor
            .request(
                reqwest::Method::PUT,
                path,
                Some(&json!({"base_key":base["base_key"],"regions":{"signal":[0.9,0,1,1]}})),
                None
            )
            .await
            .is_err()
    );
    supervisor.stop().await;
    let restarted = Supervisor::new(config);
    restarted.start().await.unwrap();
    assert_eq!(ui(&restarted, "GET", path, None).await["patch"], patch);
    assert_eq!(
        ui(
            &restarted,
            "POST",
            "/v1/profiles/generic-open-world/reset",
            None
        )
        .await["effective"],
        base["base"]
    );
    restarted.stop().await;
    assert_eq!(std::fs::read(catalog).unwrap(), original);
    for forbidden in [
        "/v1/profiles/../calibration",
        "/v1/profiles/generic-open-world/calibration?path=secret",
        "/v1/profiles/generic-open-world/media",
        "/v1/derived/cleanup",
    ] {
        assert!(!api_route_allowed("GET", forbidden));
    }
}
