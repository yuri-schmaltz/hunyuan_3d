/**
 * PageHeader — the wordmark zone.
 *
 * The "Archeon 3D" wordmark uses the serif display face in italic.
 * No gradient. No glow. Just typography doing the work.
 *
 * On the right: a small mono cluster with the version + a live
 * status dot indicating SSE connection state.
 */
import React from "react";
import { Text, Divider, StatusDot } from "../design/primitives";
import { useJobEvents } from "../context/useJobEvents";

export const PageHeader: React.FC = () => {
  const { connected } = useJobEvents();
  return (
    <header className="h-14 border-b border-border bg-bg/80 backdrop-blur-sm flex items-center px-6 z-(--z-header)">
      <div className="flex items-baseline gap-3">
        <Text voice="display" size="xl" tracking="tight">
          Archeon
        </Text>
        <Text voice="display" size="xl" tone="muted" tracking="tight">
          ·3D
        </Text>
      </div>
      <div className="ml-8 flex items-center gap-2">
        <Text
          voice="mono"
          size="2xs"
          tone="dim"
          tracking="widest"
          uppercase
        >
          High-fidelity local generation
        </Text>
      </div>
      <div className="flex-1" />
      <div className="flex items-center gap-3">
        <StatusDot kind={connected ? "live" : "off"} />
        <Text
          voice="mono"
          size="2xs"
          tone="muted"
          tracking="widest"
          uppercase
        >
          {connected ? "stream live" : "stream idle"}
        </Text>
        <Divider className="!w-px !h-4 !bg-border-strong" />
        <Text
          voice="mono"
          size="2xs"
          tone="dim"
          tracking="widest"
          uppercase
        >
          v1.0.0 · phase 2
        </Text>
      </div>
    </header>
  );
};
