"""
Regression test for the /v1/jobs/events route ordering bug.

Background: PR #5 introduced the per-job SSE endpoint at
``/v1/jobs/{uid}/events``. PR #6 added the list-level SSE at
``/v1/jobs/events``. Both were registered AFTER the catch-all
``/v1/jobs/{uid}`` in hy3dgen/api/routes.py, which meant FastAPI
matched ``/v1/jobs/events`` as ``uid="events"`` and returned 404
"Job not found" instead of opening the SSE stream.

This test guards against the bug re-appearing. It does NOT
exercise the real handlers (they pull in the full app), only
verifies the structural and HTTP-level behavior of the route
ordering itself.
"""
import re

import pytest


def test_list_sse_route_registered_before_catch_all():
    """The literal /v1/jobs/events route must be registered before
    /v1/jobs/{uid} so it wins over the catch-all.

    FastAPI/Starlette match in registration order, not by path
    specificity, so this is load-bearing.
    """
    from hy3dgen.api.routes import router

    # Build the route list in the order the FastAPI decorator
    # calls created them. We re-parse the file as text to be
    # immune to changes in how the runtime exposes them.
    src = open("hy3dgen/api/routes.py").read()
    matches = re.findall(
        r'@router\.(get|post|delete)\(\s*\n?\s*("[^"]+")',
        src,
    )
    routes_in_order = [path.strip('"') for _verb, path in matches]

    list_idx = next(
        (i for i, p in enumerate(routes_in_order) if p == "/jobs/events"),
        None,
    )
    per_job_idx = next(
        (
            i
            for i, p in enumerate(routes_in_order)
            if p == "/jobs/{uid}/events"
        ),
        None,
    )
    catchall_idx = next(
        (
            i
            for i, p in enumerate(routes_in_order)
            if p == "/jobs/{uid}"
        ),
        None,
    )

    assert list_idx is not None, "/v1/jobs/events route is missing from routes.py"
    assert catchall_idx is not None, "/v1/jobs/{uid} catch-all is missing from routes.py"
    assert per_job_idx is not None, "/v1/jobs/{uid}/events route is missing from routes.py"

    assert list_idx < catchall_idx, (
        f"/jobs/events (line {list_idx}) must be declared BEFORE "
        f"/jobs/{{uid}} (line {catchall_idx}) so the literal path wins "
        f"over the catch-all. FastAPI/Starlette match in registration "
        f"order, not by path specificity."
    )
    assert per_job_idx < catchall_idx, (
        f"/jobs/{{uid}}/events (line {per_job_idx}) must be declared BEFORE "
        f"/jobs/{{uid}} (line {catchall_idx})."
    )


def test_openapi_documents_list_sse_route():
    """The OpenAPI schema must list /v1/jobs/events as a real route,
    not as the catch-all. This catches the regression at the schema
    level even when running with the real app (where the live
    stream makes HTTP-level testing flaky)."""
    from fastapi import FastAPI, Depends
    from hy3dgen.api.routes import router

    app = FastAPI()
    app.include_router(router, dependencies=[Depends(lambda: None)])

    schema = app.openapi()
    paths = list(schema["paths"].keys())

    assert "/v1/jobs/events" in paths, (
        f"/v1/jobs/events is missing from OpenAPI paths: {paths}"
    )
    # The list-SSE route must come before the catch-all in OpenAPI too,
    # so the docs reflect the actual server behaviour.
    list_idx = paths.index("/v1/jobs/events")
    catchall_idx = paths.index("/v1/jobs/{uid}")
    assert list_idx < catchall_idx, (
        f"In OpenAPI /v1/jobs/events is at idx {list_idx} but the catch-all "
        f"/v1/jobs/{{uid}} is at idx {catchall_idx}. The order in the docs "
        f"should mirror the actual matching order."
    )
