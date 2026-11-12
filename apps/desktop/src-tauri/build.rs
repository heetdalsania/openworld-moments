// SPDX-License-Identifier: AGPL-3.0-or-later
fn main() {
    // M33: the target triple is reported in the platform capabilities and the version
    // report, so a wrong-architecture build is visible without inspecting the binary.
    let target = std::env::var("TARGET").expect("cargo sets TARGET");
    println!("cargo:rustc-env=OWM_BUILD_TARGET={target}");
    tauri_build::build()
}
