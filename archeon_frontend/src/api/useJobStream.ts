import { useEffect, useRef, useState } from 'react';
import { JobStatus, type JobResponse, type JobStatusType } from '../api/types';

/**
 * Subscribe to a single job's status via Server-Sent Events.
 *
 * Falls back to polling every 2s if the server doesn't expose an
 * ``/events`` endpoint yet (older versions of the backend, or the SSE
 * connection drops mid-stream). The fallback is automatic and the
 * caller doesn't need to do anything special.
 *
 * Returns the latest job state. ``status`` is the last observed status,
 * or ``null`` until the first event arrives.
 */
export interface UseJobStreamResult {
    job: JobResponse | null;
    status: JobStatusType | null;
    connected: boolean;       // true while the SSE connection is up
    isFallback: boolean;       // true if we fell back to polling
    error: string | null;
}

interface UseJobStreamOptions {
    /** Polling interval in ms when SSE is unavailable. Default 2000. */
    pollIntervalMs?: number;
    /** When false, the hook is idle (used for jobs that aren't active). */
    enabled?: boolean;
}

export function useJobStream(
    baseUrl: string,
    uid: string | null,
    opts: UseJobStreamOptions = {},
): UseJobStreamResult {
    const [job, setJob] = useState<JobResponse | null>(null);
    const [status, setStatus] = useState<JobStatusType | null>(null);
    const [connected, setConnected] = useState(false);
    const [isFallback, setIsFallback] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const esRef = useRef<EventSource | null>(null);
    const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        if (!uid || opts.enabled === false) return;

        // Clean up any previous run.
        if (esRef.current) {
            esRef.current.close();
            esRef.current = null;
        }
        if (pollTimer.current) {
            clearTimeout(pollTimer.current);
            pollTimer.current = null;
        }
        setConnected(false);
        setIsFallback(false);
        setError(null);

        let cancelled = false;

        const startPolling = (intervalMs: number) => {
            const tick = async () => {
                if (cancelled) return;
                try {
                    const r = await fetch(`${baseUrl}/v1/jobs/${uid}`);
                    if (!r.ok) throw new Error(`HTTP ${r.status}`);
                    const data: JobResponse = await r.json();
                    setJob(data);
                    setStatus(data.status);
                    if (
                        data.status === JobStatus.COMPLETED ||
                        data.status === JobStatus.FAILED ||
                        data.status === JobStatus.CANCELLED
                    ) {
                        return; // stop polling on terminal status
                    }
                } catch (e) {
                    setError(e instanceof Error ? e.message : 'Polling failed');
                }
                if (!cancelled) {
                    pollTimer.current = setTimeout(tick, intervalMs);
                }
            };
            tick();
        };

        const startSse = () => {
            try {
                const es = new EventSource(`${baseUrl}/v1/jobs/${uid}/events`);
                esRef.current = es;

                es.onopen = () => {
                    if (cancelled) return;
                    setConnected(true);
                };

                es.addEventListener('status', (ev) => {
                    if (cancelled) return;
                    try {
                        const data: JobResponse = JSON.parse((ev as MessageEvent).data);
                        setJob(data);
                        setStatus(data.status);
                    } catch (e) {
                        setError(e instanceof Error ? e.message : 'Bad SSE payload');
                    }
                });

                es.onerror = () => {
                    if (cancelled) return;
                    // EventSource auto-reconnects a few times then gives up.
                    // If we're still not connected, fall back to polling.
                    setConnected(false);
                    es.close();
                    esRef.current = null;
                    setIsFallback(true);
                    startPolling(opts.pollIntervalMs ?? 2000);
                };
            } catch (e) {
                setError(e instanceof Error ? e.message : 'SSE failed');
                setIsFallback(true);
                startPolling(opts.pollIntervalMs ?? 2000);
            }
        };

        startSse();

        return () => {
            cancelled = true;
            if (esRef.current) {
                esRef.current.close();
                esRef.current = null;
            }
            if (pollTimer.current) {
                clearTimeout(pollTimer.current);
                pollTimer.current = null;
            }
        };
    }, [baseUrl, uid, opts.pollIntervalMs, opts.enabled]);

    return { job, status, connected, isFallback, error };
}
