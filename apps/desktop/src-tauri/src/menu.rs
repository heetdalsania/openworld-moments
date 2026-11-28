// SPDX-License-Identifier: AGPL-3.0-or-later
//! M38: native macOS menus, shortcuts and quit handling.
//!
//! macOS builds get the standard application, File, Edit, View, Window and Help menus
//! with `Command` shortcuts. Windows builds keep the menu-free window and the in-app
//! `Ctrl` shortcuts they have always had; nothing here changes them.
//!
//! The layout is a plain description ([`macos_layout`]) so it is tested on every
//! platform. Text editing items (Undo, Cut, Copy, Paste, Select All) are the system's
//! own, so they work in every text field. App actions are sent to the UI as
//! [`EVENT`] with the item's ID; the UI decides what they do (`apps/desktop/src/menu.ts`).
//! Quit is handled here so it works even while the UI is busy: it asks first when jobs
//! are running or project edits are not saved yet.

use std::sync::atomic::{AtomicBool, Ordering};

use serde::Deserialize;
use serde_json::Value;

/// Event sent to the UI with a menu item's ID.
pub const EVENT: &str = "menu://action";

/// Items whose action the host performs itself.
pub const QUIT: &str = "app.quit";
const RECENT: &str = "file.recent";
const RECENT_CLEAR: &str = "file.recent_clear";
const RECENT_PREFIX: &str = "recent:";
const HELP_GUIDES: &str = "help.guides";
const HELP_MAC_GUIDE: &str = "help.mac_guide";

/// System-provided items: AppKit performs them, so they behave exactly as in other apps.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Native {
    About,
    Services,
    Hide,
    HideOthers,
    ShowAll,
    Undo,
    Redo,
    Cut,
    Copy,
    Paste,
    SelectAll,
    CloseWindow,
    Minimize,
    Zoom,
    Fullscreen,
    BringAllToFront,
    Separator,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Entry {
    /// An app action, sent to the UI (or handled by the host for Quit and Help links).
    Action {
        id: &'static str,
        label: &'static str,
        accelerator: Option<&'static str>,
    },
    Native(Native),
    /// File ▸ Open Recent, filled with recently opened projects.
    Recent,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Section {
    pub id: &'static str,
    pub title: &'static str,
    pub entries: Vec<Entry>,
}

const fn action(id: &'static str, label: &'static str, accelerator: Option<&'static str>) -> Entry {
    Entry::Action {
        id,
        label,
        accelerator,
    }
}

/// The macOS menu bar, following Apple's Human Interface Guidelines for menu order,
/// names and standard shortcuts.
pub fn macos_layout() -> Vec<Section> {
    use Native::*;
    vec![
        Section {
            id: "app",
            title: "OpenWorld Moments",
            entries: vec![
                Entry::Native(About),
                Entry::Native(Separator),
                action("app.settings", "Settings…", Some("Cmd+,")),
                Entry::Native(Separator),
                Entry::Native(Services),
                Entry::Native(Separator),
                Entry::Native(Hide),
                Entry::Native(HideOthers),
                Entry::Native(ShowAll),
                Entry::Native(Separator),
                action(QUIT, "Quit OpenWorld Moments", Some("Cmd+Q")),
            ],
        },
        Section {
            id: "file",
            title: "File",
            entries: vec![
                action("file.import", "Import…", Some("Cmd+Shift+I")),
                action("file.phone", "Import from Phone…", None),
                Entry::Native(Separator),
                action(
                    "file.new_project",
                    "New Project from Session…",
                    Some("Cmd+N"),
                ),
                Entry::Recent,
                Entry::Native(Separator),
                action(
                    "file.reveal_library",
                    "Show Library in Finder",
                    Some("Cmd+Shift+R"),
                ),
                Entry::Native(Separator),
                Entry::Native(CloseWindow),
            ],
        },
        Section {
            id: "edit",
            title: "Edit",
            entries: vec![
                Entry::Native(Undo),
                Entry::Native(Redo),
                Entry::Native(Separator),
                Entry::Native(Cut),
                Entry::Native(Copy),
                Entry::Native(Paste),
                Entry::Native(SelectAll),
                Entry::Native(Separator),
                action("edit.find", "Find…", Some("Cmd+F")),
            ],
        },
        Section {
            id: "view",
            title: "View",
            entries: vec![
                action("view.library", "Library", Some("Cmd+1")),
                action("view.sessions", "Sessions", Some("Cmd+2")),
                action("view.projects", "Projects", Some("Cmd+3")),
                action("view.search", "Search", Some("Cmd+4")),
                Entry::Native(Separator),
                action("view.jobs", "Show Background Jobs", Some("Cmd+Alt+J")),
                Entry::Native(Separator),
                action("view.text_bigger", "Make Text Bigger", Some("Cmd+=")),
                action("view.text_smaller", "Make Text Smaller", Some("Cmd+-")),
                action("view.text_actual", "Actual Size", Some("Cmd+0")),
                Entry::Native(Separator),
                Entry::Native(Fullscreen),
            ],
        },
        Section {
            id: "window",
            title: "Window",
            entries: vec![
                Entry::Native(Minimize),
                Entry::Native(Zoom),
                Entry::Native(Separator),
                Entry::Native(BringAllToFront),
            ],
        },
        Section {
            id: "help",
            title: "Help",
            entries: vec![
                action(HELP_GUIDES, "OpenWorld Moments Help", None),
                action(HELP_MAC_GUIDE, "Using OpenWorld Moments on a Mac", None),
                action("help.shortcuts", "Keyboard Shortcuts", Some("Cmd+/")),
                Entry::Native(Separator),
                action("help.diagnostics", "Save Diagnostics Report…", None),
                action("help.setup", "Run Setup Again", None),
            ],
        },
    ]
}

/// IDs of every app action in the layout, for the UI's contract test.
pub fn action_ids() -> Vec<&'static str> {
    macos_layout()
        .into_iter()
        .flat_map(|s| s.entries)
        .filter_map(|e| match e {
            Entry::Action { id, .. } => Some(id),
            _ => None,
        })
        .collect()
}

// -- user guides and System Settings -------------------------------------------------

const GUIDES: &str = "https://github.com/heetdalsania/openworld-moments/blob/main/docs/guides/";

/// The only web pages the app opens: user guides, by fixed topic.
pub fn guide_url(topic: &str) -> Option<String> {
    let page = match topic {
        "index" => "README.md",
        "macos" => "macos.md",
        "macos-install" => "macos.md#install",
        "macos-permissions" => "macos.md#permissions-and-recovery",
        "macos-troubleshooting" => "troubleshooting.md#macos",
        "accessibility" => "accessibility.md",
        "diagnostics" => "diagnostics.md",
        "phone" => "phone-upload.md",
        _ => return None,
    };
    Some(format!("{GUIDES}{page}"))
}

/// System Settings panes the app may open. Each one only shows the user where to grant
/// access; none of them turns a protection off.
pub fn settings_url(pane: &str) -> Option<&'static str> {
    match pane {
        "files-and-folders" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders")
        }
        "local-network" => {
            Some("x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork")
        }
        _ => None,
    }
}

// -- Open Recent ----------------------------------------------------------------------

/// A recently opened project, as the UI reports it.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct RecentProject {
    pub id: String,
    pub title: String,
}

pub const RECENT_LIMIT: usize = 10;
const TITLE_LIMIT: usize = 60;

fn is_project_id(id: &str) -> bool {
    crate::media::is_id(id, "prj_")
}

/// Menu entries for Open Recent: valid project IDs only, newest first, no duplicates,
/// at most [`RECENT_LIMIT`], with short single-line titles.
pub fn recent_entries(items: &[RecentProject]) -> Vec<(String, String)> {
    let mut seen = std::collections::HashSet::new();
    items
        .iter()
        .filter(|item| is_project_id(&item.id) && seen.insert(item.id.clone()))
        .take(RECENT_LIMIT)
        .map(|item| {
            let clean: String = item
                .title
                .chars()
                // Control characters and bidirectional overrides could disguise a title.
                .map(|c| {
                    let bidi = matches!(c, '\u{200E}' | '\u{200F}' | '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}');
                    if c.is_control() || bidi { ' ' } else { c }
                })
                .collect();
            let clean = clean.split_whitespace().collect::<Vec<_>>().join(" ");
            let title = if clean.is_empty() {
                "Untitled project".to_owned()
            } else if clean.chars().count() > TITLE_LIMIT {
                let cut: String = clean.chars().take(TITLE_LIMIT - 1).collect();
                format!("{}…", cut.trim_end())
            } else {
                clean
            };
            (format!("{RECENT_PREFIX}{}", item.id), title)
        })
        .collect()
}

/// The project a clicked Open Recent item names.
pub fn recent_project(menu_id: &str) -> Option<&str> {
    menu_id
        .strip_prefix(RECENT_PREFIX)
        .filter(|id| is_project_id(id))
}

// -- quitting -------------------------------------------------------------------------

/// What would be lost by quitting now.
#[derive(Debug, Default)]
pub struct QuitGuard {
    unsaved: AtomicBool,
    prompting: AtomicBool,
    confirmed: AtomicBool,
}

impl QuitGuard {
    pub fn set_unsaved(&self, unsaved: bool) {
        self.unsaved.store(unsaved, Ordering::SeqCst);
    }
    pub fn unsaved(&self) -> bool {
        self.unsaved.load(Ordering::SeqCst)
    }
    pub fn confirmed(&self) -> bool {
        self.confirmed.load(Ordering::SeqCst)
    }
}

/// Job states that mean work is still in progress (the contract's non-final states).
const ACTIVE: [&str; 9] = [
    "queued",
    "probing",
    "fingerprinting",
    "proxying",
    "grouping",
    "analyzing",
    "transcribing",
    "indexing",
    "rendering",
];

/// How many jobs in `GET /v1/jobs` are still working. Diagnostic jobs don't count.
pub fn running_jobs(jobs: &Value) -> usize {
    jobs.as_array().map_or(0, |list| {
        list.iter()
            .filter(|job| {
                job.get("kind").and_then(Value::as_str) != Some("diagnostic")
                    && job
                        .get("state")
                        .and_then(Value::as_str)
                        .is_some_and(|s| ACTIVE.contains(&s))
            })
            .count()
    })
}

/// The confirmation to show before quitting, or `None` to quit straight away.
pub fn quit_prompt(running: usize, unsaved: bool) -> Option<(String, String)> {
    const AFTER: &str = "When you reopen the app, interrupted jobs continue or can be retried from Background jobs.";
    let jobs = if running == 1 {
        "1 background job is".to_owned()
    } else {
        format!("{running} background jobs are")
    };
    match (running, unsaved) {
        (0, false) => None,
        (_, false) => Some((
            format!("Quit while {jobs} running?"),
            format!("Quitting stops {} now. {AFTER}", if running == 1 { "it" } else { "them" }),
        )),
        (0, true) => Some((
            "Quit with unsaved project edits?".to_owned(),
            "Some project edits have not been saved yet. Your last saved version and any recovered draft are kept.".to_owned(),
        )),
        (_, true) => Some((
            "Quit with work in progress?".to_owned(),
            format!("{jobs} still running, and some project edits have not been saved yet. Quitting stops the jobs now. {AFTER}"),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn accelerators() -> Vec<(&'static str, &'static str)> {
        macos_layout()
            .into_iter()
            .flat_map(|s| s.entries)
            .filter_map(|e| match e {
                Entry::Action {
                    id,
                    accelerator: Some(a),
                    ..
                } => Some((id, a)),
                _ => None,
            })
            .collect()
    }

    #[test]
    fn menus_follow_the_macos_order() {
        let titles: Vec<_> = macos_layout().iter().map(|s| s.title).collect();
        assert_eq!(
            titles,
            [
                "OpenWorld Moments",
                "File",
                "Edit",
                "View",
                "Window",
                "Help"
            ]
        );
        let app = &macos_layout()[0];
        assert_eq!(app.entries.first(), Some(&Entry::Native(Native::About)));
        assert!(matches!(
            app.entries.last(),
            Some(Entry::Action { id: QUIT, .. })
        ));
    }

    #[test]
    fn standard_macos_shortcuts_are_where_people_expect_them() {
        let keys = accelerators();
        let find = |id: &str| keys.iter().find(|(i, _)| *i == id).map(|(_, a)| *a);
        assert_eq!(find("app.settings"), Some("Cmd+,"));
        assert_eq!(find(QUIT), Some("Cmd+Q"));
        assert_eq!(find("edit.find"), Some("Cmd+F"));
        assert_eq!(find("file.new_project"), Some("Cmd+N"));
        // Every shortcut uses Command and none is used twice.
        let mut seen = std::collections::HashSet::new();
        for (id, accelerator) in &keys {
            assert!(accelerator.starts_with("Cmd+"), "{id}: {accelerator}");
            assert!(seen.insert(*accelerator), "{accelerator} is used twice");
        }
    }

    #[test]
    fn app_shortcuts_leave_system_and_text_editing_shortcuts_alone() {
        // Owned by AppKit items or the system: Hide, Hide Others, Minimize, Close Window,
        // full screen, text editing, Spotlight and app switching.
        let reserved = [
            "Cmd+H",
            "Cmd+Alt+H",
            "Cmd+M",
            "Cmd+W",
            "Cmd+Ctrl+F",
            "Cmd+Z",
            "Cmd+Shift+Z",
            "Cmd+X",
            "Cmd+C",
            "Cmd+V",
            "Cmd+A",
            "Cmd+Space",
            "Cmd+Tab",
            "Cmd+`",
            // In-app shortcuts kept from M13/M22/M26: Search and the editor.
            "Cmd+K",
            "Cmd+S",
        ];
        for (id, accelerator) in accelerators() {
            assert!(!reserved.contains(&accelerator), "{id} takes {accelerator}");
        }
        let natives: Vec<_> = macos_layout()
            .into_iter()
            .flat_map(|s| s.entries)
            .filter_map(|e| match e {
                Entry::Native(n) if n != Native::Separator => Some(n),
                _ => None,
            })
            .collect();
        for needed in [
            Native::Undo,
            Native::Redo,
            Native::Cut,
            Native::Copy,
            Native::Paste,
            Native::SelectAll,
            Native::Hide,
            Native::Minimize,
            Native::CloseWindow,
            Native::Fullscreen,
        ] {
            assert!(natives.contains(&needed), "{needed:?} is missing");
        }
    }

    #[test]
    fn every_ui_action_is_handled_by_the_ui() {
        let ui = include_str!("../../src/menu.ts");
        for id in action_ids() {
            if [QUIT, HELP_GUIDES, HELP_MAC_GUIDE].contains(&id) {
                continue; // the host performs these
            }
            assert!(
                ui.contains(&format!("\"{id}\"")),
                "menu.ts does not handle {id}"
            );
        }
        let unique: std::collections::HashSet<_> = action_ids().into_iter().collect();
        assert_eq!(unique.len(), action_ids().len(), "duplicate menu IDs");
    }

    #[test]
    fn only_fixed_guide_pages_and_settings_panes_open() {
        assert_eq!(guide_url("macos").unwrap(), format!("{GUIDES}macos.md"));
        for bad in ["", "../README", "https://example.com", "macos.md", "MACOS"] {
            assert_eq!(guide_url(bad), None, "{bad}");
            assert_eq!(settings_url(bad), None, "{bad}");
        }
        for topic in [
            "index",
            "macos",
            "macos-install",
            "macos-permissions",
            "macos-troubleshooting",
            "accessibility",
            "diagnostics",
            "phone",
        ] {
            assert!(guide_url(topic).unwrap().starts_with("https://github.com/"));
        }
        for pane in ["files-and-folders", "local-network"] {
            let url = settings_url(pane).unwrap();
            assert!(url.starts_with("x-apple.systempreferences:"), "{url}");
        }
        // Nothing that could turn protection off is reachable.
        assert_eq!(settings_url("firewall-off"), None);
        assert_eq!(settings_url("gatekeeper"), None);
    }

    #[test]
    fn guide_anchors_exist_in_the_guides() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../docs/guides");
        for topic in [
            "macos-install",
            "macos-permissions",
            "macos-troubleshooting",
        ] {
            let url = guide_url(topic).unwrap();
            let (page, anchor) = url.strip_prefix(GUIDES).unwrap().split_once('#').unwrap();
            let text = std::fs::read_to_string(root.join(page)).unwrap();
            let heading = anchor.replace('-', " ");
            assert!(
                text.lines()
                    .any(|l| l.starts_with('#') && l.to_lowercase().ends_with(&heading)),
                "{page} has no heading for #{anchor}"
            );
        }
    }

    const P1: &str = "prj_01JCBQ00000000000000000001";
    const P2: &str = "prj_01JCBQ00000000000000000002";

    fn recent(id: &str, title: &str) -> RecentProject {
        RecentProject {
            id: id.to_owned(),
            title: title.to_owned(),
        }
    }

    #[test]
    fn open_recent_keeps_valid_projects_only() {
        let entries = recent_entries(&[
            recent(P1, "Heist\u{202e}gone wrong\n"),
            recent("../../etc", "Sneaky"),
            recent("ast_01JCBQ00000000000000000001", "A clip"),
            recent(P1, "Duplicate"),
            recent(P2, "   "),
        ]);
        assert_eq!(
            entries,
            vec![
                (format!("recent:{P1}"), "Heist gone wrong".to_owned()),
                (format!("recent:{P2}"), "Untitled project".to_owned()),
            ]
        );
        let long = "x".repeat(200);
        let entries = recent_entries(&[recent(P1, &long)]);
        assert_eq!(entries[0].1.chars().count(), TITLE_LIMIT);
        assert!(entries[0].1.ends_with('…'));
        let many: Vec<_> = (0..25)
            .map(|i| recent(&format!("prj_01JCBQ000000000000000000{i:02}"), "p"))
            .collect();
        assert_eq!(recent_entries(&many).len(), RECENT_LIMIT);
        assert!(recent_entries(&[]).is_empty());
    }

    #[test]
    fn recent_items_resolve_only_to_projects() {
        assert_eq!(recent_project(&format!("recent:{P1}")), Some(P1));
        assert_eq!(recent_project(P1), None);
        assert_eq!(recent_project("recent:prj_bad"), None);
        assert_eq!(recent_project("recent:"), None);
        assert_eq!(recent_project(RECENT_CLEAR), None);
    }

    #[test]
    fn running_jobs_count_work_in_progress_only() {
        let jobs = serde_json::json!([
            {"kind": "import", "state": "probing"},
            {"kind": "render", "state": "rendering"},
            {"kind": "render", "state": "ready"},
            {"kind": "import", "state": "failed"},
            {"kind": "import", "state": "cancelled"},
            {"kind": "diagnostic", "state": "queued"},
            {"kind": "transcribe", "state": "queued"},
            {"state": "rendering"},
            "garbage",
        ]);
        assert_eq!(running_jobs(&jobs), 4);
        assert_eq!(running_jobs(&serde_json::json!({"error": 1})), 0);
        assert_eq!(running_jobs(&Value::Null), 0);
    }

    #[test]
    fn quitting_asks_only_when_something_would_be_lost() {
        assert_eq!(quit_prompt(0, false), None);
        let (title, detail) = quit_prompt(1, false).unwrap();
        assert_eq!(title, "Quit while 1 background job is running?");
        assert!(detail.contains("stops it now"), "{detail}");
        let (title, detail) = quit_prompt(3, false).unwrap();
        assert_eq!(title, "Quit while 3 background jobs are running?");
        assert!(detail.contains("stops them now"), "{detail}");
        let (title, detail) = quit_prompt(0, true).unwrap();
        assert!(title.contains("unsaved"), "{title}");
        assert!(detail.contains("draft"), "{detail}");
        let (title, detail) = quit_prompt(2, true).unwrap();
        assert_eq!(title, "Quit with work in progress?");
        assert!(detail.starts_with("2 background jobs"), "{detail}");
    }

    #[test]
    fn quit_guard_tracks_unsaved_edits() {
        let guard = QuitGuard::default();
        assert!(!guard.unsaved() && !guard.confirmed());
        guard.set_unsaved(true);
        assert!(guard.unsaved());
        guard.set_unsaved(false);
        assert!(!guard.unsaved());
    }
}

// -- Tauri integration (macOS) ---------------------------------------------------------

#[cfg(target_os = "macos")]
pub use native::{build, on_close_requested, on_menu_event, set_recent};

#[cfg(target_os = "macos")]
mod native {
    use super::*;
    use tauri::menu::{
        AboutMetadata, IsMenuItem, Menu, MenuEvent, MenuItem, PredefinedMenuItem, Submenu,
    };
    use tauri::{AppHandle, Emitter, Manager, Runtime};

    /// Open Recent, kept so its items can be replaced.
    pub struct RecentMenu<R: Runtime>(pub Submenu<R>);

    fn native<R: Runtime>(
        app: &AppHandle<R>,
        item: Native,
        about: &AboutMetadata<'static>,
    ) -> tauri::Result<PredefinedMenuItem<R>> {
        use Native::*;
        match item {
            About => {
                PredefinedMenuItem::about(app, Some("About OpenWorld Moments"), Some(about.clone()))
            }
            Services => PredefinedMenuItem::services(app, None),
            Hide => PredefinedMenuItem::hide(app, Some("Hide OpenWorld Moments")),
            HideOthers => PredefinedMenuItem::hide_others(app, None),
            ShowAll => PredefinedMenuItem::show_all(app, None),
            Undo => PredefinedMenuItem::undo(app, None),
            Redo => PredefinedMenuItem::redo(app, None),
            Cut => PredefinedMenuItem::cut(app, None),
            Copy => PredefinedMenuItem::copy(app, None),
            Paste => PredefinedMenuItem::paste(app, None),
            SelectAll => PredefinedMenuItem::select_all(app, None),
            CloseWindow => PredefinedMenuItem::close_window(app, None),
            Minimize => PredefinedMenuItem::minimize(app, None),
            Zoom => PredefinedMenuItem::maximize(app, Some("Zoom")),
            Fullscreen => PredefinedMenuItem::fullscreen(app, None),
            BringAllToFront => PredefinedMenuItem::bring_all_to_front(app, None),
            Separator => PredefinedMenuItem::separator(app),
        }
    }

    /// The About panel: name, version and licence, and that this is a preview.
    fn about<R: Runtime>(app: &AppHandle<R>) -> AboutMetadata<'static> {
        let version = app.package_info().version.to_string();
        AboutMetadata {
            name: Some("OpenWorld Moments".to_owned()),
            version: Some(version.clone()),
            short_version: Some(version),
            copyright: app.config().bundle.copyright.clone(),
            credits: Some(
                "Preview build for macOS. Not a supported release yet. \
                 Help ▸ Save Diagnostics Report shows how this copy is signed.\n\n\
                 Unofficial community project. Not affiliated with or endorsed by Rockstar Games."
                    .to_owned(),
            ),
            ..Default::default()
        }
    }

    /// Build the macOS menu bar.
    pub fn build<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<Menu<R>> {
        let about = about(app);
        let menu = Menu::new(app)?;
        for section in macos_layout() {
            let submenu = Submenu::with_id(app, section.id, section.title, true)?;
            for entry in section.entries {
                match entry {
                    Entry::Action {
                        id,
                        label,
                        accelerator,
                    } => submenu.append(&MenuItem::with_id(app, id, label, true, accelerator)?)?,
                    Entry::Native(item) => submenu.append(&native(app, item, &about)?)?,
                    Entry::Recent => {
                        let recent = Submenu::with_id(app, RECENT, "Open Recent", true)?;
                        fill_recent(app, &recent, &[])?;
                        submenu.append(&recent)?;
                        app.manage(RecentMenu(recent));
                    }
                }
            }
            match section.id {
                "window" => submenu.set_as_windows_menu_for_nsapp()?,
                "help" => submenu.set_as_help_menu_for_nsapp()?,
                _ => {}
            }
            menu.append(&submenu)?;
        }
        Ok(menu)
    }

    fn fill_recent<R: Runtime>(
        app: &AppHandle<R>,
        submenu: &Submenu<R>,
        items: &[RecentProject],
    ) -> tauri::Result<()> {
        for item in submenu.items()? {
            submenu.remove(&item as &dyn IsMenuItem<R>)?;
        }
        let entries = recent_entries(items);
        for (id, title) in &entries {
            submenu.append(&MenuItem::with_id(app, id, title, true, None::<&str>)?)?;
        }
        if !entries.is_empty() {
            submenu.append(&PredefinedMenuItem::separator(app)?)?;
        }
        submenu.append(&MenuItem::with_id(
            app,
            RECENT_CLEAR,
            "Clear Menu",
            !entries.is_empty(),
            None::<&str>,
        )?)?;
        Ok(())
    }

    /// Replace Open Recent with the UI's list.
    pub fn set_recent<R: Runtime>(
        app: &AppHandle<R>,
        items: &[RecentProject],
    ) -> tauri::Result<()> {
        let Some(recent) = app.try_state::<RecentMenu<R>>() else {
            return Ok(());
        };
        let submenu = recent.0.clone();
        let items = items.to_vec();
        let handle = app.clone();
        // Menus belong to the main thread.
        app.run_on_main_thread(move || {
            let _ = fill_recent(&handle, &submenu, &items);
        })
    }

    pub fn on_menu_event<R: Runtime>(app: &AppHandle<R>, event: MenuEvent) {
        let id = event.id().as_ref();
        if id == QUIT {
            request_quit(app);
        } else if id == HELP_GUIDES || id == HELP_MAC_GUIDE {
            let topic = if id == HELP_GUIDES { "index" } else { "macos" };
            if let Some(url) = guide_url(topic) {
                let _ = crate::platform::open_url(&url);
            }
        } else if let Some(project) = recent_project(id) {
            let _ = app.emit(EVENT, format!("{RECENT_PREFIX}{project}"));
        } else if id == RECENT_CLEAR || action_ids().contains(&id) {
            let _ = app.emit(EVENT, id);
        }
    }

    /// The window's close button and Close Window quit the app (it has one window), so
    /// they ask the same question as Quit.
    pub fn on_close_requested<R: Runtime>(window: &tauri::Window<R>, api: &tauri::CloseRequestApi) {
        let app = window.app_handle();
        let confirmed = app
            .try_state::<QuitGuard>()
            .is_some_and(|guard| guard.confirmed());
        if !confirmed {
            api.prevent_close();
            request_quit(app);
        }
    }

    /// Quit now, or ask first when jobs are running or edits are unsaved.
    pub fn request_quit<R: Runtime>(app: &AppHandle<R>) {
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            let Some(guard) = app.try_state::<QuitGuard>() else {
                app.exit(0);
                return;
            };
            if guard.prompting.swap(true, Ordering::SeqCst) {
                return; // a question is already on screen
            }
            let worker = app
                .try_state::<Option<crate::worker::Supervisor>>()
                .and_then(|s| s.inner().clone());
            let running = match worker {
                Some(worker) => worker
                    .list_jobs()
                    .await
                    .map(|jobs| running_jobs(&jobs))
                    .unwrap_or(0),
                None => 0,
            };
            let Some((title, detail)) = quit_prompt(running, guard.unsaved()) else {
                guard.confirmed.store(true, Ordering::SeqCst);
                app.exit(0);
                return;
            };
            use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
            let handle = app.clone();
            app.dialog()
                .message(detail)
                .title(title)
                .kind(MessageDialogKind::Warning)
                .buttons(MessageDialogButtons::OkCancelCustom(
                    "Quit".to_owned(),
                    "Cancel".to_owned(),
                ))
                .show(move |quit| {
                    if let Some(guard) = handle.try_state::<QuitGuard>() {
                        guard.prompting.store(false, Ordering::SeqCst);
                        if quit {
                            guard.confirmed.store(true, Ordering::SeqCst);
                        }
                    }
                    if quit {
                        handle.exit(0);
                    }
                });
        });
    }
}
