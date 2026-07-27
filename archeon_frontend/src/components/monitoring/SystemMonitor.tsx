/**
 * SystemMonitor — vertical stack of system metrics.
 *
 * Replaces the grid-of-cards layout. Each metric is a row with a
 * mono label on the left, the value on the right, and a hairline
 * divider between rows. Reads as a control panel readout.
 */
import React, { useEffect, useState } from "react";
import type { SystemMetrics } from "../../api/types";
import { apiClient } from "../../api/client";
import { Text, StatusDot, Stack, type StatusKind } from "../../design/primitives";

function pickKind(metrics: SystemMetrics | null, error: string | null): StatusKind {
  if (error) return "off";
  if (!metrics) return "queued";
  return "live";
}

function fmtBytes(n: number): string {
  if (!isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "K", "M", "G", "T"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export const SystemMonitor: React.FC = () => {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const fetchMetrics = async () => {
      try {
        const response = await apiClient.get<SystemMetrics>("/system/metrics");
        if (!alive) return;
        setMetrics(response.data);
        setError(null);
      } catch (err) {
        if (!alive) return;
        console.error("Failed to fetch metrics", err);
        setError("Offline");
      }
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);
    return () => {
      alive = false;
      clearInterval(interval);
    };
  }, []);

  const kind = pickKind(metrics, error);

  return (
    <Stack gap={0} className="divide-y divide-border">
      <Row
        label="CPU (process)"
        value={metrics ? `${metrics.cpu_percent.toFixed(1)}%` : "—"}
        kind={kind}
      />
      <Row
        label="RAM (process)"
        value={metrics ? fmtBytes(metrics.ram_bytes) : "—"}
        kind={kind}
      />
      {metrics?.gpu_percent !== undefined && (
        <Row
          label="GPU"
          value={`${metrics.gpu_percent.toFixed(1)}%`}
          kind={kind}
        />
      )}
      {metrics?.gpu_mem_used !== undefined && metrics?.gpu_mem_total !== undefined && (
        <Row
          label="VRAM"
          value={`${fmtBytes(metrics.gpu_mem_used)} / ${fmtBytes(metrics.gpu_mem_total)}`}
          kind={kind}
        />
      )}
      <Row
        label="Jobs in mem"
        value={metrics?.jobs_in_memory !== undefined
          ? String(metrics.jobs_in_memory)
          : "—"}
        kind={kind}
      />
      <Row
        label="Jobs in store"
        value={metrics?.jobs_in_store !== undefined
          ? String(metrics.jobs_in_store)
          : "—"}
        kind={kind}
      />
      <Row
        label="Persistence"
        value={metrics?.persistence_enabled ? "on" : "off"}
        kind={kind}
      />
      <Row
        label="Uptime"
        value={metrics?.uptime_seconds !== undefined
          ? formatUptime(metrics.uptime_seconds)
          : "—"}
        kind={kind}
      />
    </Stack>
  );
};

const Row: React.FC<{ label: string; value: string; kind: StatusKind }> = ({
  label,
  value,
  kind,
}) => (
  <div className="py-3 flex items-baseline justify-between gap-3">
    <div className="flex items-center gap-2">
      <StatusDot kind={kind} size={5} />
      <Text
        voice="mono"
        size="2xs"
        tone="muted"
        tracking="widest"
        uppercase
      >
        {label}
      </Text>
    </div>
    <Text voice="mono" size="sm" tone="fg" className="tabular-nums">
      {value}
    </Text>
  </div>
);

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d`;
}
