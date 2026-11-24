# Publication, rollback and triage — 0.1.0-alpha.32

This page is for the maintainer and triagers. It was written, and the draft release
prepared, **before publication**; nothing here has been published.

## 1. Publishing the draft (maintainer only)

The draft GitHub release `v0.1.0-alpha.32` was created by the M32 session with the
installer set built by the pull request's CI. Pull-request builds are **not attested**,
and the draft's target is the PR head commit. Before clicking **Publish**:

1. Merge the M32 pull request.
2. Wait for the `CI` run on the merge commit to pass. Its *Desktop production build
   (Windows)* job builds the same release set and attests every file.
3. Replace the draft's assets with that run's attested set and point the tag at the merge
   commit (run from a clean checkout of `main`; `<run>` is the main CI run id):

   ```bash
   gh run view <run> --json databaseId,headSha,event,status,conclusion,url,jobs > ci-run.json
   uv run --directory services/media-worker python ../../scripts/release/release_check.py ci-summary ../../ci-run.json
   gh run download <run> -n Windows-x64-alpha-candidate -D release-set
   uv run --directory services/media-worker python ../../scripts/release/release_check.py \
     verify-artifacts ../../release-set --version 0.1.0-alpha.32 \
     --report ../../release-verification.json --markdown ../../release-hashes.md
   gh attestation verify release-set/OpenWorld-Moments_0.1.0-alpha.32_Windows_x64-setup.exe \
     --repo heetdalsania/openworld-moments
   gh release view v0.1.0-alpha.32 --json assets --jq '.assets[].name' \
     | xargs -I{} gh release delete-asset v0.1.0-alpha.32 {} --yes
   gh release upload v0.1.0-alpha.32 release-set/* release-verification.json
   gh release edit v0.1.0-alpha.32 --target "$(gh run view <run> --json headSha --jq .headSha)"
   ```

   Both `release_check.py` commands must exit 0. Paste `release-hashes.md` into the
   qualification report's *Published artifact hashes* section in a follow-up commit.
4. Confirm the private vulnerability reporting setting (**Settings → Code security →
   Private vulnerability reporting**). It was **off** when the draft was prepared;
   `SECURITY.md` documents the interim contact route either way.
5. Optionally create the triage labels (section 4).
6. Remove the "Draft — maintainer steps" box at the top of the release text, keep
   **Set as a pre-release** ticked, and leave **Set as the latest release** unticked
   if GitHub offers it for a pre-release. Then **Publish**. GitHub creates the tag
   `v0.1.0-alpha.32` on the target commit at that moment.
7. Run the post-publication smoke test ([M40 section E](../../milestones/M40-windows-deferred-verification.md#e-windows-public-alpha-m32))
   when a Windows PC is available. It is deferred by maintainer decision and does not
   block publication.

## 2. Migration notes

| From | What happens | Data |
|---|---|---|
| Nothing (new user) | Fresh per-user install | New library in `%APPDATA%\org.openworldmoments.desktop\library` |
| `0.1.0-alpha.29` (M29 test candidate) | In-place upgrade; the installer offers to uninstall the old version first and keeps the library | No SQL migration: schema stays **19**. Documents written from now on use contract **1.27**; 1.23–1.26 documents stay readable. Phone transfer and model downloads need a fresh opt-in (M31). Installed speech models are kept. |
| Development builds older than schema 19 | Migrations run once at first launch, after a pre-upgrade backup of the database is written | The backup is kept; a library from a *newer* schema is refused rather than opened |

No data format in this release removes or rewrites user data. Source footage is never
modified by any version.

## 3. Rollback

### For a user

1. The installer refuses to install an older version over a newer one
   (`allowDowngrades: false`).
2. Older builds are not guaranteed to read documents a newer build wrote. Keep a copy of
   the library from **before** the upgrade: quit the app, then copy
   `%APPDATA%\org.openworldmoments.desktop\library` somewhere safe.
3. To roll back: uninstall from **Settings → Apps** with **Delete the application data**
   unticked, replace the library folder with your copy, and install the older
   installer after checking its checksum.
4. For 0.1.0-alpha.32 there is no earlier public release; the only earlier build is
   the 0.1.0-alpha.29 test candidate. Uninstalling (and keeping or deleting the library)
   is the supported way back.

### For the maintainer (a bad release)

- **Never move or reuse a published tag.** Fix forward with `0.1.0-alpha.33` (bump
  `apps/desktop/src-tauri/tauri.packaged.conf.json`; every script reads it).
- If the installer is harmful (data loss, security), immediately edit the release to
  remove the installer asset (or convert the release back to a draft), add a notice at
  the top of the release text, and open a pinned issue labelled `release-blocker`.
- If it is merely broken, keep it published with a notice and link the fix.
- Security problems follow [SECURITY.md](../../../SECURITY.md): fix privately, then
  publish an advisory with the fixed release.

## 4. Triage labels

[`.github/labels.json`](../../../.github/labels.json) lists the labels the issue templates
and triage use (`bug`, `detector`, `installer`, `phone-upload`, `media`, `data-loss`,
`regression`, `release-blocker`, `needs-repro`, `footage-policy`,
`alpha:0.1.0-alpha.32`, …). Labels missing from the repository can be created by the
maintainer with:

```bash
jq -c '.[]' .github/labels.json | while read -r label; do
  gh label create "$(jq -r .name <<<"$label")" --color "$(jq -r .color <<<"$label")" \
    --description "$(jq -r .description <<<"$label")" --force
done
```

`--force` updates labels that already exist. (`detector` and `milestone` are used by
existing issue templates but did not exist in the repository when M32 was prepared.)

### Triage rules

| Report | Labels | Response |
|---|---|---|
| Lost or changed library, project or source data | `bug`, `data-loss`, `release-blocker` | Same day; consider pulling the installer |
| Install, repair, upgrade or uninstall fails | `bug`, `installer` | Ask for Windows edition/build, account type and a diagnostics report |
| SmartScreen or antivirus warning only | `installer` | Expected for the unsigned alpha; point to checksum verification |
| Detector misses or false events | `detector` | Ask for profile/detector versions and timestamps; never footage |
| Leaked footage, game files or official assets attached | `footage-policy` | Remove the attachment, then lock if repeated |
| Security vulnerability posted publicly | — | Hide the content, move it to a private advisory per SECURITY.md |
| Works in 0.1.0-alpha.29 but not in 0.1.0-alpha.32 | `regression` | Bisect against the M29 candidate |

Every report from this release also gets `alpha:0.1.0-alpha.32`.
