import React, { useCallback, useEffect, useRef, useState } from "react";
import { JobEventsContext, type JobEvents } from "./useJobEvents";
import { useJobListStream } from "../api/useJobListStream";
import { BASE_URL } from "../api/client";
import type { JobEvent, JobResponse } from "../api/types";

/**
 * Cap the in-memory event history so the context value doesn't
 * grow unbounded for long-running sessions.
 */
const MAX_EVENTS = 64;

/**
 * Build a synthetic ``JobEvent`` from a ``JobResponse`` so the
 * ticker/header can render a single uniform event log without
 * needing a separate ``/v1/events`` endpoint.
 */
function toEvent(job: JobResponse): JobEvent {
  return {
    uid: job.uid,
    status: job.status,
    at: job.updated_at ?? job.created_at,
    request_type: job.request_type,
  };
}

/** Provider component. Should wrap the entire app. */
export const JobEventsProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const listeners = useRef<Set<() => void>>(new Set());
  const [submissionCount, setSubmissionCount] = useState(0);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const seenUids = useRef<Set<string>>(new Set());

  const { jobs, connected, isFallback, error, refetch } =
    useJobListStream(BASE_URL);

  // Diff the streaming job list and append new entries to the event
  // log. Only statuses that change are recorded as new events.
  useEffect(() => {
    if (jobs.length === 0) return;
    let changed = false;
    setEvents((prev) => {
      const next = [...prev];
      for (const j of jobs) {
        const key = `${j.uid}:${j.status}`;
        if (seenUids.current.has(key)) continue;
        seenUids.current.add(key);
        next.push(toEvent(j));
        changed = true;
      }
      if (next.length > MAX_EVENTS) {
        next.splice(0, next.length - MAX_EVENTS);
      }
      return changed ? next : prev;
    });
  }, [jobs]);

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
        console.error("JobEvent listener threw:", err);
      }
    }
  }, []);

  const lastError = error ?? null;

  const value: JobEvents = {
    onJobSubmitted,
    notifyJobSubmitted,
    submissionCount,
    events,
    connected,
    isFallback,
    lastError,
    refetch,
    jobs,
  };

  return (
    <JobEventsContext.Provider value={value}>
      {children}
    </JobEventsContext.Provider>
  );
};
