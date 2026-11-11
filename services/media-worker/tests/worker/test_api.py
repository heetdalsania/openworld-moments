# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openworld_moments_contracts import load
from openworld_moments_contracts.versioning import SUPPORTED_VERSION
from starlette.testclient import WebSocketDenialResponse

from tests.worker.conftest import wait_for

COR = "cor_01JCBQ00000000000000000008"


def _job(client: TestClient, job_id: str) -> dict[str, Any]:
    return client.get(f"/v1/jobs/{job_id}").json()  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({}, "auth.missing_token"),
        ({"Authorization": "Bearer wrong"}, "auth.invalid_token"),
        ({"Authorization": "Basic abc"}, "auth.invalid_token"),
    ],
)
def test_requests_without_a_valid_token_are_rejected(
    client: TestClient, headers: dict[str, str], code: str
) -> None:
    del client.headers["Authorization"]
    for method, path in [
        ("GET", "/v1/health"),
        ("GET", "/v1/jobs"),
        ("POST", "/v1/jobs"),
        ("GET", "/v1/nope"),
    ]:
        response = client.request(method, path, headers=headers)
        assert response.status_code == 401, (method, path)
        body = response.json()
        assert body["code"] == code and body["retryable"] is False
        assert load("error", body)


def test_websocket_requires_the_token(client: TestClient) -> None:
    del client.headers["Authorization"]
    with (
        pytest.raises(WebSocketDenialResponse) as caught,
        client.websocket_connect("/v1/jobs/events"),
    ):
        pass
    assert caught.value.status_code == 401


def test_unexpected_host_header_is_rejected(client: TestClient) -> None:
    response = client.get("/v1/health", headers={"Host": "evil.example:80"})
    assert response.status_code == 403
    assert response.json()["code"] == "auth.bad_host"


def test_health_and_correlation_ids(client: TestClient) -> None:
    response = client.get("/v1/health", headers={"X-Correlation-Id": COR})
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == COR
    assert response.json()["status"] == "ok" and response.json()["schema_version"] == str(
        SUPPORTED_VERSION
    )
    generated = client.get("/v1/health", headers={"X-Correlation-Id": "not-valid"}).headers[
        "x-correlation-id"
    ]
    assert generated.startswith("cor_") and len(generated) == 30


def test_invalid_requests_use_the_error_contract(client: TestClient) -> None:
    for body, code in [
        ({"kind": "diagnostic", "params": {"steps": 0}}, "job.invalid_params"),
        ({"kind": "teleport"}, "job.unknown_kind"),
        ({"kind": "diagnostic", "extra": 1}, "request.invalid"),
    ]:
        response = client.post("/v1/jobs", json=body)
        assert response.status_code == 422, body
        assert response.json()["code"] == code
        assert load("error", response.json())
    missing = client.get("/v1/jobs/job_01JCBQ00000000000000000099")
    assert missing.status_code == 404 and missing.json()["code"] == "job.not_found"


def test_diagnostic_job_streams_ordered_progress_with_correlation_id(client: TestClient) -> None:
    with client.websocket_connect("/v1/jobs/events") as ws:
        job = client.post(
            "/v1/jobs",
            json={"kind": "diagnostic", "params": {"steps": 5, "step_ms": 5}},
            headers={"X-Correlation-Id": COR},
        ).json()
        events = []
        while True:
            event = load("job-event", json.loads(ws.receive_text()))
            events.append(event)
            if event.job.state == "ready":  # type: ignore[attr-defined]
                break
    seqs = [e.seq for e in events]  # type: ignore[attr-defined]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), (
        "events must be contiguous and ordered"
    )
    assert {e.job.id for e in events} == {job["id"]}  # type: ignore[attr-defined]
    assert {e.job.correlation_id for e in events} == {COR}  # type: ignore[attr-defined]
    states = [e.job.state for e in events if e.kind == "state"]  # type: ignore[attr-defined]
    assert states == ["queued", "analyzing", "ready"]
    done = [e.job.progress.done for e in events if e.kind == "progress"]  # type: ignore[attr-defined]
    assert done == sorted(done) and done[-1] == 5


def test_cancelling_a_running_job_stops_it(client: TestClient) -> None:
    job = client.post(
        "/v1/jobs", json={"kind": "diagnostic", "params": {"steps": 1000, "step_ms": 20}}
    ).json()
    wait_for(lambda: _job(client, job["id"]).get("progress", {}).get("done", 0) >= 2)
    assert client.post(f"/v1/jobs/{job['id']}/cancel").status_code == 200
    final = wait_for(lambda: (j := _job(client, job["id"]))["state"] == "cancelled" and j)
    progress_at_cancel = final["progress"]["done"]
    assert progress_at_cancel < 1000
    # Work really stopped: progress does not advance afterwards.
    import time

    time.sleep(0.2)
    assert _job(client, job["id"])["progress"]["done"] == progress_at_cancel
    again = client.post(f"/v1/jobs/{job['id']}/cancel")
    assert again.status_code == 200 and again.json()["state"] == "cancelled"


def test_failed_jobs_can_be_retried_until_max_attempts(client: TestClient) -> None:
    job = client.post(
        "/v1/jobs", json={"kind": "diagnostic", "params": {"steps": 2, "step_ms": 1, "fail_at": 1}}
    ).json()
    for attempt in (1, 2, 3):
        failed = wait_for(lambda: (j := _job(client, job["id"]))["state"] == "failed" and j)
        assert failed["attempt"] == attempt
        assert failed["error"] == {
            "code": "diagnostic.requested_failure",
            "message": "Failed at step 1 as requested.",
            "retryable": True,
            "correlation_id": job["correlation_id"],
        }
        response = client.post(f"/v1/jobs/{job['id']}/retry")
        if attempt < 3:
            assert response.status_code == 200 and response.json()["state"] == "queued"
    assert response.status_code == 409 and response.json()["code"] == "job.max_attempts"


def test_finished_jobs_cannot_be_cancelled_or_retried(client: TestClient) -> None:
    job = client.post(
        "/v1/jobs", json={"kind": "diagnostic", "params": {"steps": 1, "step_ms": 0}}
    ).json()
    wait_for(lambda: _job(client, job["id"])["state"] == "ready")
    assert client.post(f"/v1/jobs/{job['id']}/cancel").json()["code"] == "job.not_cancellable"
    assert client.post(f"/v1/jobs/{job['id']}/retry").json()["code"] == "job.not_retryable"


def test_list_jobs_returns_contract_documents(client: TestClient) -> None:
    client.post("/v1/jobs", json={"kind": "diagnostic", "params": {"steps": 1, "step_ms": 0}})
    jobs = client.get("/v1/jobs").json()
    assert len(jobs) == 1 and load("job", jobs[0])


def test_request_bodies_are_bounded(client: TestClient) -> None:
    # M30: a declared length over the cap or an unbounded chunked body is refused
    # before the route reads anything.
    from openworld_moments.api.app import MAX_REQUEST_BYTES

    too_big = client.post(
        "/v1/jobs",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": str(MAX_REQUEST_BYTES + 1)},
    )
    assert too_big.status_code == 413 and too_big.json()["code"] == "request.too_large"

    def chunks() -> Iterator[bytes]:
        yield b'{"kind": "diagnostic", '
        yield b'"params": {}}'

    chunked = client.post(
        "/v1/jobs", content=chunks(), headers={"content-type": "application/json"}
    )
    assert chunked.status_code == 411 and chunked.json()["code"] == "request.length_required"
    normal = client.post("/v1/jobs", json={"kind": "diagnostic", "params": {"steps": 1}})
    assert normal.status_code == 201
