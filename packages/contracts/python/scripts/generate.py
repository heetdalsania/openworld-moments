# SPDX-License-Identifier: Apache-2.0
"""Generate Pydantic models from ../schemas and vendor the schemas into the package.

Run from the repository root with: pnpm contracts:generate
Output is deterministic: no timestamps, fixed tool versions from uv.lock, ruff-formatted.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = PACKAGE_ROOT.parent / "schemas"
MODULE = PACKAGE_ROOT / "openworld_moments_contracts"
MODELS = MODULE / "generated"
VENDORED_SCHEMAS = MODULE / "schemas"

CODEGEN_ARGS = [
    "--input-file-type",
    "jsonschema",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--target-python-version",
    "3.12",
    "--no-allow-remote-refs",
    "--disable-timestamp",
    "--use-annotated",
    "--use-title-as-name",
    "--field-constraints",
    "--use-schema-description",
    "--use-double-quotes",
    "--collapse-root-models",
    "--enum-field-as-literal",
    "all",
    "--no-formatters",
]


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)  # noqa: S603 - fixed argument list, no shell


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "generated"
        run(
            [
                sys.executable,
                "-m",
                "datamodel_code_generator",
                "--input",
                str(SCHEMAS),
                "--output",
                str(out),
                *CODEGEN_ARGS,
            ]
        )
        if MODELS.exists():
            shutil.rmtree(MODELS)
        shutil.copytree(out, MODELS)
    # Sort imports and format in place so the package's ruff config applies.
    run([sys.executable, "-m", "ruff", "check", "--quiet", "--select", "I", "--fix", str(MODELS)])
    run([sys.executable, "-m", "ruff", "format", "--quiet", str(MODELS)])

    if VENDORED_SCHEMAS.exists():
        shutil.rmtree(VENDORED_SCHEMAS)
    VENDORED_SCHEMAS.mkdir()
    for schema in sorted(SCHEMAS.glob("*.schema.json")):
        shutil.copyfile(schema, VENDORED_SCHEMAS / schema.name)
    print(f"Generated {MODELS.relative_to(PACKAGE_ROOT)} and vendored {VENDORED_SCHEMAS.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
