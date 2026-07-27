/**
 * AppShell — the three-zone layout container.
 *
 *   ┌────────────────── header ──────────────────┐
 *   ├──────┬────────────────────────────────────┤
 *   │ rail │              main                  │
 *   │      │                                    │
 *   ├──────┴────────────────────────────────────┤
 *   │              ticker                       │
 *   └───────────────────────────────────────────┘
 *
 * The main zone is the only scrollable area; the rail and ticker
 * stay fixed. The header has a hairline divider. The ticker is a
 * monospace live feed of the most recent SSE event.
 */
import React from "react";
import { PageHeader } from "./PageHeader";
import { StatusTicker } from "./StatusTicker";
import { LeftRail } from "./LeftRail";

export const AppShell: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => (
  <div className="h-screen flex flex-col bg-bg text-fg">
    <PageHeader />
    <div className="flex-1 flex overflow-hidden">
      <LeftRail />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-10 py-10">{children}</div>
      </main>
    </div>
    <StatusTicker />
  </div>
);
