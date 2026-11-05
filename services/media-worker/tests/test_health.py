# SPDX-License-Identifier: AGPL-3.0-or-later
from openworld_moments import __version__
from openworld_moments.health import health


def test_health_ok_on_supported_python() -> None:
    result = health((3, 12))
    assert result.status == "ok"
    assert result.version == __version__
    assert result.python == "3.12"


def test_health_flags_unsupported_python() -> None:
    assert health((3, 11)).status == "unsupported-python"
    assert health((3, 13)).status == "unsupported-python"


def test_health_detects_running_interpreter() -> None:
    # The project pins Python 3.12, so the test interpreter must be supported.
    assert health().status == "ok"


def test_health_serializes_to_plain_dict() -> None:
    assert health((3, 12)).to_dict() == {
        "status": "ok",
        "version": __version__,
        "python": "3.12",
    }
