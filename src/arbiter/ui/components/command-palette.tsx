"use client";

import { ArrowRight, Box, Folder, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { JsonRecord } from "@/lib/types";
import { EmptyState, ResourceGlyph } from "./ui";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (view: string) => void;
}

const commands = [
  { label: "Open workspaces", hint: "Projects and services", view: "workspaces", icon: Folder },
  { label: "Inspect containers", hint: "Docker runtime", view: "containers", icon: Box },
  { label: "Ask Arbiter", hint: "Use observed local state", view: "agent", icon: Sparkles },
];

export function CommandPalette({ open, onClose, onNavigate }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<JsonRecord[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    requestAnimationFrame(() => inputRef.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, open]);

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setResults([]);
      return;
    }
    const timer = window.setTimeout(() => {
      void api<JsonRecord[]>(`/search?q=${encodeURIComponent(query.trim())}`).then(setResults).catch(() => setResults([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [open, query]);

  const filteredCommands = useMemo(() => commands.filter((command) => `${command.label} ${command.hint}`.toLowerCase().includes(query.toLowerCase())), [query]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-label="Search resources" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <Search />
          <input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search resources and actions…" />
          <button onClick={onClose} aria-label="Close"><X /></button>
        </header>
        <div className="command-results">
          {filteredCommands.length ? <p className="result-label">Actions</p> : null}
          {filteredCommands.map(({ label, hint, view, icon: Icon }) => (
            <button key={view} onClick={() => { onNavigate(view); onClose(); }}>
              <span className="command-icon"><Icon /></span>
              <span><strong>{label}</strong><small>{hint}</small></span>
              <ArrowRight />
            </button>
          ))}
          {results.length ? <p className="result-label">Observed resources</p> : null}
          {results.map((result, index) => {
            const resource = result.resource && typeof result.resource === "object" ? result.resource as JsonRecord : result;
            const type = String(resource.resource_type ?? resource.type ?? "resource");
            const label = String(resource.label ?? resource.name ?? resource.id ?? "Resource");
            return (
              <button key={String(resource.id ?? index)} onClick={() => { onNavigate(type === "project" ? "workspaces" : type === "container" ? "containers" : "topology"); onClose(); }}>
                <ResourceGlyph type={type} size="small" />
                <span><strong>{label}</strong><small>{type.replaceAll("_", " ")}</small></span>
                <ArrowRight />
              </button>
            );
          })}
          {!filteredCommands.length && !results.length ? <EmptyState title="No matching resources" description="Try a project, process, port, or action." icon={Search} /> : null}
        </div>
      </section>
    </div>
  );
}
