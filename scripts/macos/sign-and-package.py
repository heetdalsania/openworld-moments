# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign, package, notarize and verify a native macOS build (M37).

    python3 scripts/macos/sign-and-package.py check-credentials
    python3 scripts/macos/sign-and-package.py package --arch arm64 [--app PATH]
        [--mode auto|adhoc|developer-id] [--require-notarized]
    python3 scripts/macos/sign-and-package.py verify-dmg DMG --arch arm64
        [--expect adhoc|notarized] [--no-run]
    python3 scripts/macos/sign-and-package.py checksums DIR

`package` takes the app built by `build-shell.py` and, inside out:

1. signs every nested Mach-O file (runtime libraries and extension modules, FFmpeg,
   FFprobe, the frozen worker) with the Hardened Runtime, deepest first;
2. re-hashes `Resources/runtime/inventory.json`, because signing rewrites those files
   and the worker refuses a runtime whose hashes do not match (M34);
3. signs the app bundle (the Tauri host) with the reviewed entitlements;
4. with Apple credentials: notarizes the app, inspects the log and staples the ticket;
5. builds `OpenWorld-Moments_<version>_macOS_<arch>.dmg` (app plus an `Applications`
   link), signs it and, with credentials, notarizes and staples it too;
6. verifies every signature, the architecture audit and Gatekeeper, and writes
   `signing-report-<arch>.json` next to the DMG.

Credentials come only from the environment (see CREDENTIAL_NAMES). With none, the
build is signed ad hoc (`codesign -s -`), named `..._adhoc-unnotarized.dmg`, and the
notarization steps are reported as SKIPPED; such a DMG must never be published. Some
but not all credentials is a configuration error. `--require-notarized` (the release
gate) exits 3 unless the DMG is Developer ID signed, notarized, stapled and accepted
by Gatekeeper. Secret values are never printed: commands that carry them are logged
by program name only, and all program output is scrubbed of them.

Every program is started by argument array, never through a shell.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / "output" / "packaging" / "macos"
ENTITLEMENTS = ROOT / "apps" / "desktop" / "src-tauri" / "macos" / "entitlements.plist"
ADHOC_ENTITLEMENTS = ENTITLEMENTS.with_name("entitlements-adhoc.plist")
APP = "OpenWorld Moments.app"
#: Never change it: macOS keys permissions, Keychain items and preferences to it.
BUNDLE_ID = "org.openworldmoments.desktop"
VOLUME = "OpenWorld Moments"

#: GitHub Actions secrets (names, never values) in the protected `macos-release`
#: environment. All six or none.
CREDENTIAL_NAMES = (
    "MACOS_CERTIFICATE_P12_BASE64",  # Developer ID Application certificate + key, .p12
    "MACOS_CERTIFICATE_PASSWORD",  # the .p12 export password
    "APPLE_TEAM_ID",  # 10-character Apple team identifier
    "APPLE_API_KEY_ID",  # App Store Connect API key ID (notarization)
    "APPLE_API_ISSUER_ID",  # App Store Connect issuer UUID
    "APPLE_API_KEY_P8_BASE64",  # the AuthKey_<id>.p8 private key, base64
)

#: Entitlement keys the reviewed file may contain. Empty: the Hardened Runtime needs
#: no exception (docs/platforms/macos-signing.md#entitlements).
ALLOWED_ENTITLEMENTS: frozenset[str] = frozenset()
#: Keys that must never appear, whatever the allowlist says.
FORBIDDEN_ENTITLEMENTS = frozenset(
    {
        "com.apple.security.app-sandbox",  # ADR-0008: no App Sandbox for the alpha
        "com.apple.security.get-task-allow",  # debugger attachment; notarization rejects it
        "com.apple.security.cs.disable-library-validation",
        "com.apple.security.cs.allow-dyld-environment-variables",
        "com.apple.security.cs.disable-executable-page-protection",
        "com.apple.security.cs.allow-jit",
        "com.apple.security.cs.allow-unsigned-executable-memory",
    }
)

#: Ad hoc builds only: an ad hoc signature has no Team ID, so library validation would
#: stop the worker loading its own ad hoc libpython. Developer ID builds sign every
#: library with one team and must not carry this exception (it is forbidden there).
ADHOC_ONLY_ENTITLEMENTS = frozenset({"com.apple.security.cs.disable-library-validation"})
ADHOC_EXCEPTION_TARGETS = frozenset({"Contents/Resources/runtime/owm-worker"})

BUNDLE_SUFFIXES = (".app", ".framework", ".bundle", ".xpc", ".appex", ".plugin")
MH_EXECUTE = 2
SKIP_NOTICE = (
    "SKIPPED: Developer ID signing, notarization and stapling. No Apple credentials are "
    "configured (" + ", ".join(CREDENTIAL_NAMES) + "). The build is signed ad hoc; the DMG "
    "is not notarized, Gatekeeper will reject it, and it must not be published."
)

EXIT_FAILED, EXIT_USAGE, EXIT_NOT_PUBLISHABLE = 1, 2, 3


def _load(name: str, path: Path) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(HERE))
from macho import is_macho  # noqa: E402

shell = _load("build_shell", HERE / "build-shell.py")


class SigningError(RuntimeError):
    """A step failed; the message is already free of secret values."""


class CredentialError(SigningError):
    pass


class NotPublishable(SigningError):
    """The release gate refused: not Developer ID signed, notarized and stapled."""


# --- credentials and redaction -------------------------------------------------------

TEAM_ID = re.compile(r"[A-Z0-9]{10}")
KEY_ID = re.compile(r"[A-Z0-9]{8,12}")
ISSUER_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass(frozen=True, repr=False)
class Credentials:
    p12: bytes
    p12_password: str
    team_id: str
    key_id: str
    issuer_id: str
    key_p8: bytes
    raw: tuple[str, ...] = field(default=())

    def __repr__(self) -> str:  # never let a traceback or log print the values
        return "Credentials(<redacted>)"

    def secret_values(self) -> list[str]:
        """Everything to scrub from output. The team ID is public (it is in every
        signature) and stays readable."""
        values = [*self.raw, self.p12_password, self.key_id, self.issuer_id]
        text = self.key_p8.decode("utf-8", "replace")
        values += [line.strip() for line in text.splitlines() if "-----" not in line]
        return [v for v in values if v and v != self.team_id]


def _decode(name: str, value: str) -> bytes:
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError):
        raise CredentialError(f"{name} is not valid base64 (value not shown)") from None


def credentials_from(env: Mapping[str, str]) -> Credentials | None:
    """The Apple credentials in `env`: all of them, none (None) or an error naming the
    missing or malformed variables, never their values."""
    present = [n for n in CREDENTIAL_NAMES if env.get(n, "").strip()]
    if not present:
        return None
    missing = [n for n in CREDENTIAL_NAMES if n not in present]
    if missing:
        raise CredentialError(
            "incomplete Apple signing credentials: "
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not set "
            f"while {', '.join(present)} {'is' if len(present) == 1 else 'are'}. "
            "Set all of them in the macos-release environment or none."
        )
    value = {n: env[n].strip() for n in CREDENTIAL_NAMES}
    for name, pattern in (
        ("APPLE_TEAM_ID", TEAM_ID),
        ("APPLE_API_KEY_ID", KEY_ID),
        ("APPLE_API_ISSUER_ID", ISSUER_ID),
    ):
        if not pattern.fullmatch(value[name]):
            raise CredentialError(f"{name} is malformed (value not shown)")
    p12 = _decode("MACOS_CERTIFICATE_P12_BASE64", value["MACOS_CERTIFICATE_P12_BASE64"])
    key = _decode("APPLE_API_KEY_P8_BASE64", value["APPLE_API_KEY_P8_BASE64"])
    if b"PRIVATE KEY" not in key:
        raise CredentialError("APPLE_API_KEY_P8_BASE64 is not a .p8 private key")
    return Credentials(
        p12=p12,
        p12_password=value["MACOS_CERTIFICATE_PASSWORD"],
        team_id=value["APPLE_TEAM_ID"],
        key_id=value["APPLE_API_KEY_ID"],
        issuer_id=value["APPLE_API_ISSUER_ID"],
        key_p8=key,
        raw=(value["MACOS_CERTIFICATE_P12_BASE64"], value["APPLE_API_KEY_P8_BASE64"]),
    )


class Redactor:
    MASK = "[REDACTED]"

    def __init__(self, values: Sequence[str] = ()) -> None:
        self._values: list[str] = []
        for value in values:
            self.add(value)

    def add(self, value: str) -> None:
        if len(value) >= 4 and value not in self._values:
            self._values.append(value)
            self._values.sort(key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, self.MASK)
        return text


# --- running programs ------------------------------------------------------------------


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def text(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


class Run(Protocol):
    def __call__(
        self, args: Sequence[str], *, check: bool = True, timeout: float = 1800
    ) -> Result: ...

    def secret(
        self, label: str, args: Sequence[str], *, check: bool = True, timeout: float = 1800
    ) -> Result: ...


class Runner:
    """Runs a program by argument array. Output is scrubbed of secret values.

    A command that carries a secret must use `secret(label, args)`, where the label is
    a literal such as "security import". That method never logs or reports anything
    derived from `args`: its log line and any error are built from the label alone.
    Only `__call__`, for commands without a secret, echoes its (scrubbed) arguments."""

    def __init__(self, redact: Redactor, echo: Callable[[str], None] = print) -> None:
        self.redact = redact
        self.echo = echo

    def __call__(self, args: Sequence[str], *, check: bool = True, timeout: float = 1800) -> Result:
        name = Path(args[0]).name
        self.echo(f"$ {self.redact(shlex.join([name, *args[1:]]))}")
        try:
            done = subprocess.run(  # noqa: S603 - argument array, no shell
                list(args), capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SigningError(f"{name}: {self.redact(str(error))}") from None
        return self._finish(name, done, check)

    def secret(
        self, label: str, args: Sequence[str], *, check: bool = True, timeout: float = 1800
    ) -> Result:
        self.echo(f"$ {label} [arguments withheld]")
        try:
            done = subprocess.run(  # noqa: S603 - argument array, no shell
                list(args), capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SigningError(f"{label}: {type(error).__name__}") from None
        return self._finish(label, done, check)

    def _finish(self, name: str, done: subprocess.CompletedProcess[str], check: bool) -> Result:
        result = Result(done.returncode, self.redact(done.stdout), self.redact(done.stderr))
        if check and result.returncode != 0:
            raise SigningError(f"{name} failed ({result.returncode}): {tail(result.text)}")
        return result


def tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-lines:]) or "(no output)"


# --- what gets signed ------------------------------------------------------------------


def macho_filetype(path: Path) -> int | None:
    """The Mach-O file type (2 = executable, 6 = dylib, 8 = bundle) of a thin file or
    of the first slice of a universal one; None if it is not Mach-O."""
    try:
        with path.open("rb") as stream:
            head = stream.read(4096)
    except OSError:
        return None
    if len(head) < 16:
        return None
    if head[:4] in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):  # universal
        if len(head) < 16:
            return None
        offset = int.from_bytes(head[16:20], "big")
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                head = stream.read(16)
        except OSError:
            return None
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return int.from_bytes(head[12:16], "little")
    if head[:4] in (b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"):
        return int.from_bytes(head[12:16], "big")
    return None


def main_executable(app: Path) -> Path:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    return app / "Contents" / "MacOS" / str(info["CFBundleExecutable"])


def signing_plan(app: Path) -> list[Path]:
    """Every code item to sign, inside out: nested Mach-O files and bundles deepest
    first, the app bundle last. The host executable is signed with the bundle."""
    host = main_executable(app)
    items: list[Path] = []
    for path in (app / "Contents").rglob("*"):
        if path.is_symlink():
            continue  # a link inside the bundle points at a file signed on its own
        nested_bundle = path.is_dir() and path.suffix in BUNDLE_SUFFIXES
        if nested_bundle or (path.is_file() and path != host and is_macho(path)):
            items.append(path)
    items.sort(key=lambda p: (-len(p.relative_to(app).parts), p.as_posix()))
    return [*items, app]


def wants_entitlements(item: Path) -> bool:
    """Entitlements belong to executables (and the app), not to libraries."""
    if item.is_dir():
        return item.suffix == ".app"
    return macho_filetype(item) == MH_EXECUTE


def code_identifier(item: Path, app: Path, bundle_id: str) -> str | None:
    """A stable identifier for nested code (`<bundle id>.runtime.ffmpeg`), instead of the
    linker's hash-suffixed one; bundles keep the identifier from their Info.plist."""
    if item.is_dir():
        return None
    stem = item.name.split(".")[0].lstrip("_") or "code"
    safe = "".join(c if c.isalnum() or c == "-" else "-" for c in stem)
    return f"{bundle_id}.runtime.{safe}"


def adhoc_exception(item: Path, app: Path) -> bool:
    return item.relative_to(app).as_posix() in ADHOC_EXCEPTION_TARGETS


@dataclass(frozen=True)
class Identity:
    """`-` for ad hoc, otherwise the SHA-1 of a Developer ID Application identity."""

    name: str
    team_id: str | None = None
    keychain: Path | None = None

    @property
    def adhoc(self) -> bool:
        return self.name == "-"

    def describe(self) -> str:
        return "ad hoc" if self.adhoc else f"Developer ID Application ({self.team_id})"


ADHOC = Identity("-")


def codesign_command(
    target: Path, identity: Identity, entitlements: Path | None, identifier: str | None = None
) -> list[str]:
    command = ["/usr/bin/codesign", "--force", "--sign", identity.name]
    if identifier is not None:
        command += ["--identifier", identifier]
    if identity.keychain is not None:
        command += ["--keychain", str(identity.keychain)]
    if target.suffix != ".dmg":
        command += ["--options", "runtime"]
    # Ad hoc signatures cannot carry a secure timestamp; Developer ID ones must.
    command.append("--timestamp=none" if identity.adhoc else "--timestamp")
    if entitlements is not None:
        command += ["--entitlements", str(entitlements)]
    command.append(str(target))
    return command


def check_entitlements_file(
    path: Path,
    allowed: frozenset[str] = ALLOWED_ENTITLEMENTS,
    forbidden: frozenset[str] = FORBIDDEN_ENTITLEMENTS,
) -> list[str]:
    try:
        document = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as error:
        return [f"{path.name}: {error}"]
    if not isinstance(document, dict):
        return [f"{path.name}: not a dictionary"]
    return [
        f"{path.name}: {key} is "
        + ("forbidden" if key in forbidden else "not in the reviewed allowlist")
        for key in sorted(document)
        if key in forbidden or key not in allowed
    ]


def check_adhoc_entitlements_file(path: Path) -> list[str]:
    return check_entitlements_file(
        path, ADHOC_ONLY_ENTITLEMENTS, FORBIDDEN_ENTITLEMENTS - ADHOC_ONLY_ENTITLEMENTS
    )


def allowed_entitlements(item: Path, app: Path, identity: Identity) -> frozenset[str]:
    if identity.adhoc and adhoc_exception(item, app):
        return ALLOWED_ENTITLEMENTS | ADHOC_ONLY_ENTITLEMENTS
    return ALLOWED_ENTITLEMENTS - FORBIDDEN_ENTITLEMENTS


def rehash_inventory(runtime: Path, signed: set[str]) -> list[str]:
    """Update the runtime inventory after signing; return the files whose hash changed.
    Only signed code may change, and no file may appear or disappear."""
    path = runtime / "inventory.json"
    document = json.loads(path.read_text("utf-8"))
    listed: dict[str, str] = document["files"]
    on_disk = {
        p.relative_to(runtime).as_posix(): shell_digest(p)
        for p in sorted(runtime.rglob("*"))
        if p.is_file() and not p.is_symlink() and p != path
    }
    if set(on_disk) != set(listed):
        unlisted = sorted(set(on_disk) - set(listed))[:3]
        absent = sorted(set(listed) - set(on_disk))[:3]
        raise SigningError(f"runtime changed shape while signing: new {unlisted}, gone {absent}")
    changed = [name for name in listed if listed[name] != on_disk[name]]
    unexpected = sorted(set(changed) - signed)
    if unexpected:
        raise SigningError(f"signing changed files that are not code: {unexpected[:5]}")
    document["files"] = {name: on_disk[name] for name in listed}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return changed


def shell_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def entitlements_for(
    item: Path, app: Path, identity: Identity, entitlements: Path, adhoc_entitlements: Path
) -> Path | None:
    if not wants_entitlements(item):
        return None
    if identity.adhoc and adhoc_exception(item, app):
        return adhoc_entitlements
    return entitlements


def sign_app(
    app: Path,
    identity: Identity,
    run: Run,
    entitlements: Path,
    adhoc_entitlements: Path = ADHOC_ENTITLEMENTS,
) -> dict[str, Any]:
    plan = signing_plan(app)
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    bundle_id = str(info["CFBundleIdentifier"])
    runtime = app / "Contents" / "Resources" / "runtime"
    signed: set[str] = set()
    for item in plan[:-1]:
        chosen = entitlements_for(item, app, identity, entitlements, adhoc_entitlements)
        run(codesign_command(item, identity, chosen, code_identifier(item, app, bundle_id)))
        if item.is_relative_to(runtime):
            signed.add(item.relative_to(runtime).as_posix())
    changed = rehash_inventory(runtime, signed) if runtime.is_dir() else []
    run(codesign_command(app, identity, entitlements))
    return {
        "order": [p.relative_to(app.parent).as_posix() for p in plan],
        "inventory_rehashed": len(changed),
        "adhoc_exceptions": sorted(ADHOC_EXCEPTION_TARGETS) if identity.adhoc else [],
    }


# --- verification ----------------------------------------------------------------------

FLAGS = re.compile(r"flags=0x[0-9a-f]+\(([^)]*)\)")


def signature_problems(details: str, identity: Identity, *, hardened: bool = True) -> list[str]:
    """Check one `codesign --display --verbose=4` output against the intended identity."""
    problems = []
    if identity.adhoc:
        if "Signature=adhoc" not in details:
            problems.append("not signed ad hoc")
    else:
        if "Authority=Developer ID Application:" not in details:
            problems.append("not signed by a Developer ID Application certificate")
        if f"TeamIdentifier={identity.team_id}" not in details:
            problems.append("signed by another team")
        if "Timestamp=" not in details:
            problems.append("no secure timestamp")
    if hardened:
        flags = FLAGS.search(details)
        if not flags or "runtime" not in flags.group(1).split(","):
            problems.append("Hardened Runtime is not enabled")
        if flags and "linker-signed" in flags.group(1).split(","):
            problems.append("still carries the linker's signature")
    return problems


def verify_signatures(app: Path, identity: Identity, run: Run) -> dict[str, Any]:
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    problems: list[str] = []
    checked = 0
    for item in signing_plan(app):
        name = item.relative_to(app.parent).as_posix()
        details = run(["/usr/bin/codesign", "--display", "--verbose=4", str(item)]).text
        problems += [f"{name}: {p}" for p in signature_problems(details, identity)]
        if wants_entitlements(item):
            xml = run(
                ["/usr/bin/codesign", "--display", "--entitlements", "-", "--xml", str(item)]
            ).stdout.strip()
            granted = plistlib.loads(xml.encode()) if xml.startswith("<?xml") else {}
            allowed = allowed_entitlements(item, app, identity)
            problems += [
                f"{name}: entitlement {key} is not allowed"
                for key in sorted(granted)
                if key not in allowed
            ]
        checked += 1
    problems += [f"bundle: {p}" for p in inventory_problems(app)]
    if problems:
        raise SigningError("signature verification failed:\n  " + "\n  ".join(problems))
    return {"codesign_verify_deep_strict": "pass", "items_checked": checked}


def inventory_problems(app: Path) -> list[str]:
    """The worker's own startup check (M34): every listed file hashes as recorded."""
    runtime = app / "Contents" / "Resources" / "runtime"
    try:
        document = json.loads((runtime / "inventory.json").read_text("utf-8"))
    except (OSError, ValueError) as error:
        return [f"inventory.json: {error}"]
    return [
        f"runtime/{name}: hash differs from inventory.json"
        for name, digest in document["files"].items()
        if not (runtime / name).is_file() or shell_digest(runtime / name) != digest
    ]


def gatekeeper(path: Path, run: Run) -> dict[str, Any]:
    if path.suffix == ".dmg":
        args = ["--type", "open", "--context", "context:primary-signature"]
    else:
        args = ["--type", "execute"]
    result = run(["/usr/sbin/spctl", "--assess", *args, "--verbose=4", str(path)], check=False)
    source = re.search(r"source=(.+)", result.text)
    return {
        "accepted": result.returncode == 0,
        "source": source.group(1).strip() if source else None,
        "detail": tail(result.text, 4).replace(str(path.parent) + "/", ""),
    }


# --- notarization ----------------------------------------------------------------------


def write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def explain_notary_failure(text: str) -> str:
    lowered = text.lower()
    if any(s in lowered for s in ("401", "unable to authenticate", "unauthorized", "expired")):
        return (
            "Apple refused the App Store Connect API key (expired, revoked, or a wrong key "
            "or issuer ID). Rotate APPLE_API_KEY_ID, APPLE_API_ISSUER_ID and "
            "APPLE_API_KEY_P8_BASE64; see docs/platforms/macos-signing.md#rotation."
        )
    if "403" in lowered or "agreement" in lowered:
        return (
            "Apple refused the request (HTTP 403): the team may need to accept the latest "
            "Program License Agreement in App Store Connect."
        )
    return f"notarytool failed: {tail(text, 6)}"


def notarization_problems(status: str | None, log: dict[str, Any] | None) -> list[str]:
    """Anything short of Accepted with no issues fails: Apple's warnings require action."""
    problems = []
    if status != "Accepted":
        problems.append(f"submission status is {status or 'unknown'}")
    if log is None:
        problems.append("no notarization log was retrieved")
        return problems
    if log.get("status") != "Accepted":
        problems.append(f"log status is {log.get('status') or 'unknown'}")
    for issue in log.get("issues") or []:
        problems.append(
            f"{issue.get('severity', 'issue')}: {issue.get('path', '?')}: "
            f"{issue.get('message', '')}".strip()
        )
    if log.get("status") == "Accepted" and not log.get("ticketContents"):
        problems.append("the log lists no ticket contents")
    return problems


def notarize(
    target: Path, label: str, credentials: Credentials, run: Run, work: Path, logs: Path
) -> dict[str, Any]:
    key = work / "notary-api-key.p8"
    write_private(key, credentials.key_p8)
    upload = target
    if target.suffix == ".app":
        upload = work / f"{label}.zip"
        upload.unlink(missing_ok=True)
        run(["/usr/bin/ditto", "-c", "-k", "--keepParent", str(target), str(upload)])
    auth = ["--key", str(key), "--key-id", credentials.key_id, "--issuer", credentials.issuer_id]
    try:
        result = run.secret(
            "xcrun notarytool submit",
            ["/usr/bin/xcrun", "notarytool", "submit", str(upload), *auth,
             "--wait", "--timeout", "45m", "--output-format", "json"],
            check=False, timeout=3000,
        )  # fmt: skip
        try:
            submission = json.loads(result.stdout)
        except ValueError:
            submission = None
        if not isinstance(submission, dict) or "id" not in submission:
            raise SigningError(f"notarizing {label}: {explain_notary_failure(result.text)}")
        submission_id = str(submission["id"])
        log_path = logs / f"notarization-{label}.json"
        fetched = run.secret(
            "xcrun notarytool log",
            ["/usr/bin/xcrun", "notarytool", "log", submission_id, *auth, str(log_path)],
            check=False, timeout=600,
        )  # fmt: skip
        log = None
        if fetched.returncode == 0 and log_path.is_file():
            try:
                log = json.loads(log_path.read_text("utf-8"))
            except ValueError:
                log = None
        problems = notarization_problems(submission.get("status"), log)
        if problems:
            raise SigningError(
                f"notarization of {label} was not accepted cleanly "
                f"(submission {submission_id}, log {log_path.name}):\n  " + "\n  ".join(problems)
            )
        return {"submission": submission_id, "status": "Accepted", "log": log_path.name}
    finally:
        key.unlink(missing_ok=True)
        if upload != target:
            upload.unlink(missing_ok=True)


def staple(target: Path, run: Run) -> None:
    run(["/usr/bin/xcrun", "stapler", "staple", str(target)])
    run(["/usr/bin/xcrun", "stapler", "validate", str(target)])


# --- keychain --------------------------------------------------------------------------

IDENTITY_LINE = re.compile(r'^\s*\d+\)\s+([0-9A-F]{40})\s+"(Developer ID Application: .*)"$')


def pick_identity(listing: str, team_id: str) -> str:
    matches = [
        m.group(1)
        for line in listing.splitlines()
        if (m := IDENTITY_LINE.match(line)) and m.group(2).endswith(f"({team_id})")
    ]
    if len(matches) != 1:
        raise CredentialError(
            f"expected one valid Developer ID Application identity for APPLE_TEAM_ID in "
            f"MACOS_CERTIFICATE_P12_BASE64, found {len(matches)} (expired or wrong certificate?)"
        )
    return matches[0]


def _keychain_list(run: Run) -> list[str]:
    listing = run(["/usr/bin/security", "list-keychains", "-d", "user"]).stdout
    return [line.strip().strip('"') for line in listing.splitlines() if line.strip()]


@contextlib.contextmanager
def signing_keychain(
    credentials: Credentials, run: Run, redact: Redactor, work: Path
) -> Iterator[Identity]:
    """A temporary keychain holding only the Developer ID identity, deleted afterwards
    together with the decoded certificate, whatever happens."""
    keychain = work / "owm-signing.keychain-db"
    password = secrets.token_urlsafe(32)
    redact.add(password)
    certificate = work / "developer-id.p12"
    previous: list[str] | None = None
    security = "/usr/bin/security"
    try:
        write_private(certificate, credentials.p12)
        run.secret(
            "security create-keychain",
            [security, "create-keychain", "-p", password, str(keychain)],
        )
        run([security, "set-keychain-settings", "-lut", "21600", str(keychain)])
        run.secret(
            "security unlock-keychain",
            [security, "unlock-keychain", "-p", password, str(keychain)],
        )
        run.secret(
            "security import",
            [security, "import", str(certificate), "-k", str(keychain),
             "-P", credentials.p12_password, "-f", "pkcs12", "-T", "/usr/bin/codesign"],
        )  # fmt: skip
        certificate.unlink()
        run.secret(
            "security set-key-partition-list",
            [security, "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
             "-s", "-k", password, str(keychain)],
        )  # fmt: skip
        previous = _keychain_list(run)
        run([security, "list-keychains", "-d", "user", "-s", str(keychain), *previous])
        listing = run([security, "find-identity", "-v", "-p", "codesigning", str(keychain)])
        yield Identity(
            pick_identity(listing.stdout, credentials.team_id), credentials.team_id, keychain
        )
    finally:
        certificate.unlink(missing_ok=True)
        if previous is not None:
            run([security, "list-keychains", "-d", "user", "-s", *previous], check=False)
        if keychain.exists():
            run([security, "delete-keychain", str(keychain)], check=False)


# --- DMG -------------------------------------------------------------------------------


def dmg_name(version: str, arch: str, commit: str, *, notarized: bool) -> str:
    """Release: `OpenWorld-Moments_<version>_macOS_<arch>.dmg` (ADR-0008). Anything
    else carries the commit and an `_adhoc-unnotarized` suffix so it cannot pass for one."""
    if arch not in shell.TARGETS:
        raise ValueError(f"unknown architecture {arch!r}")
    safe = "".join(c for c in version if c.isalnum() or c in ".-")
    if notarized:
        return f"OpenWorld-Moments_{safe}_macOS_{arch}.dmg"
    short = "".join(c for c in commit[:7] if c in "0123456789abcdef") or "unknown"
    return f"OpenWorld-Moments_{safe}+{short}_macOS_{arch}_adhoc-unnotarized.dmg"


def create_dmg(app: Path, dmg: Path, run: Run, work: Path) -> None:
    staging = work / "dmg-root"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    run(["/usr/bin/ditto", str(app), str(staging / APP)])
    (staging / "Applications").symlink_to("/Applications")
    dmg.unlink(missing_ok=True)
    command = [
        "/usr/bin/hdiutil", "create", "-volname", VOLUME, "-srcfolder", str(staging),
        "-fs", "HFS+", "-format", "UDZO", "-imagekey", "zlib-level=9", "-ov", str(dmg),
    ]  # fmt: skip
    for attempt in range(3):  # hdiutil is occasionally "Resource busy" on CI runners
        if run(command, check=attempt == 2).returncode == 0:
            break
    shutil.rmtree(staging)


def metadata_problems(app: Path, info: Mapping[str, Any]) -> list[str]:
    """The stable identity a replacement install relies on, and one version everywhere."""
    problems = []
    if info.get("CFBundleIdentifier") != BUNDLE_ID:
        problems.append(
            f"CFBundleIdentifier is {info.get('CFBundleIdentifier')!r}, not {BUNDLE_ID}"
        )
    if (
        info.get("CFBundleIconFile") != "icon.icns"
        or not (app / "Contents" / "Resources" / "icon.icns").is_file()
    ):
        problems.append("the app icon (icon.icns) is missing")
    if info.get("LSApplicationCategoryType") != "public.app-category.video":
        problems.append("LSApplicationCategoryType is not public.app-category.video")
    if not str(info.get("NSHumanReadableCopyright", "")).strip():
        problems.append("NSHumanReadableCopyright is missing")
    version = info.get("CFBundleShortVersionString")
    try:
        inventory = json.loads(
            (app / "Contents" / "Resources" / "runtime" / "inventory.json").read_text("utf-8")
        )
    except (OSError, ValueError):
        inventory = {}
    if inventory.get("application") != version:
        problems.append(
            f"the runtime was frozen as {inventory.get('application')!r} but the app is "
            f"{version!r}; the SBOM and DMG would disagree"
        )
    return problems


# --- the package command ---------------------------------------------------------------


def package(
    arch: str,
    app: Path,
    out: Path,
    env: Mapping[str, str],
    *,
    mode: str = "auto",
    require_notarized: bool = False,
    entitlements: Path = ENTITLEMENTS,
    adhoc_entitlements: Path = ADHOC_ENTITLEMENTS,
    echo: Callable[[str], None] = print,
    runner: Callable[[Redactor], Run] | None = None,
) -> dict[str, Any]:
    credentials = None if mode == "adhoc" else credentials_from(env)
    if mode == "developer-id" and credentials is None:
        raise CredentialError(
            "--mode developer-id: none of " + ", ".join(CREDENTIAL_NAMES) + " is set"
        )
    if credentials is None:
        echo(SKIP_NOTICE)
        if require_notarized:
            raise NotPublishable("--require-notarized: no Apple credentials, nothing to publish")
    if problems := check_entitlements_file(entitlements) + check_adhoc_entitlements_file(
        adhoc_entitlements
    ):
        raise SigningError("entitlements: " + "; ".join(problems))
    if problems := shell.verify_bundle(app, arch, require_runtime=True):
        raise SigningError("the app fails the architecture audit:\n  " + "\n  ".join(problems))
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    if problems := metadata_problems(app, info):
        raise SigningError("bundle metadata:\n  " + "\n  ".join(problems))
    redact = Redactor(credentials.secret_values() if credentials else [])
    run: Run = runner(redact) if runner else Runner(redact, echo)
    version = str(info["CFBundleShortVersionString"])
    commit = shell.git_commit()
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "architecture": arch,
        "version": version,
        "commit": commit,
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "minimum_macos": info.get("LSMinimumSystemVersion"),
        "mode": "developer-id" if credentials else "adhoc",
        "entitlements_sha256": shell_digest(entitlements),
    }
    with tempfile.TemporaryDirectory(prefix="owm-sign-") as temporary:
        work = Path(temporary)
        keychain = (
            signing_keychain(credentials, run, redact, work)
            if credentials
            else contextlib.nullcontext(ADHOC)
        )
        with keychain as identity:
            report["signed_by"] = identity.describe()
            report["signing"] = sign_app(app, identity, run, entitlements, adhoc_entitlements)
            report["signatures"] = verify_signatures(app, identity, run)
            if problems := shell.verify_bundle(app, arch, require_runtime=True):
                raise SigningError(
                    "signed app fails the architecture audit: " + "; ".join(problems)
                )
            notarization: dict[str, Any] = {}
            if credentials:
                notarization["app"] = notarize(app, f"app-{arch}", credentials, run, work, out)
                staple(app, run)
            dmg = out / dmg_name(version, arch, commit, notarized=credentials is not None)
            create_dmg(app, dmg, run, work)
            run(codesign_command(dmg, identity, None))
            if credentials:
                notarization["dmg"] = notarize(dmg, f"dmg-{arch}", credentials, run, work, out)
                staple(dmg, run)
            run(["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(dmg)])
            dmg_details = run(["/usr/bin/codesign", "--display", "--verbose=4", str(dmg)]).text
            if problems := signature_problems(dmg_details, identity, hardened=False):
                raise SigningError(f"{dmg.name}: " + "; ".join(problems))
    report["notarization"] = notarization or "SKIPPED: no Apple credentials"
    report["stapled"] = bool(notarization)
    report["gatekeeper"] = {"app": gatekeeper(app, run), "dmg": gatekeeper(dmg, run)}
    accepted = all(g["accepted"] for g in report["gatekeeper"].values())
    report["publishable"] = bool(credentials) and bool(notarization) and accepted
    report["dmg"] = {"name": dmg.name, "sha256": shell_digest(dmg), "bytes": dmg.stat().st_size}
    notices = app / "Contents" / "Resources" / "runtime" / "THIRD_PARTY_NOTICES.txt"
    if notices.is_file():
        shutil.copyfile(notices, out / "THIRD_PARTY_NOTICES.txt")
    report_path = out / f"signing-report-{arch}.json"
    report_path.write_text(redact(json.dumps(report, indent=2)) + "\n", encoding="utf-8")
    if credentials and not accepted:
        raise NotPublishable(f"Gatekeeper rejected the notarized build: {report['gatekeeper']}")
    if require_notarized and not report["publishable"]:
        raise NotPublishable("--require-notarized: the DMG is not notarized and stapled")
    return report


# --- verify-dmg ------------------------------------------------------------------------


@contextlib.contextmanager
def mounted(dmg: Path, run: Run, where: Path) -> Iterator[Path]:
    where.mkdir(parents=True, exist_ok=True)
    run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-noautoopen",
         "-mountpoint", str(where), str(dmg)])  # fmt: skip
    try:
        yield where
    finally:
        if run(["/usr/bin/hdiutil", "detach", str(where)], check=False).returncode != 0:
            run(["/usr/bin/hdiutil", "detach", "-force", str(where)], check=False)


def install(dmg: Path, applications: Path, run: Run, work: Path) -> tuple[Path, list[str]]:
    """Drag-to-Applications as Finder does it: replacing removes the old bundle first."""
    problems = []
    with mounted(dmg, run, work / "mount") as volume:
        entries = sorted(p.name for p in volume.iterdir() if not p.name.startswith("."))
        if entries != sorted(["Applications", APP]):
            problems.append(f"DMG contents are {entries}, expected the app and Applications")
        link = volume / "Applications"
        if not link.is_symlink() or os.readlink(link) != "/Applications":
            problems.append("DMG: Applications is not a link to /Applications")
        target = applications / APP
        if target.exists():
            shutil.rmtree(target)
        applications.mkdir(parents=True, exist_ok=True)
        run(["/usr/bin/ditto", str(volume / APP), str(target)])
    return target, problems


def version_report_at(app: Path, home: Path) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603
        [str(main_executable(app)), "--version-report"],
        capture_output=True, text=True, timeout=60, check=True,
        env={"HOME": str(home), "LANG": "C"},
    )  # fmt: skip
    report: dict[str, Any] = json.loads(result.stdout)
    return report


def verify_dmg(
    dmg: Path, arch: str, run: Run, *, expect: str = "adhoc", launch: bool = True
) -> dict[str, Any]:
    """Install, replace, tamper and uninstall checks on a copy, with a fake home."""
    identity = ADHOC if expect == "adhoc" else None
    problems: list[str] = []
    results: dict[str, Any] = {"dmg": dmg.name, "sha256": shell_digest(dmg), "expect": expect}
    run(["/usr/bin/hdiutil", "verify", str(dmg)])
    run(["/usr/bin/codesign", "--verify", "--strict", str(dmg)])
    if expect == "notarized":
        staple_check = run(["/usr/bin/xcrun", "stapler", "validate", str(dmg)], check=False)
        if staple_check.returncode != 0:
            problems.append("DMG has no valid stapled ticket")
    with tempfile.TemporaryDirectory(prefix="owm-dmg-") as temporary:
        work = Path(temporary)
        applications, home = work / "Applications", work / "home"
        app, found = install(dmg, applications, run, work)
        problems += found
        problems += [
            f"installed: {p}" for p in shell.verify_bundle(app, arch, require_runtime=True)
        ]
        verify = ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)]
        if run(verify, check=False).returncode != 0:
            problems.append("installed app fails codesign --verify --deep --strict")
        details = run(["/usr/bin/codesign", "--display", "--verbose=4", str(app)]).text
        if identity is not None:
            problems += [f"installed: {p}" for p in signature_problems(details, identity)]
        problems += [f"installed: {p}" for p in inventory_problems(app)]
        if launch:
            report = version_report_at(app, home)
            problems += [f"version report: {p}" for p in shell.check_report(report, arch)]
            results["version_report"] = report.get("build")
        # The library lives outside the bundle, so replacing or deleting the app keeps it.
        data = home / "Library" / "Application Support" / "OpenWorld Moments"
        data.mkdir(parents=True)
        (data / "library.sqlite").write_bytes(b"synthetic library")
        app, found = install(dmg, applications, run, work)  # upgrade / replace
        problems += found
        if run(verify, check=False).returncode != 0:
            problems.append("replaced app fails codesign verification")
        results["replace_keeps_library"] = (
            data / "library.sqlite"
        ).read_bytes() == b"synthetic library"
        results["gatekeeper"] = gatekeeper(app, run)
        if expect == "notarized" and not results["gatekeeper"]["accepted"]:
            problems.append("Gatekeeper rejected the installed notarized app")
        # Tampering: a changed resource, then a nested binary without its signature.
        tampered = work / "tampered" / APP
        run(["/usr/bin/ditto", str(app), str(tampered)])
        with (tampered / "Contents" / "Resources" / "runtime" / "inventory.json").open("a") as f:
            f.write(" ")
        results["tampered_resource_rejected"] = (
            run([*verify[:-1], str(tampered)], check=False).returncode != 0
        )
        shutil.rmtree(tampered)
        run(["/usr/bin/ditto", str(app), str(tampered)])
        tool = tampered / "Contents" / "Resources" / "runtime" / "tools" / "ffprobe"
        run(["/usr/bin/codesign", "--remove-signature", str(tool)])
        results["unsigned_nested_binary_rejected"] = (
            run([*verify[:-1], str(tampered)], check=False).returncode != 0
        )
        for case in ("tampered_resource_rejected", "unsigned_nested_binary_rejected"):
            if not results[case]:
                problems.append(f"{case}: codesign accepted a modified app")
        shutil.rmtree(app)  # uninstall: move the app to the Trash
        results["uninstall_keeps_library"] = (data / "library.sqlite").is_file()
        for case in ("replace_keeps_library", "uninstall_keeps_library"):
            if not results[case]:
                problems.append(f"{case} failed")
    results["problems"] = problems
    return results


# --- checksums -------------------------------------------------------------------------


def write_checksums(folder: Path) -> Path:
    """`checksums.txt` (sha256sum format) for every file in `folder`."""
    lines = [
        f"{shell_digest(p)}  {p.name}"
        for p in sorted(folder.iterdir())
        if p.is_file() and not p.is_symlink() and p.name != "checksums.txt"
    ]
    path = folder / "checksums.txt"
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


# --- command line ----------------------------------------------------------------------


def github_output(name: str, value: str, env: Mapping[str, str]) -> None:
    if target := env.get("GITHUB_OUTPUT"):
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"{name}={value}\n")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-credentials", help="which signing mode the environment allows")
    pack = commands.add_parser("package", help="sign, notarize and build the DMG")
    pack.add_argument("--arch", choices=sorted(shell.TARGETS), required=True)
    pack.add_argument("--app", type=Path, help="default: the build-shell.py bundle")
    pack.add_argument("--output", type=Path, help="default: output/packaging/macos/release-<arch>")
    pack.add_argument("--mode", choices=("auto", "adhoc", "developer-id"), default="auto")
    pack.add_argument("--require-notarized", action="store_true", help="the publication gate")
    check = commands.add_parser("verify-dmg", help="install, replace, tamper, uninstall checks")
    check.add_argument("dmg", type=Path)
    check.add_argument("--arch", choices=sorted(shell.TARGETS), required=True)
    check.add_argument("--expect", choices=("adhoc", "notarized"), default="adhoc")
    check.add_argument("--no-run", action="store_true", help="do not start the executable")
    sums = commands.add_parser("checksums", help="write checksums.txt for a folder")
    sums.add_argument("folder", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "check-credentials":
            credentials = credentials_from(env)
            mode = "developer-id" if credentials else "adhoc"
            print(f"signing mode: {mode}")
            if credentials is None:
                print(SKIP_NOTICE)
            github_output("mode", mode, env)
            return 0
        if args.command == "checksums":
            print(f"wrote {write_checksums(args.folder)}")
            return 0
        if sys.platform != "darwin":
            print("macOS signing runs on macOS", file=sys.stderr)
            return EXIT_USAGE
        if args.command == "package":
            out = args.output or OUTPUT / f"release-{args.arch}"
            report = package(
                args.arch,
                args.app or shell.bundle_path(args.arch),
                out,
                env,
                mode=args.mode,
                require_notarized=args.require_notarized,
            )
            keys = ("mode", "signed_by", "notarization", "stapled", "publishable", "dmg")
            print(json.dumps({k: report[k] for k in keys}, indent=2))
            if not report["publishable"]:
                print(f"NOT PUBLISHABLE: {report['dmg']['name']} is not notarized.")
            return 0
        runner = Runner(Redactor())
        results = verify_dmg(
            args.dmg, args.arch, runner, expect=args.expect, launch=not args.no_run
        )
        path = args.dmg.parent / f"dmg-check-{args.arch}.json"
        path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        for problem in results["problems"]:
            print(f"error: {problem}", file=sys.stderr)
        print(json.dumps({k: v for k, v in results.items() if k != "problems"}, indent=2))
        return EXIT_FAILED if results["problems"] else 0
    except NotPublishable as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_NOT_PUBLISHABLE
    except SigningError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
