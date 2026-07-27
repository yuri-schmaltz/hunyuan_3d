/**
 * ModeChips — tabs-with-underline for the four generation modes.
 *
 * Not pills. Not buttons. A row of monospace, uppercase labels with
 * an amber underline on the active one. The glyphs on the left
 * (``Aa``, ``◐``, ``⊞``, ``◈``) communicate the mode at a glance.
 */
import React from "react";
import { clsx } from "clsx";

export type ModeKey = "text" | "image" | "multiview" | "texture";

const MODES: { key: ModeKey; glyph: string; label: string; hint: string }[] = [
  { key: "text", glyph: "Aa", label: "Text", hint: "Prompt → mesh" },
  { key: "image", glyph: "◐", label: "Image", hint: "Single view → mesh" },
  { key: "multiview", glyph: "⊞", label: "4 Views", hint: "Multi-view → mesh" },
  { key: "texture", glyph: "◈", label: "Re-texture", hint: "Mesh + reference" },
];

export const ModeChips: React.FC<{
  value: ModeKey;
  onChange: (k: ModeKey) => void;
}> = ({ value, onChange }) => (
  <div role="tablist" className="flex border-b border-border">
    {MODES.map((m) => {
      const active = m.key === value;
      return (
        <button
          key={m.key}
          role="tab"
          aria-selected={active}
          onClick={() => onChange(m.key)}
          title={m.hint}
          className={clsx(
            "group relative px-5 h-11 flex items-center gap-2",
            "font-mono text-xs uppercase tracking-wider",
            "border-b-2 -mb-px transition-colors duration-[120ms] " +
              "ease-[cubic-bezier(0.16,1,0.3,1)]",
            "focus:outline-none focus-visible:text-fg",
            active
              ? "border-accent text-fg"
              : "border-transparent text-fg-muted hover:text-fg",
          )}
        >
          <span
            className={clsx(
              "text-sm",
              active ? "text-accent" : "opacity-60",
            )}
          >
            {m.glyph}
          </span>
          <span>{m.label}</span>
        </button>
      );
    })}
  </div>
);
