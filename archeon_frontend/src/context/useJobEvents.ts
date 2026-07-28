import { createContext, useContext } from 'react';

/**
 * A simple pub/sub channel so any component (e.g. CreateJobForm) can notify
 * the rest of the UI that a new job was submitted, without lifting the job
 * list state up to App.tsx or introducing a heavier state library.
 *
 * Listeners register a callback via ``onJobSubmitted``; the form calls
 * ``notifyJobSubmitted`` after a successful POST.
 */
export interface JobEvents {
    /** Subscribe to "a new job was just submitted" events. */
    onJobSubmitted: (cb: () => void) => () => void;
    /** Fire-and-forget notification. */
    notifyJobSubmitted: () => void;
    /** Monotonically increasing counter for the last submitted job (debug). */
    submissionCount: number;
}

export const JobEventsContext = createContext<JobEvents | null>(null);

/** Hook for consuming the JobEvents context. */
export function useJobEvents(): JobEvents {
    const ctx = useContext(JobEventsContext);
    if (!ctx) {
        throw new Error('useJobEvents must be used within a <JobEventsProvider>');
    }
    return ctx;
}
