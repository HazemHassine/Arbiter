"use client";

import { Box, Check, Cpu, RefreshCw, Server, Settings2 } from "lucide-react";

import { Button, EmptyState, ErrorNotice, KeyValue, LoadingRows, PageHeader, Panel, PanelHeader, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { asText } from "@/lib/format";
import type { JsonRecord, RuntimeCapability } from "@/lib/types";

export function SettingsView({ refreshKey }: { refreshKey: number }) {
  const runtimes = useResource<RuntimeCapability[]>("/runtimes", [], refreshKey);
  const observation = useResource<JsonRecord>("/observation", {}, refreshKey);
  return (
    <>
      <PageHeader eyebrow="Local capabilities" title="Runtime capabilities" description="Detected local runtimes and the exact level of control this agent supports." actions={<Button onClick={() => { void runtimes.refresh(); void observation.refresh(); }}><RefreshCw /> Refresh</Button>} />
      <ErrorNotice message={runtimes.error || observation.error} onRetry={() => void runtimes.refresh()} />
      {runtimes.loading ? <Panel><LoadingRows /></Panel> : runtimes.data.length ? <div className="card-grid">{runtimes.data.map((runtime) => <Panel className="runtime-card" key={runtime.name}><header><span><Box /></span><div><h2>{runtime.name}</h2><p>{runtime.detail || runtime.version || runtime.executable || "Runtime adapter"}</p></div><StatusBadge value={runtime.available === false ? "unavailable" : runtime.support || runtime.status || "available"} /></header><div className="capability-list">{runtime.capabilities?.length ? runtime.capabilities.map((capability) => <span key={capability}><Check /> {capability.replaceAll("_", " ")}</span>) : <span>Inspection only</span>}</div></Panel>)}</div> : <EmptyState title="No runtimes detected" icon={Cpu} />}
      <Panel className="observation-card"><PanelHeader title="Observation service" description="Bounded host polling and Docker event delivery" /><div className="key-value-grid"><KeyValue label="Observer state" value={<StatusBadge value={observation.data.running ? "running" : "stopped"} />} /><KeyValue label="Interval" value={`${asText(observation.data.interval_seconds ?? observation.data.interval)}s`} /><KeyValue label="Events observed" value={asText(observation.data.events_observed ?? observation.data.events)} /><KeyValue label="Last scan" value={asText(observation.data.last_scan ?? observation.data.last_observation)} /></div><div className="settings-note"><Server /><div><strong>Local-only boundary</strong><p>The control plane is designed to bind to loopback. Add an authentication boundary before exposing it elsewhere.</p></div></div></Panel>
    </>
  );
}
