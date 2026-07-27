/**
 * LeftRail — fixed-width sidebar (260px) for the system vitals.
 *
 * Holds the SystemMonitor stack plus two utility actions at the
 * bottom. Hairline dividers separate each section, in line with
 * the "paper millimetrado" aesthetic.
 */
import React from "react";
import { Text, Divider, Button, Stack } from "../design/primitives";
import { SystemMonitor } from "./monitoring/SystemMonitor";

export const LeftRail: React.FC = () => (
  <aside className="w-64 border-r border-border bg-bg flex flex-col overflow-y-auto">
    <div className="px-5 py-4">
      <Stack gap={2}>
        <Text
          voice="mono"
          size="2xs"
          tone="muted"
          tracking="widest"
          uppercase
        >
          System vitals
        </Text>
        <Text voice="body" size="xs" tone="dim" className="leading-snug">
          Live snapshot of the inference host. Refreshes every 2s.
        </Text>
      </Stack>
    </div>
    <Divider />
    <div className="px-5 py-4">
      <SystemMonitor />
    </div>
    <div className="flex-1" />
    <Divider />
    <div className="px-5 py-4">
      <Stack gap={2}>
        <Text
          voice="mono"
          size="2xs"
          tone="muted"
          tracking="widest"
          uppercase
        >
          Quick actions
        </Text>
        <Button variant="secondary" size="sm" block>
          New project
        </Button>
        <Button variant="ghost" size="sm" block>
          Documentation →
        </Button>
      </Stack>
    </div>
  </aside>
);
