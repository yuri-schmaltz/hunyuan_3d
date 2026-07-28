import React, { useEffect, useRef, useState } from 'react';
import { apiClient, BASE_URL } from '../../api/client';
import { JobStatus } from '../../api/types';
import type { JobResponse, JobStatusType } from '../../api/types';
import { RefreshCw, CheckCircle, Clock, XCircle, AlertTriangle, Download, Scissors, X, Eye, EyeOff } from 'lucide-react';
import { MeshPreview } from './MeshPreview';
import { useJobEvents } from '../../context/useJobEvents';

const POLL_INTERVAL_MS = 2000;
// Cap the exponential backoff so a flapping backend doesn't degrade to multi-minute polls.
const MAX_POLL_BACKOFF_MS = 30_000;

export const JobGallery: React.FC = () => {
    const [jobs, setJobs] = useState<JobResponse[]>(() => []);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [previewingUid, setPreviewingUid] = useState<string | null>(null);
    const inFlight = useRef(false);
    // Exponential backoff state for polling after a failure.
    const consecutiveFailures = useRef(0);
    // Track the latest submission count from the JobEvents provider so we
    // can refetch immediately when a new job is submitted elsewhere.
    const lastSeenSubmission = useRef(0);
    const { onJobSubmitted, submissionCount } = useJobEvents();

    const fetchJobs = async (): Promise<boolean> => {
        if (inFlight.current) return true; // treated as "ok" so we don't back off
        inFlight.current = true;
        try {
            const res = await apiClient.get<JobResponse[]>('/jobs');
            setJobs(
                res.data.sort(
                    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
                ),
            );
            setError(null);
            consecutiveFailures.current = 0;
            return true;
        } catch (err) {
            consecutiveFailures.current += 1;
            setError(err instanceof Error ? err.message : 'Failed to load jobs');
            return false;
        } finally {
            inFlight.current = false;
            setLoading(false);
        }
    };

    useEffect(() => {
        // Schedule the first fetch on the next tick so the initial setState
        // doesn't cascade inside the effect body.
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | null = null;

        const tick = async () => {
            if (cancelled || document.hidden) {
                timer = setTimeout(tick, POLL_INTERVAL_MS);
                return;
            }
            const ok = await fetchJobs();
            const delay = ok
                ? POLL_INTERVAL_MS
                : Math.min(
                    POLL_INTERVAL_MS * 2 ** consecutiveFailures.current,
                    MAX_POLL_BACKOFF_MS,
                );
            timer = setTimeout(tick, delay);
        };

        timer = setTimeout(tick, 0);
        return () => {
            cancelled = true;
            if (timer) clearTimeout(timer);
        };
    }, []);

    // Refetch immediately when another component submits a new job.
    useEffect(() => {
        if (submissionCount > lastSeenSubmission.current) {
            lastSeenSubmission.current = submissionCount;
            void fetchJobs();
        }
    }, [submissionCount]);

    // Allow other components (e.g. CreateJobForm) to trigger an immediate refresh
    // through the JobEvents provider without prop-drilling.
    useEffect(() => onJobSubmitted(() => { void fetchJobs(); }), [onJobSubmitted]);

    const handleCancel = async (uid: string) => {
        try {
            await apiClient.delete(`/jobs/${uid}`);
            void fetchJobs();
        } catch (err) {
            console.error(err);
            setError(err instanceof Error ? err.message : 'Cancel failed');
        }
    };

    const handleOptimize = async (uid: string) => {
        try {
            const res = await apiClient.post<{ file_path: string }>('/meshops/process', {
                job_uid: uid,
                action: 'decimate',
                ratio: 0.5,
            });
            const fname = res.data.file_path.split('/').pop();
            window.open(`${BASE_URL}/files/${encodeURIComponent(fname ?? '')}`, '_blank');
        } catch (err) {
            console.error(err);
            setError(err instanceof Error ? err.message : 'Optimization failed');
        }
    };

    const previewUrl = (job: JobResponse): string | null => {
        if (!job.file_path) return null;
        const fname = job.file_path.split(/[\\/]/).pop();
        return `${BASE_URL}/files/${encodeURIComponent(fname ?? '')}`;
    };

    const getStatusIcon = (status: JobStatusType) => {
        switch (status) {
            case JobStatus.COMPLETED: return <CheckCircle size={16} className="text-emerald-400" aria-hidden />;
            case JobStatus.PROCESSING: return <RefreshCw size={16} className="text-sky-400 animate-spin" aria-hidden />;
            case JobStatus.FAILED: return <XCircle size={16} className="text-rose-400" aria-hidden />;
            case JobStatus.QUEUED: return <Clock size={16} className="text-amber-400" aria-hidden />;
            case JobStatus.CANCELLED: return <XCircle size={16} className="text-gray-500" aria-hidden />;
            default: return <AlertTriangle size={16} className="text-gray-500" aria-hidden />;
        }
    };

    // Status badge: solid background with white text for WCAG AA contrast.
    const getStatusBadgeClass = (status: JobStatusType): string => {
        switch (status) {
            case JobStatus.COMPLETED: return 'bg-emerald-700 text-white';
            case JobStatus.PROCESSING: return 'bg-sky-700 text-white';
            case JobStatus.FAILED: return 'bg-rose-700 text-white';
            case JobStatus.QUEUED: return 'bg-amber-700 text-white';
            case JobStatus.CANCELLED: return 'bg-gray-700 text-gray-200';
            default: return 'bg-gray-700 text-gray-200';
        }
    };

    const previewedJob = previewingUid ? jobs.find((j) => j.uid === previewingUid) ?? null : null;

    return (
        <div className="bg-archeon-panel border border-gray-700 rounded-lg p-6 h-full overflow-y-auto max-h-[600px]">
            <h3 className="text-lg font-semibold mb-4 text-gray-300 flex items-center justify-between sticky top-0 bg-archeon-panel py-2 z-10">
                <span>Recent Jobs</span>
                <button
                    onClick={fetchJobs}
                    className="text-gray-500 hover:text-white"
                    aria-label="Refresh jobs"
                >
                    <RefreshCw size={16} />
                </button>
            </h3>

            {error && (
                <div role="alert" className="bg-rose-900/40 text-rose-200 text-sm p-2 rounded mb-3">
                    {error}
                </div>
            )}

            {/* Inline preview when a job is selected for inspection. */}
            {previewedJob && previewUrl(previewedJob) && (
                <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-xs text-gray-400 font-mono">
                            Preview · {previewedJob.uid.slice(0, 8)}…
                        </span>
                        <button
                            onClick={() => setPreviewingUid(null)}
                            className="text-gray-400 hover:text-white"
                            aria-label="Close preview"
                        >
                            <X size={16} />
                        </button>
                    </div>
                    <MeshPreview
                        src={previewUrl(previewedJob)!}
                        alt={`Mesh for job ${previewedJob.uid}`}
                        height={320}
                    />
                </div>
            )}

            <div className="space-y-2">
                {loading && jobs.length === 0 && (
                    <div
                        className="text-gray-500 text-sm animate-pulse"
                        role="status"
                        aria-live="polite"
                    >
                        Loading jobs…
                    </div>
                )}

                {!loading && jobs.length === 0 && !error && (
                    <p className="text-gray-500 text-sm">No jobs found.</p>
                )}

                {jobs.map((job) => {
                    const isPreviewing = previewingUid === job.uid;
                    return (
                        <div
                            key={job.uid}
                            className="bg-gray-800/50 p-3 rounded flex items-center justify-between hover:bg-gray-800 transition-colors"
                        >
                            <div className="flex items-center gap-3 min-w-0">
                                {getStatusIcon(job.status)}
                                <div className="text-sm min-w-0">
                                    <div className="font-mono text-gray-300 text-xs truncate">
                                        {job.uid.slice(0, 8)}…
                                    </div>
                                    <div className="text-xs text-gray-500">
                                        {new Date(job.created_at).toLocaleTimeString()}
                                    </div>
                                </div>
                            </div>

                            <div className="flex items-center gap-2 ml-2">
                                <div
                                    className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${getStatusBadgeClass(job.status)}`}
                                >
                                    {job.status}
                                </div>

                                {job.status === JobStatus.COMPLETED && job.file_path && (
                                    <div className="flex gap-1">
                                        <button
                                            onClick={() => setPreviewingUid(isPreviewing ? null : job.uid)}
                                            className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                                            aria-label={isPreviewing ? 'Hide preview' : 'Show preview'}
                                            title={isPreviewing ? 'Hide preview' : 'Show preview'}
                                        >
                                            {isPreviewing ? <EyeOff size={14} /> : <Eye size={14} />}
                                        </button>
                                        <a
                                            href={previewUrl(job) ?? '#'}
                                            target="_blank"
                                            rel="noreferrer noopener"
                                            className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                                            title="Download"
                                            aria-label="Download mesh"
                                        >
                                            <Download size={14} />
                                        </a>
                                        <button
                                            onClick={() => handleOptimize(job.uid)}
                                            className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white transition-colors"
                                            title="Optimize (Decimate 50%)"
                                            aria-label="Optimize mesh"
                                        >
                                            <Scissors size={14} />
                                        </button>
                                    </div>
                                )}

                                {(job.status === JobStatus.QUEUED || job.status === JobStatus.PROCESSING) && (
                                    <button
                                        onClick={() => handleCancel(job.uid)}
                                        className="p-1.5 hover:bg-rose-700/40 rounded text-gray-400 hover:text-rose-300 transition-colors"
                                        title="Cancel job"
                                        aria-label="Cancel job"
                                    >
                                        <X size={14} />
                                    </button>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};
