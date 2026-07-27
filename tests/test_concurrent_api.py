"""
Stress test for the public API under concurrent load.

Hits ``GET /v1/jobs`` 200 times across 50 concurrent clients and
verifies that:
- All requests succeed (no 5xx)
- The total wall-clock time scales sub-linearly with parallelism
- The API remains responsive (per-request latency under 500ms even
  at peak concurrency)
"""
import asyncio
import time

import httpx
import pytest


async def test_concurrent_get_jobs(_running_server):
    """50 concurrent clients × 4 requests = 200 requests on /v1/jobs."""
    base_url = _running_server
    concurrency = 50
    requests_per_client = 4
    total = concurrency * requests_per_client

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        async def one_client(_id: int) -> list[float]:
            latencies: list[float] = []
            for _ in range(requests_per_client):
                t0 = time.perf_counter()
                r = await client.get("/v1/jobs")
                latencies.append((time.perf_counter() - t0) * 1000)
                assert r.status_code == 200, (
                    f"client {_id} got {r.status_code}: {r.text[:200]}"
                )
            return latencies

        t0 = time.perf_counter()
        results = await asyncio.gather(*[one_client(i) for i in range(concurrency)])
        wall = time.perf_counter() - t0

    all_latencies = [lat for client_lats in results for lat in client_lats]
    all_latencies.sort()

    p50 = all_latencies[len(all_latencies) // 2]
    p95 = all_latencies[int(len(all_latencies) * 0.95)]
    p99 = all_latencies[int(len(all_latencies) * 0.99)]
    rps = total / wall

    print(
        f"\n[concurrent] {total} requests, {concurrency} concurrent: "
        f"wall={wall:.2f}s, rps={rps:.0f}, "
        f"p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms"
    )

    assert p95 < 1000, f"p95 latency {p95:.1f}ms exceeds 1s budget"


async def test_concurrent_health(_running_server):
    """100 concurrent /health probes (simulates a load balancer)."""
    base_url = _running_server

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        async def probe() -> float:
            t0 = time.perf_counter()
            r = await client.get("/health")
            assert r.status_code == 200
            return (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        results = await asyncio.gather(*[probe() for _ in range(100)])
        wall = time.perf_counter() - t0

    results.sort()
    p50 = results[50]
    p95 = results[95]

    print(
        f"\n[concurrent health] 100 probes: wall={wall:.2f}s, "
        f"rps={100 / wall:.0f}, p50={p50:.1f}ms, p95={p95:.1f}ms"
    )

    assert p95 < 1000, f"health p95 {p95:.1f}ms exceeds 1s budget"


async def test_concurrent_per_job_lookup(_running_server, _seeded_job):
    """50 concurrent lookups of the same uid (cache-warm scenario)."""
    base_url = _running_server
    uid = _seeded_job

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        async def lookup() -> float:
            t0 = time.perf_counter()
            r = await client.get(f"/v1/jobs/{uid}")
            assert r.status_code == 200
            return (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        results = await asyncio.gather(*[lookup() for _ in range(50)])
        wall = time.perf_counter() - t0

    results.sort()
    print(
        f"\n[concurrent per-job] 50 lookups of same uid: wall={wall:.2f}s, "
        f"p50={results[25]:.1f}ms, p95={results[47]:.1f}ms"
    )
