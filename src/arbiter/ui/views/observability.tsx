"use client";

import { ActivityLogIcon as Activity, BoxIcon as ContainerIcon, CopyIcon as Copy, ExternalLinkIcon as ExternalLink, PauseIcon as Pause, PlayIcon as Play, RadiobuttonIcon as Radio, ReloadIcon as RefreshCw, MagnifyingGlassIcon as Route, MagnifyingGlassIcon as Search } from "@radix-ui/react-icons";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button, EmptyState, ErrorNotice, KeyValue, MetricCard, PageHeader, Panel, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { api, eventStreamUrl } from "@/lib/api";
import { asText, formatBytes, formatDate } from "@/lib/format";
import type { Container, JsonRecord, PortOwner, SystemEvent } from "@/lib/types";

export function ObservabilityView({ refreshKey, notify }: { refreshKey: number; notify: (message: string, tone?: string) => void }) {
  const initialEvents = useResource<SystemEvent[]>("/activity?limit=100", [], refreshKey);
  const containers = useResource<Container[]>("/containers", [], refreshKey);
  const ports = useResource<PortOwner[]>("/ports", [], refreshKey);
  const observation = useResource<JsonRecord>("/observation", {}, refreshKey);
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [paused, setPaused] = useState(false);
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"events" | "logs">("events");
  const [containerId, setContainerId] = useState("");
  const [logs, setLogs] = useState("Select a running container to begin tailing logs.");
  const [stats, setStats] = useState<JsonRecord>({});
  const [previewPort, setPreviewPort] = useState<number | null>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => { setEvents(initialEvents.data); }, [initialEvents.data]);
  useEffect(() => {
    const source = new EventSource(eventStreamUrl());
    source.onopen = () => setStreaming(true);
    source.onerror = () => setStreaming(false);
    source.onmessage = (message) => {
      if (pausedRef.current) return;
      try { const event = JSON.parse(message.data) as SystemEvent; setEvents((current) => [...current.slice(-249), event]); } catch { /* Ignore malformed stream frames. */ }
    };
    return () => source.close();
  }, []);

  useEffect(() => {
    if (!containerId || tab !== "logs") return;
    let active = true;
    const load = async () => {
      try {
        const [logResult, statResult] = await Promise.all([api<{ logs: string }>(`/containers/${encodeURIComponent(containerId)}/logs?tail=300`), api<JsonRecord>(`/containers/${encodeURIComponent(containerId)}/stats`)]);
        if (active) { setLogs(logResult.logs || "No log output."); setStats(statResult); }
      } catch (reason) { if (active) setLogs(reason instanceof Error ? reason.message : "Unable to load logs"); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => { active = false; window.clearInterval(timer); };
  }, [containerId, tab]);

  const filteredEvents = useMemo(() => events.filter((event) => JSON.stringify(event).toLowerCase().includes(search.toLowerCase())), [events, search]);
  const endpoints = useMemo(() => ports.data.filter((port) => [80, 443, 3000, 3001, 4173, 5000, 5173, 8000, 8080, 8787].includes(port.port)), [ports.data]);
  const running = containers.data.filter((item) => item.state === "running");
  const previewUrl = previewPort ? `http://127.0.0.1:${previewPort}` : "";

  return (
    <>
      <PageHeader eyebrow="Live runtime observation" title="Observability" description="One live console for system events, container logs, runtime metrics, and local previews." actions={<><StatusBadge value={streaming ? "live stream" : "reconnecting"} /><Button onClick={() => { void initialEvents.refresh(); void containers.refresh(); void ports.refresh(); }}><RefreshCw /> Refresh</Button></>} />
      <ErrorNotice message={initialEvents.error || containers.error || ports.error} />
      <div className="metric-grid observe-metrics"><MetricCard label="Events buffered" value={events.length} note="Current browser session" icon={Activity} tone="green" /><MetricCard label="Containers running" value={running.length} note={`${containers.data.length} observed`} icon={ContainerIcon} tone="blue" /><MetricCard label="Active listeners" value={ports.data.length} note="Host port scan" icon={Route} tone="amber" /><MetricCard label="Observation interval" value={`${asText(observation.data.interval_seconds)}s`} note="Bounded polling" icon={Radio} tone="amber" /></div>
      <div className="observability-layout">
        <Panel className="console-panel">
          <header className="console-head"><div className="console-tabs"><button className={tab === "events" ? "active" : ""} onClick={() => setTab("events")}>Events</button><button className={tab === "logs" ? "active" : ""} onClick={() => setTab("logs")}>Container logs</button></div><div className="console-actions">{tab === "logs" ? <select value={containerId} onChange={(event) => setContainerId(event.target.value)}><option value="">Select container…</option>{running.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select> : <label><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter output" /></label>}<Button variant="ghost" onClick={() => setPaused((value) => !value)}>{paused ? <Play /> : <Pause />}{paused ? "Resume" : "Pause"}</Button><Button variant="ghost" onClick={() => navigator.clipboard.writeText(tab === "logs" ? logs : JSON.stringify(filteredEvents, null, 2)).then(() => notify("Copied to clipboard", "success"))}><Copy /> Copy</Button></div></header>
          <div className="console-body">{tab === "logs" ? <pre className="log-output">{logs}</pre> : filteredEvents.length ? <div className="event-console">{filteredEvents.map((event, index) => <div className="console-event" key={String(event.id ?? index)}><time>{formatDate(event.created_at)}</time><span className={`event-action ${event.action || "event"}`}>{event.action || "event"}</span><span><strong>{event.message || event.type}</strong><small>{event.resource_type} · {event.resource_id}</small></span><code>{event.type}</code></div>)}</div> : <EmptyState title="No matching events" icon={Activity} />}</div>
          <footer className="console-foot"><span><i className={streaming ? "live" : ""} />{streaming ? "Event stream connected" : "Reconnecting to stream"}</span><span>{tab === "logs" ? "Refreshes every 4s" : `${filteredEvents.length} entries`}</span></footer>
        </Panel>
        <aside className="observe-side">
          <Panel className="preview-panel"><header><div className="browser-dots"><i /><i /><i /></div><select value={previewPort ?? ""} onChange={(event) => setPreviewPort(event.target.value ? Number(event.target.value) : null)}><option value="">Select detected endpoint…</option>{endpoints.map((endpoint) => <option value={endpoint.port} key={`${endpoint.protocol}-${endpoint.port}`}>localhost:{endpoint.port} · {endpoint.process || endpoint.container || endpoint.service || "HTTP candidate"}</option>)}</select>{previewUrl ? <a href={previewUrl} target="_blank" rel="noreferrer" aria-label="Open preview"><ExternalLink /></a> : null}</header><div className="preview-frame">{previewUrl ? <iframe src={previewUrl} title="Local application preview" /> : <EmptyState title="Local preview" description="Select a likely HTTP listener. Services that block embedding can still be opened in a new tab." icon={Route} />}</div></Panel>
          <Panel className="runtime-stats"><header><div><h2>Runtime metrics</h2><p>Selected container snapshot</p></div><StatusBadge value={containerId ? "live" : "no selection"} /></header>{containerId ? <div className="key-value-stack"><KeyValue label="CPU" value={asText(stats.cpu_percent ?? stats.cpu)} /><KeyValue label="Memory" value={formatBytes(stats.memory_usage ?? stats.memory)} /><KeyValue label="Memory limit" value={formatBytes(stats.memory_limit)} /><KeyValue label="Network RX" value={formatBytes(stats.network_rx ?? stats.rx_bytes)} /><KeyValue label="Network TX" value={formatBytes(stats.network_tx ?? stats.tx_bytes)} /><KeyValue label="PIDs" value={asText(stats.pids ?? stats.pid_count)} /></div> : <EmptyState title="Choose a container" description="Select Container logs to load an on-demand metrics snapshot." icon={ContainerIcon} />}</Panel>
        </aside>
      </div>
    </>
  );
}
