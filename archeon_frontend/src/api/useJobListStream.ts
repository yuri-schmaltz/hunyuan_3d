import { useCallback, useEffect, useRef, useState } from 'react';
import type { JobResponse } from './types';

export interface UseJobListStreamResult {
    jobs: JobResponse[];
    connected: boolean;
    isFallback: boolean;
    error: string | null;
    /** Force an immediate re-fetch (used after submitting a new job). */
    refetch: () => void;
}

interface UseJobListStreamOptions {
    /** Polling interval in ms when SSE is unavailable. Default 3000. */
    pollIntervalMs?: number;
    /** When false, the hook is idle. Default true. */
    enabled?: boolean;
}

/**
 * Subscribe to the full job list via Server-Sent Events.
 *
 * One connection, many jobs: opens an ``EventSource`` to
 * ``/v1/jobs/events`` and replaces the local job array with whatever
 * the server pushes. Falls back to polling ``/v1/jobs`` on connection
 * error so the gallery still works against older backends.
 */
export function useJobListStream(
    baseUrl: string,
    opts: UseJobListStreamOptions = {},
): UseJobListStreamResult {
    const [jobs, setJobs] = useState<JobResponse[]>([]);
    const [connected, setConnected] = useState(false);
    const [isFallback, setIsFallback] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // We use a single ref that holds all the mutable state needed by
    // the long-lived EventSource and the cleanup logic. The effect
    // body writes the ref and the ``refetch`` callback reads it.
    const stateRef = useRef<{
        cancelled: boolean;
        isPolling: boolean;
        pollTimer: ReturnType<typeof setTimeout> | null;
        es: EventSource | null;
    }>({
        cancelled: false,
        isPolling: false,
        pollTimer: null,
        es: null,
    });

    const fetchOnce = useCallback(async (): Promise<void> => {
        try {
            const r = await fetch(`${baseUrl}/v1/jobs`);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data: JobResponse[] = await r.json();
            if (!stateRef.current.cancelled) setJobs(data);
        } catch (e) {
            if (!stateRef.current.cancelled) {
                setError(e instanceof Error ? e.message : 'Polling failed');
            }
        }
    }, [baseUrl]);

    useEffect(() => {
        const enabled = opts.enabled !== false;
        if (!enabled) {
            setJobs([]);
            setConnected(false);
            setError(null);
            return;
        }

        stateRef.current.cancelled = false;
        stateRef.current.isPolling = false;
        setConnected(false);
        setIsFallback(false);
        setError(null);

        const startPolling = (intervalMs: number) => {
            stateRef.current.isPolling = true;
            const tick = () => {
                if (stateRef.current.cancelled) return;
                void fetchOnce();
                if (!stateRef.current.cancelled) {
                    stateRef.current.pollTimer = setTimeout(tick, intervalMs);
                }
            };
            tick();
        };

        const startSse = () => {
            try {
                const es = new EventSource(`${baseUrl}/v1/jobs/events`);
                stateRef.current.es = es;

                es.onopen = () => {
                    if (stateRef.current.cancelled) return;
                    setConnected(true);
                };

                es.addEventListener('list', (ev) => {
                    if (stateRef.current.cancelled) return;
                    try {
                        const data: JobResponse[] = JSON.parse((ev as MessageEvent).data);
                        setJobs(data);
                    } catch (e) {
                        setError(e instanceof Error ? e.message : 'Bad SSE payload');
                    }
                });

                es.onerror = () => {
                    if (stateRef.current.cancelled) return;
                    setConnected(false);
                    es.close();
                    stateRef.current.es = null;
                    setIsFallback(true);
                    startPolling(opts.pollIntervalMs ?? 3000);
                };
            } catch (e) {
                setError(e instanceof Error ? e.message : 'SSE failed');
                setIsFallback(true);
                startPolling(opts.pollIntervalMs ?? 3000);
            }
        };

        startSse();

        return () => {
            stateRef.current.cancelled = true;
            if (stateRef.current.es) {
                stateRef.current.es.close();
                stateRef.current.es = null;
            }
            if (stateRef.current.pollTimer) {
                clearTimeout(stateRef.current.pollTimer);
                stateRef.current.pollTimer = null;
            }
        };
    }, [baseUrl, opts.pollIntervalMs, opts.enabled, fetchOnce]);

    const refetch = useCallback(() => {
        if (stateRef.current.isPolling) {
            void fetchOnce();
        }
        // If SSE is up, the server will deliver a new snapshot within
        // milliseconds; nothing to do client-side.
    }, [fetchOnce]);

    return { jobs, connected, isFallback, error, refetch };
}
