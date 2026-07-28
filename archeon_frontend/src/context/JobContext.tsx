import React, { useCallback, useRef, useState } from 'react';
import { JobEventsContext, type JobEvents } from './useJobEvents';

/** Provider component. Should wrap the entire app. */
export const JobEventsProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const listeners = useRef<Set<() => void>>(new Set());
    const [submissionCount, setSubmissionCount] = useState(0);

    const onJobSubmitted = useCallback((cb: () => void) => {
        listeners.current.add(cb);
        return () => {
            listeners.current.delete(cb);
        };
    }, []);

    const notifyJobSubmitted = useCallback(() => {
        setSubmissionCount((n) => n + 1);
        for (const cb of listeners.current) {
            try {
                cb();
            } catch (err) {
                console.error('JobEvent listener threw:', err);
            }
        }
    }, []);

    const value: JobEvents = { onJobSubmitted, notifyJobSubmitted, submissionCount };

    return <JobEventsContext.Provider value={value}>{children}</JobEventsContext.Provider>;
};
