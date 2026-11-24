# SPDX-License-Identifier: AGPL-3.0-or-later
"""M37: macOS signing, notarization and DMG packaging, without Apple's tools.

Every external program is replaced by a recording fake, so these run on any OS and
cover the paths a real run cannot reach without credentials: Developer ID signing,
rejected notarization, an expired API key and secret redaction.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import plistlib
import re
import shutil
import struct
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARM64 = 0x0100000C
EXECUTE, DYLIB, BUNDLE = 2, 6, 8


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


signing = _load("sign_and_package", ROOT / "scripts/macos/sign-and-package.py")

P12 = b"\x30\x82fake-pkcs12-certificate-and-private-key"
# Fake values, assembled at run time so secret scanners see no key material in the source.
PEM = "PRIVATE " + "KEY"
P8 = f"-----BEGIN {PEM}-----\n{'Q' * 40}FAKEBODY\n-----END {PEM}-----\n".encode()
ENV = {
    "MACOS_CERTIFICATE_P12_BASE64": base64.b64encode(P12).decode(),
    "MACOS_CERTIFICATE_PASSWORD": "horse" * 5,
    "APPLE_TEAM_ID": "ABCDE12345",
    "APPLE_API_KEY_ID": "KEY1234567",
    "APPLE_API_ISSUER_ID": "69a6de7e-1111-2222-3333-444455556666",
    "APPLE_API_KEY_P8_BASE64": base64.b64encode(P8).decode(),
}
SECRETS = [
    ENV["MACOS_CERTIFICATE_P12_BASE64"],
    ENV["MACOS_CERTIFICATE_PASSWORD"],
    ENV["APPLE_API_KEY_ID"],
    ENV["APPLE_API_ISSUER_ID"],
    ENV["APPLE_API_KEY_P8_BASE64"],
    "Q" * 40 + "FAKEBODY",
]
IDENTITY_HASH = "0123456789ABCDEF0123456789ABCDEF01234567"
VERSION = "0.1.0-alpha.37"


def macho(filetype: int = EXECUTE, cpu: int = ARM64) -> bytes:
    command = struct.pack("<IIIIII", 0x32, 24, 1, 14 << 16, 14 << 16, 0)
    header = struct.pack("<IiIIIIII", 0xFEEDFACF, cpu, 0, filetype, 1, len(command), 0, 0)
    return header + command + b"\0" * 64


def fat(*slices: bytes) -> bytes:
    table, body = b"", b""
    offset = 8 + 20 * len(slices)
    for data in slices:
        (cpu,) = struct.unpack_from("<i", data, 4)
        table += struct.pack(">iiIII", cpu, 0, offset + len(body), len(data), 0)
        body += data
    return struct.pack(">II", 0xCAFEBABE, len(slices)) + table + body


def make_app(root: Path, *, version: str = VERSION, frozen_as: str = VERSION) -> Path:
    app: Path = root / signing.APP
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "MacOS" / "openworld-moments-desktop").write_bytes(macho())
    (contents / "Resources").mkdir()
    (contents / "Resources" / "icon.icns").write_bytes(b"icns")
    info = {
        "CFBundleExecutable": "openworld-moments-desktop",
        "CFBundleIdentifier": signing.BUNDLE_ID,
        "CFBundleShortVersionString": version,
        "CFBundleIconFile": "icon.icns",
        "LSMinimumSystemVersion": "14.0",
        "LSApplicationCategoryType": "public.app-category.video",
        "NSHumanReadableCopyright": "© OpenWorld Moments contributors",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    runtime = contents / "Resources" / "runtime"
    files = {
        "owm-worker": macho(),
        "tools/ffmpeg": macho(),
        "tools/ffprobe": macho(),
        "_internal/libpython3.12.dylib": macho(DYLIB),
        "_internal/pydantic_core/_pydantic_core.cpython-312-darwin.so": macho(BUNDLE),
        "data/profile.json": b"{}",
        "THIRD_PARTY_NOTICES.txt": b"notices",
    }
    for name, data in files.items():
        (runtime / name).parent.mkdir(parents=True, exist_ok=True)
        (runtime / name).write_bytes(data)
    inventory = {
        "platform": "macos",
        "architecture": "arm64",
        "application": frozen_as,
        "files": {name: signing.shell_digest(runtime / name) for name in sorted(files)},
    }
    (runtime / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    return app


class Fake:
    """Records every command and imitates Apple's tools well enough for the flow."""

    def __init__(
        self,
        *,
        team: str | None = None,
        notary_status: str = "Accepted",
        notary_issues: list[dict[str, str]] | None = None,
        notary_failure: str | None = None,
        gatekeeper_accepts: bool = False,
    ) -> None:
        self.team = team
        self.notary_status = notary_status
        self.notary_issues = notary_issues
        self.notary_failure = notary_failure
        self.gatekeeper_accepts = gatekeeper_accepts
        self.calls: list[tuple[list[str], bool]] = []
        self.key_files: list[Path] = []

    def details(self) -> str:
        if self.team is None:
            return (
                "Signature=adhoc\nCodeDirectory v=20500 flags=0x10002(adhoc,runtime)\n"
                "TeamIdentifier=not set"
            )
        return (
            "Authority=Developer ID Application: Example (ABCDE12345)\n"
            "Authority=Developer ID Certification Authority\nAuthority=Apple Root CA\n"
            "Timestamp=23 Nov 2026\nCodeDirectory v=20500 flags=0x10000(runtime)\n"
            f"TeamIdentifier={self.team}"
        )

    def secret(
        self, label: str, args: Sequence[str], *, check: bool = True, timeout: float = 1800
    ) -> Any:
        assert label and not any(secret in label for secret in SECRETS)
        return self._run(list(args), sensitive=True, check=check)

    def __call__(self, args: Sequence[str], *, check: bool = True, timeout: float = 1800) -> Any:
        return self._run(list(args), sensitive=False, check=check)

    def _run(self, args: list[str], *, sensitive: bool, check: bool) -> Any:
        self.calls.append((args, sensitive))
        program = Path(args[0]).name
        out, err, code = "", "", 0
        if program == "codesign" and "--force" in args:
            target = Path(args[-1])
            if target.is_file():
                with target.open("ab") as stream:
                    stream.write(b"__signature__")
        elif program == "codesign" and "--display" in args:
            out = "" if "--entitlements" in args else self.details()
        elif program == "ditto":
            source, target = Path(args[-2]), Path(args[-1])
            if source.is_dir() and "-c" not in args:
                shutil.copytree(source, target, symlinks=True)
            else:
                target.write_bytes(b"zip")
        elif program == "hdiutil" and args[1] == "create":
            Path(args[-1]).write_bytes(b"dmg image")
        elif program == "spctl":
            code = 0 if self.gatekeeper_accepts else 3
            err = (
                f"{args[-1]}: accepted\nsource=Notarized Developer ID"
                if self.gatekeeper_accepts
                else f"{args[-1]}: rejected"
            )
        elif program == "security":
            if args[1] == "create-keychain":
                Path(args[-1]).write_bytes(b"keychain")
            elif args[1] == "delete-keychain":
                Path(args[-1]).unlink(missing_ok=True)
            elif args[1] == "list-keychains" and "-s" not in args:
                out = '    "/Users/runner/Library/Keychains/login.keychain-db"\n'
            elif args[1] == "find-identity":
                out = (
                    f'  1) {IDENTITY_HASH} "Developer ID Application: Example (ABCDE12345)"\n'
                    "     1 valid identities found\n"
                )
        elif program == "xcrun" and args[1] == "notarytool":
            key = Path(args[args.index("--key") + 1])
            self.key_files.append(key)
            assert key.is_file()
            if args[2] == "submit":
                if self.notary_failure:
                    code, err = 1, self.notary_failure
                else:
                    out = json.dumps({"id": "sub-1", "status": self.notary_status})
            elif args[2] == "log":
                log = {
                    "status": self.notary_status,
                    "issues": self.notary_issues,
                    "ticketContents": [{"path": "x", "cdhash": "00"}]
                    if self.notary_status == "Accepted"
                    else None,
                }
                Path(args[-1]).write_text(json.dumps(log))
        if check and code:
            raise signing.SigningError(f"{program} failed ({code}): {err}")
        return signing.Result(code, out, err)

    def programs(self) -> list[str]:
        return [" ".join([Path(a[0]).name, *a[1:3]]) for a, _ in self.calls]


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    """The architecture audit reads real Mach-O files; its own tests live in
    test_macos_shell.py. Here it passes, and git reports a fixed commit."""
    monkeypatch.setattr(signing.shell, "verify_bundle", lambda *a, **k: [])
    monkeypatch.setattr(signing.shell, "git_commit", lambda: "0123456789abcdef")


def run_package(
    tmp_path: Path, fake: Fake, env: dict[str, str], **kwargs: Any
) -> tuple[dict[str, Any], list[str]]:
    app = make_app(tmp_path / "build")
    echoed: list[str] = []
    report = signing.package(
        "arm64", app, tmp_path / "out", env, echo=echoed.append, runner=lambda _r: fake, **kwargs
    )
    return report, echoed


# -- credentials and redaction ------------------------------------------------------------


def test_no_credentials_means_ad_hoc_and_all_means_developer_id() -> None:
    assert signing.credentials_from({}) is None
    assert signing.credentials_from({name: "  " for name in ENV}) is None
    credentials = signing.credentials_from(ENV)
    assert credentials is not None
    assert credentials.p12 == P12 and credentials.key_p8 == P8
    assert credentials.team_id == "ABCDE12345"
    assert repr(credentials) == "Credentials(<redacted>)"
    assert set(signing.CREDENTIAL_NAMES) == set(ENV)


@pytest.mark.parametrize("missing", sorted(ENV))
def test_partial_credentials_fail_and_name_only_the_variables(missing: str) -> None:
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(signing.CredentialError) as error:
        signing.credentials_from(env)
    message = str(error.value)
    assert missing in message
    assert not any(secret in message for secret in [*SECRETS, ENV["APPLE_TEAM_ID"]])


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("APPLE_TEAM_ID", "not-a-team", "malformed"),
        ("APPLE_API_ISSUER_ID", "issuer", "malformed"),
        ("MACOS_CERTIFICATE_P12_BASE64", "%%% not base64 %%%", "base64"),
        ("APPLE_API_KEY_P8_BASE64", base64.b64encode(b"just text").decode(), "private key"),
    ],
)
def test_malformed_credentials_are_refused_without_echoing(
    name: str, value: str, expected: str
) -> None:
    with pytest.raises(signing.CredentialError, match=expected) as error:
        signing.credentials_from({**ENV, name: value})
    assert value not in str(error.value)


def test_redaction_covers_every_secret_but_keeps_the_public_team_id() -> None:
    credentials = signing.credentials_from(ENV)
    assert credentials is not None
    redact = signing.Redactor(credentials.secret_values())
    text = " ".join([*SECRETS, ENV["APPLE_TEAM_ID"], "ok"])
    scrubbed = redact(text)
    assert not any(secret in scrubbed for secret in SECRETS)
    assert ENV["APPLE_TEAM_ID"] in scrubbed and scrubbed.endswith("ok")
    assert signing.Redactor(["abc"])("abc") == "abc"  # too short to be a secret


def test_runner_withholds_sensitive_arguments_and_scrubs_output() -> None:
    secret = ENV["MACOS_CERTIFICATE_PASSWORD"]
    echoed: list[str] = []
    run = signing.Runner(signing.Redactor([secret]), echoed.append)
    script = f"import sys; print({secret!r}); print({secret!r}, file=sys.stderr)"
    result = run.secret("python secret-test", [sys.executable, "-c", script, "-P", secret])
    assert secret not in result.stdout and secret not in result.stderr
    assert "[REDACTED]" in result.stdout
    assert echoed and all(secret not in line for line in echoed)
    # The log line of a secret command is the label alone, never derived from args.
    assert echoed[0] == "$ python secret-test [arguments withheld]"
    with pytest.raises(signing.SigningError) as error:
        run.secret("python secret-test", [sys.executable, "-c", script + "; sys.exit(4)"])
    assert secret not in str(error.value) and "(4)" in str(error.value)
    with pytest.raises(signing.SigningError, match="missing-program"):
        run(["/nonexistent/missing-program"])
    with pytest.raises(signing.SigningError) as missing:
        run.secret("security import", [f"/nonexistent/{secret}"])
    assert secret not in str(missing.value) and str(missing.value).startswith("security import:")
    # Other commands are echoed in full, but still scrubbed.
    run([sys.executable, "-c", "pass", secret])
    assert secret not in echoed[-1] and "[REDACTED]" in echoed[-1]


# -- signing order and commands ------------------------------------------------------------


def test_signing_plan_is_inside_out_and_ends_with_the_app(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    nested = app / "Contents" / "Frameworks" / "Helper.framework" / "Versions" / "A"
    nested.mkdir(parents=True)
    (nested / "Helper").write_bytes(macho(DYLIB))
    (app / "Contents" / "Resources" / "runtime" / "tools" / "link").symlink_to("ffmpeg")
    plan = [p.relative_to(app).as_posix() if p != app else "." for p in signing.signing_plan(app)]
    assert plan[-1] == "."
    assert "Contents/MacOS/openworld-moments-desktop" not in plan  # signed with the bundle
    assert "Contents/Resources/runtime/tools/link" not in plan
    assert "Contents/Resources/runtime/data/profile.json" not in plan
    depths = [len(Path(p).parts) for p in plan[:-1]]
    assert depths == sorted(depths, reverse=True)
    framework = plan.index("Contents/Frameworks/Helper.framework")
    assert plan.index("Contents/Frameworks/Helper.framework/Versions/A/Helper") < framework
    worker = plan.index("Contents/Resources/runtime/owm-worker")
    assert plan.index("Contents/Resources/runtime/_internal/libpython3.12.dylib") < worker


def test_mach_o_file_types(tmp_path: Path) -> None:
    for name, data, expected in [
        ("exe", macho(EXECUTE), EXECUTE),
        ("lib", macho(DYLIB), DYLIB),
        ("so", macho(BUNDLE), BUNDLE),
        ("fat", fat(macho(EXECUTE)), EXECUTE),
        ("text", b"#!/bin/sh\necho hi\n", None),
        ("short", b"\xcf\xfa", None),
    ]:
        (tmp_path / name).write_bytes(data)
        assert signing.macho_filetype(tmp_path / name) == expected, name
    assert signing.macho_filetype(tmp_path / "absent") is None


def test_codesign_commands_for_ad_hoc_developer_id_and_dmg(tmp_path: Path) -> None:
    entitlements = tmp_path / "e.plist"
    adhoc = signing.codesign_command(tmp_path / "ffmpeg", signing.ADHOC, entitlements, "id.ffmpeg")
    assert adhoc[:4] == ["/usr/bin/codesign", "--force", "--sign", "-"]
    assert "--timestamp=none" in adhoc and "--timestamp" not in adhoc
    assert adhoc[adhoc.index("--options") + 1] == "runtime"
    assert adhoc[adhoc.index("--identifier") + 1] == "id.ffmpeg"
    identity = signing.Identity(IDENTITY_HASH, "ABCDE12345", tmp_path / "k.keychain-db")
    release = signing.codesign_command(tmp_path / "x.app", identity, None)
    assert release[3] == IDENTITY_HASH and "--timestamp" in release
    assert "--keychain" in release and "--entitlements" not in release
    dmg = signing.codesign_command(tmp_path / "a.dmg", identity, None)
    assert "--options" not in dmg


def test_code_identifiers_are_stable(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    runtime = app / "Contents" / "Resources" / "runtime"
    ident = signing.code_identifier
    assert (
        ident(runtime / "tools/ffmpeg", app, signing.BUNDLE_ID)
        == f"{signing.BUNDLE_ID}.runtime.ffmpeg"
    )
    so = runtime / "_internal/pydantic_core/_pydantic_core.cpython-312-darwin.so"
    assert ident(so, app, signing.BUNDLE_ID) == f"{signing.BUNDLE_ID}.runtime.pydantic-core"
    assert ident(app, app, signing.BUNDLE_ID) is None


# -- entitlements -------------------------------------------------------------------------


def test_shipped_entitlements_are_the_reviewed_minimum() -> None:
    assert signing.check_entitlements_file(signing.ENTITLEMENTS) == []
    assert plistlib.loads(signing.ENTITLEMENTS.read_bytes()) == {}
    assert signing.check_adhoc_entitlements_file(signing.ADHOC_ENTITLEMENTS) == []
    adhoc = plistlib.loads(signing.ADHOC_ENTITLEMENTS.read_bytes())
    assert set(adhoc) == set(signing.ADHOC_ONLY_ENTITLEMENTS)
    # The ad hoc exception is never acceptable as the release file.
    assert signing.check_entitlements_file(signing.ADHOC_ENTITLEMENTS)


@pytest.mark.parametrize(
    "key",
    [
        "com.apple.security.app-sandbox",
        "com.apple.security.get-task-allow",
        "com.apple.security.cs.allow-jit",
        "com.apple.security.device.camera",
    ],
)
def test_unreviewed_or_forbidden_entitlements_fail(tmp_path: Path, key: str) -> None:
    path = tmp_path / "e.plist"
    path.write_bytes(plistlib.dumps({key: True}))
    assert any(key in p for p in signing.check_entitlements_file(path))
    assert any(key in p for p in signing.check_adhoc_entitlements_file(path))


def test_library_validation_exception_is_ad_hoc_and_worker_only(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    worker = app / "Contents/Resources/runtime/owm-worker"
    ffmpeg = app / "Contents/Resources/runtime/tools/ffmpeg"
    key = "com.apple.security.cs.disable-library-validation"
    release = signing.Identity(IDENTITY_HASH, "ABCDE12345")
    assert key in signing.allowed_entitlements(worker, app, signing.ADHOC)
    assert key not in signing.allowed_entitlements(ffmpeg, app, signing.ADHOC)
    assert key not in signing.allowed_entitlements(worker, app, release)
    base, adhoc = Path("base.plist"), Path("adhoc.plist")
    choose = signing.entitlements_for
    assert choose(worker, app, signing.ADHOC, base, adhoc) == adhoc
    assert choose(worker, app, release, base, adhoc) == base
    assert choose(ffmpeg, app, signing.ADHOC, base, adhoc) == base
    lib = app / "Contents/Resources/runtime/_internal/libpython3.12.dylib"
    assert choose(lib, app, signing.ADHOC, base, adhoc) is None
    assert choose(app, app, signing.ADHOC, base, adhoc) == base


# -- inventory ----------------------------------------------------------------------------


def test_inventory_is_rehashed_for_signed_code_only(tmp_path: Path) -> None:
    app = make_app(tmp_path)
    runtime = app / "Contents/Resources/runtime"
    with (runtime / "owm-worker").open("ab") as stream:
        stream.write(b"signature")
    assert signing.inventory_problems(app)  # the worker would refuse to start
    assert signing.rehash_inventory(runtime, {"owm-worker", "tools/ffmpeg"}) == ["owm-worker"]
    assert signing.inventory_problems(app) == []

    (runtime / "data/profile.json").write_text('{"changed": true}')
    with pytest.raises(signing.SigningError, match="not code"):
        signing.rehash_inventory(runtime, {"owm-worker"})
    (runtime / "data/profile.json").write_text("{}")
    (runtime / "data/new.json").write_text("{}")
    with pytest.raises(signing.SigningError, match="changed shape"):
        signing.rehash_inventory(runtime, {"owm-worker"})


# -- verification -------------------------------------------------------------------------


def test_signature_details_are_checked_against_the_intended_identity() -> None:
    release = signing.Identity(IDENTITY_HASH, "ABCDE12345")
    good = Fake(team="ABCDE12345").details()
    assert signing.signature_problems(good, release) == []
    assert signing.signature_problems(Fake().details(), signing.ADHOC) == []
    assert "signed by another team" in signing.signature_problems(
        good.replace("ABCDE12345", "ZZZZZ99999"), release
    )
    assert "no secure timestamp" in signing.signature_problems(
        good.replace("Timestamp=23 Nov 2026\n", ""), release
    )
    unsigned = "Signature=adhoc\nflags=0x20002(adhoc,linker-signed)"
    problems = signing.signature_problems(unsigned, signing.ADHOC)
    assert "Hardened Runtime is not enabled" in problems
    assert "still carries the linker's signature" in problems
    assert signing.signature_problems(good, signing.ADHOC) == ["not signed ad hoc"]
    assert signing.signature_problems("Signature=adhoc", signing.ADHOC, hardened=False) == []


def test_notarization_must_be_accepted_with_no_issues() -> None:
    accepted = {"status": "Accepted", "issues": None, "ticketContents": [{"path": "a"}]}
    assert signing.notarization_problems("Accepted", accepted) == []
    warned = {**accepted, "issues": [{"severity": "warning", "path": "a/b", "message": "m"}]}
    assert signing.notarization_problems("Accepted", warned) == ["warning: a/b: m"]
    invalid = {
        "status": "Invalid",
        "issues": [{"severity": "error", "path": "x", "message": "unsigned"}],
    }
    problems = signing.notarization_problems("Invalid", invalid)
    assert "submission status is Invalid" in problems and "error: x: unsigned" in problems
    assert "no notarization log was retrieved" in signing.notarization_problems("Accepted", None)
    empty = {"status": "Accepted", "issues": []}
    assert "the log lists no ticket contents" in signing.notarization_problems("Accepted", empty)


def test_notary_failures_are_explained() -> None:
    expired = signing.explain_notary_failure(
        "Error: HTTP status code: 401. Unable to authenticate."
    )
    assert "Rotate" in expired and "APPLE_API_KEY_P8_BASE64" in expired
    assert "Agreement" in signing.explain_notary_failure("HTTP status code: 403 agreement missing")
    assert "boom" in signing.explain_notary_failure("boom")


def test_exactly_one_developer_id_identity_must_match_the_team() -> None:
    line = f'  1) {IDENTITY_HASH} "Developer ID Application: Example (ABCDE12345)"'
    assert signing.pick_identity(line, "ABCDE12345") == IDENTITY_HASH
    with pytest.raises(signing.CredentialError, match="found 0"):
        signing.pick_identity(line, "ZZZZZ99999")
    other = f'  2) {"F" * 40} "Apple Development: Example (ABCDE12345)"'
    with pytest.raises(signing.CredentialError, match="found 0"):
        signing.pick_identity(other, "ABCDE12345")
    twice = line + "\n" + line.replace("1)", "2)").replace(IDENTITY_HASH, "E" * 40)
    with pytest.raises(signing.CredentialError, match="found 2"):
        signing.pick_identity(twice, "ABCDE12345")


def test_metadata_must_be_stable_and_consistent(tmp_path: Path) -> None:
    app = make_app(tmp_path / "a")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert signing.metadata_problems(app, info) == []
    stale = make_app(tmp_path / "b", frozen_as="0.1.0-alpha.35")
    assert any("frozen as" in p for p in signing.metadata_problems(stale, info))
    renamed = {**info, "CFBundleIdentifier": "com.example.other"}
    assert any("CFBundleIdentifier" in p for p in signing.metadata_problems(app, renamed))
    bare = {
        k: v
        for k, v in info.items()
        if k not in ("NSHumanReadableCopyright", "LSApplicationCategoryType")
    }
    assert len(signing.metadata_problems(app, bare)) == 2


# -- names and checksums ----------------------------------------------------------------------


def test_dmg_names_follow_adr_0008_and_ad_hoc_builds_cannot_pass_for_releases() -> None:
    assert signing.dmg_name(VERSION, "arm64", "abc", notarized=True) == (
        "OpenWorld-Moments_0.1.0-alpha.37_macOS_arm64.dmg"
    )
    assert signing.dmg_name(VERSION, "x86_64", "0123456789", notarized=False) == (
        "OpenWorld-Moments_0.1.0-alpha.37+0123456_macOS_x86_64_adhoc-unnotarized.dmg"
    )
    with pytest.raises(ValueError, match="architecture"):
        signing.dmg_name(VERSION, "universal", "abc", notarized=True)


def test_checksums_cover_every_file(tmp_path: Path) -> None:
    (tmp_path / "a.dmg").write_bytes(b"a")
    (tmp_path / "sbom.json").write_text("{}")
    (tmp_path / "sub").mkdir()
    path = signing.write_checksums(tmp_path)
    lines = path.read_text().splitlines()
    assert [line.split("  ")[1] for line in lines] == ["a.dmg", "sbom.json"]
    assert lines[0].split("  ")[0] == signing.shell_digest(tmp_path / "a.dmg")
    signing.write_checksums(tmp_path)  # idempotent: never lists itself
    assert "checksums.txt" not in path.read_text()


# -- the whole flow -----------------------------------------------------------------------


@pytest.mark.usefixtures("patched")
def test_without_credentials_the_build_is_ad_hoc_and_clearly_not_publishable(
    tmp_path: Path,
) -> None:
    fake = Fake()
    report, echoed = run_package(tmp_path, fake, {})
    assert echoed[0] == signing.SKIP_NOTICE
    assert report["mode"] == "adhoc" and report["signed_by"] == "ad hoc"
    assert report["notarization"] == "SKIPPED: no Apple credentials"
    assert report["stapled"] is False and report["publishable"] is False
    assert report["dmg"]["name"].endswith("_macOS_arm64_adhoc-unnotarized.dmg")
    assert report["gatekeeper"]["app"]["accepted"] is False
    assert report["signing"]["inventory_rehashed"] == 5
    assert report["signing"]["adhoc_exceptions"] == ["Contents/Resources/runtime/owm-worker"]
    programs = fake.programs()
    assert not any(p.startswith(("xcrun", "security")) for p in programs)
    out = tmp_path / "out"
    assert (out / report["dmg"]["name"]).is_file()
    assert (out / "THIRD_PARTY_NOTICES.txt").is_file()
    assert json.loads((out / "signing-report-arm64.json").read_text())["publishable"] is False
    # Only the worker got the ad hoc library-validation exception.
    adhoc = [a for a, _ in fake.calls if str(signing.ADHOC_ENTITLEMENTS) in a]
    assert [Path(a[-1]).name for a in adhoc] == ["owm-worker"]


def test_release_gate_refuses_before_doing_anything_without_credentials(tmp_path: Path) -> None:
    fake = Fake()
    with pytest.raises(signing.NotPublishable):
        run_package(tmp_path, fake, {}, require_notarized=True)
    assert fake.calls == []


def test_partial_credentials_stop_the_package(tmp_path: Path) -> None:
    env = {k: v for k, v in ENV.items() if k != "APPLE_API_KEY_P8_BASE64"}
    with pytest.raises(signing.CredentialError, match="APPLE_API_KEY_P8_BASE64"):
        run_package(tmp_path, Fake(), env)
    with pytest.raises(signing.CredentialError, match="none of"):
        run_package(tmp_path / "2", Fake(), {}, mode="developer-id")


@pytest.mark.usefixtures("patched")
def test_ad_hoc_mode_ignores_credentials(tmp_path: Path) -> None:
    fake = Fake()
    report, _ = run_package(tmp_path, fake, ENV, mode="adhoc")
    assert report["mode"] == "adhoc"
    assert not any(a[0].endswith("security") for a, _ in fake.calls)


def assert_no_secrets(fake: Fake, tmp_path: Path, *texts: str) -> None:
    for args, sensitive in fake.calls:
        if any(secret in " ".join(args) for secret in SECRETS):
            assert sensitive, f"{args[:2]} carries a secret but was not run with secret()"
    for path in (tmp_path / "out").rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            assert not any(s.encode() in content for s in SECRETS), path.name
    for text in texts:
        assert not any(secret in text for secret in SECRETS)


@pytest.mark.usefixtures("patched")
def test_developer_id_flow_signs_notarizes_staples_in_order(tmp_path: Path) -> None:
    fake = Fake(team="ABCDE12345", gatekeeper_accepts=True)
    report, echoed = run_package(tmp_path, fake, ENV, require_notarized=True)
    assert report["publishable"] is True and report["stapled"] is True
    assert report["mode"] == "developer-id"
    assert report["signed_by"] == "Developer ID Application (ABCDE12345)"
    assert report["dmg"]["name"] == "OpenWorld-Moments_0.1.0-alpha.37_macOS_arm64.dmg"
    assert report["notarization"]["app"]["log"] == "notarization-app-arm64.json"
    assert signing.SKIP_NOTICE not in echoed
    programs = fake.programs()
    signs = [i for i, p in enumerate(programs) if p.startswith("codesign --force")]
    app_sign = next(
        i
        for i, (a, _) in enumerate(fake.calls)
        if a[0].endswith("codesign") and a[-1].endswith(".app")
    )
    dmg_create = programs.index("hdiutil create -volname")
    submits = [i for i, p in enumerate(programs) if p == "xcrun notarytool submit"]
    staples = [i for i, p in enumerate(programs) if p == "xcrun stapler staple"]
    assert max(i for i in signs if i < app_sign) < app_sign  # nested code first
    assert app_sign < submits[0] < staples[0] < dmg_create < submits[1] < staples[1]
    dmg_sign = next(i for i in signs if fake.calls[i][0][-1].endswith(".dmg"))
    assert dmg_create < dmg_sign < submits[1]
    # Every codesign used the imported identity, with a timestamp, from the temporary keychain.
    for index in signs:
        args = fake.calls[index][0]
        assert args[3] == IDENTITY_HASH and "--timestamp" in args and "--keychain" in args
        assert str(signing.ADHOC_ENTITLEMENTS) not in args
    # Credentials are cleaned up: the key file, the certificate and the keychain.
    assert fake.key_files and not any(p.exists() for p in fake.key_files)
    deleted = [i for i, p in enumerate(programs) if p.startswith("security delete-keychain")]
    assert deleted and deleted[0] > staples[1]
    assert_no_secrets(fake, tmp_path, *echoed)


@pytest.mark.usefixtures("patched")
@pytest.mark.parametrize(
    ("fake", "message"),
    [
        (Fake(team="ABCDE12345", notary_status="Invalid"), "submission status is Invalid"),
        (
            Fake(
                team="ABCDE12345",
                notary_issues=[{"severity": "warning", "path": "a", "message": "no timestamp"}],
            ),
            "warning: a: no timestamp",
        ),
        (
            Fake(
                team="ABCDE12345",
                notary_failure="Error: HTTP status code: 401. Unable to authenticate. "
                + ENV["APPLE_API_KEY_ID"],
            ),
            "Rotate",
        ),
    ],
    ids=["rejected", "warnings", "expired-key"],
)
def test_failed_notarization_stops_publication_and_cleans_up(
    tmp_path: Path, fake: Fake, message: str
) -> None:
    with pytest.raises(signing.SigningError, match=message) as error:
        run_package(tmp_path, fake, ENV, require_notarized=True)
    programs = fake.programs()
    assert "hdiutil create -volname" not in programs  # nothing to publish was built
    assert any(p.startswith("security delete-keychain") for p in programs)
    assert fake.key_files and not any(p.exists() for p in fake.key_files)
    assert_no_secrets(fake, tmp_path, str(error.value))


@pytest.mark.usefixtures("patched")
def test_gatekeeper_rejecting_a_notarized_build_is_not_publishable(tmp_path: Path) -> None:
    with pytest.raises(signing.NotPublishable, match="Gatekeeper"):
        run_package(tmp_path, Fake(team="ABCDE12345", gatekeeper_accepts=False), ENV)


@pytest.mark.usefixtures("patched")
def test_signatures_from_another_team_fail_verification(tmp_path: Path) -> None:
    with pytest.raises(signing.SigningError, match="another team"):
        run_package(tmp_path, Fake(team="ZZZZZ99999"), ENV)


@pytest.mark.usefixtures("patched")
def test_a_wrong_architecture_bundle_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        signing.shell, "verify_bundle", lambda *a, **k: ["owm-worker: x86_64, expected arm64"]
    )
    fake = Fake()
    with pytest.raises(signing.SigningError, match="architecture audit"):
        run_package(tmp_path, fake, {})
    assert fake.calls == []


# -- command line and CI ----------------------------------------------------------------------


def test_check_credentials_reports_the_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "github-output"
    assert signing.main(["check-credentials"], {"GITHUB_OUTPUT": str(output)}) == 0
    assert output.read_text() == "mode=adhoc\n"
    assert "SKIPPED" in capsys.readouterr().out
    assert signing.main(["check-credentials"], {**ENV, "GITHUB_OUTPUT": str(output)}) == 0
    assert output.read_text().endswith("mode=developer-id\n")
    printed = capsys.readouterr().out
    assert not any(secret in printed for secret in SECRETS)
    partial = {"APPLE_TEAM_ID": "ABCDE12345"}
    assert signing.main(["check-credentials"], partial) == signing.EXIT_FAILED


def test_tauri_metadata_and_versions_agree() -> None:
    tauri = ROOT / "apps/desktop/src-tauri"
    base = json.loads((tauri / "tauri.conf.json").read_text())
    mac = json.loads((tauri / "tauri.macos.conf.json").read_text())
    packaged = json.loads((tauri / "tauri.macos-packaged.conf.json").read_text())
    assert base["identifier"] == signing.BUNDLE_ID
    assert "icons/icon.icns" in base["bundle"]["icon"]
    assert mac["bundle"]["category"] == "Video"
    assert mac["bundle"]["copyright"].strip()
    assert mac["bundle"]["macOS"]["hardenedRuntime"] is True
    assert "signingIdentity" not in mac["bundle"]["macOS"]  # signing is sign-and-package.py's job
    freeze = (ROOT / "scripts/macos/freeze-worker.py").read_text("utf-8")
    match = re.search(r'"application": "([^"]+)"', freeze)
    assert match and match.group(1) == packaged["version"]


def workflow(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text("utf-8")


def test_only_the_protected_release_workflow_sees_apple_secrets() -> None:
    release = workflow("macos-release.yml")
    for name in signing.CREDENTIAL_NAMES:
        assert f"secrets.{name}" in release
    assert "environment: macos-release" in release
    assert "pull_request" not in release
    assert "--require-notarized" in release
    used = set(re.findall(r"secrets\.([A-Z0-9_]+)", release))
    assert used == set(signing.CREDENTIAL_NAMES)
    ci = workflow("ci.yml")
    assert not any(f"secrets.{name}" in ci for name in signing.CREDENTIAL_NAMES)
    assert "sign-and-package.py package" in ci and "verify-dmg" in ci
