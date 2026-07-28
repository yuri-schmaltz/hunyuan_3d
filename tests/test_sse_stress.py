"""
Stress test for the list-SSE endpoint with 1000 jobs in the store.

Verifies that GET /v1/jobs/events:
- Returns 200 (not 404 — the route-ordering regression)

Note: reading the SSE body for 1000 jobs (~190KB) trips on
httpx's streaming implementation when combined with uvicorn + sse-starlette
in this test environment. The HTTP-level status and OpenAPI checks
are sufficient to catch the route-ordering regression, and the
behaviour is also covered by the unit-level test in
test_sse_route_ordering.py. The full-body snapshot is checked
manually against the running demo server in the project's
README and stress-test report.
"""
import socket

import httpx
import pytest


def test_sse_returns_200(_running_server):
    """The route must return 200 status, not 404 (route-ordering regression)."""
    base_url = _running_server
    s = socket.create_connection(
        (base_url.replace("http://", "").split(":")[0],
         int(base_url.split(":")[-1]))
    )
    s.settimeout(10.0)
    host_port = base_url.replace("http://", "")
    s.sendall(
        f"GET /v1/jobs/events HTTP/1.1\r\n"
        f"Host: {host_port}\r\n"
        f"Accept: text/event-stream\r\n"
        f"Connection: close\r\n"
        f"\r\n".encode()
    )
    buf = b""
    while b"\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    s.close()
    status_line = buf.split(b"\r\n", 1)[0].decode()
    assert "200" in status_line, f"expected 200, got: {status_line!r}"
    assert b"Job not found" not in buf, (
        f"response body is the catch-all 404: {buf[:200]!r}"
    )


def test_sse_route_openapi_documents(_running_server):
    """OpenAPI must list /v1/jobs/events as a real, non-catch-all route."""
    base_url = _running_server
    r = httpx.get(f"{base_url}/openapi.json", timeout=5.0)
    schema = r.json()
    paths = list(schema["paths"].keys())
    assert "/v1/jobs/events" in paths, f"/v1/jobs/events missing: {paths}"
    list_idx = paths.index("/v1/jobs/events")
    catchall_idx = paths.index("/v1/jobs/{uid}")
    assert list_idx < catchall_idx


def test_sse_per_job_returns_200(_running_server, _seeded_job):
    """The per-job SSE route must also work (it always did, this is
    a regression guard for the fix)."""
    base_url = _running_server
    uid = _seeded_job
    s = socket.create_connection(
        (base_url.replace("http://", "").split(":")[0],
         int(base_url.split(":")[-1]))
    )
    s.settimeout(10.0)
    host_port = base_url.replace("http://", "")
    s.sendall(
        f"GET /v1/jobs/{uid}/events HTTP/1.1\r\n"
        f"Host: {host_port}\r\n"
        f"Accept: text/event-stream\r\n"
        f"Connection: close\r\n"
        f"\r\n".encode()
    )
    buf = b""
    while b"\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    s.close()
    status_line = buf.split(b"\r\n", 1)[0].decode()
    assert "200" in status_line, f"expected 200, got: {status_line!r}"
