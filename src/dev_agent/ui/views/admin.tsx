"use client";

import { Activity, Bot, Clock3, Database, ExternalLink, FileText, Gauge, Radio, RefreshCw, ShieldCheck, Terminal, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, EmptyState, ErrorNotice, KeyValue, LoadingRows, MetricCard, PageHeader, Panel, PanelHeader, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { asText, formatBytes } from "@/lib/format";
import type { JsonRecord } from "@/lib/types";

type AdminTab = "observability" | "harness" | "documentation";

export function AdminView({ refreshKey }: { refreshKey: number }) {
  const overview = useResource<JsonRecord>("/admin/overview", {}, refreshKey);
  const [tab, setTab] = useState<AdminTab>("observability");
  useEffect(() => { const timer = window.setInterval(() => void overview.refresh(), 10000); return () => window.clearInterval(timer); }, [overview.refresh]);
  const telemetry = record(overview.data.telemetry);
  const requests = record(telemetry.requests);
  const latency = record(requests.latency_ms);
  const llm = record(telemetry.llm);
  const database = record(overview.data.database);

  return (
    <>
      <PageHeader eyebrow="Control plane internals" title="Agent administration" description="Process health, API/model usage, event delivery, persistence, and the safety harness." actions={<><StatusBadge value="auto-refreshing" /><Button onClick={() => void overview.refresh()}><RefreshCw /> Refresh</Button></>} />
      <div className="tab-bar admin-tabs"><button className={tab === "observability" ? "active" : ""} onClick={() => setTab("observability")}><Activity /> Observability</button><button className={tab === "harness" ? "active" : ""} onClick={() => setTab("harness")}><ShieldCheck /> Agent harness</button><button className={tab === "documentation" ? "active" : ""} onClick={() => setTab("documentation")}><FileText /> Documentation</button></div>
      <ErrorNotice message={overview.error} onRetry={() => void overview.refresh()} />
      {overview.loading && !Object.keys(overview.data).length ? <Panel><LoadingRows /></Panel> : tab === "observability" ? <AdminObservability overview={overview.data} requests={requests} latency={latency} llm={llm} database={database} /> : tab === "harness" ? <Harness data={record(overview.data.harness)} /> : <Documentation data={record(overview.data.documentation)} />}
    </>
  );
}

function AdminObservability({ overview, requests, latency, llm, database }: { overview: JsonRecord; requests: JsonRecord; latency: JsonRecord; llm: JsonRecord; database: JsonRecord }) {
  const telemetry = record(overview.telemetry);
  const events = record(overview.events);
  const process = record(overview.process);
  const samples = Array.isArray(requests.samples) ? requests.samples as JsonRecord[] : [];
  const routes = Array.isArray(requests.routes) ? requests.routes as JsonRecord[] : [];
  return <>
    <div className="metric-grid admin-metrics"><MetricCard label="Process uptime" value={formatDuration(Number(telemetry.uptime_seconds))} note="Current daemon process" icon={Clock3} tone="green" /><MetricCard label="API requests" value={asText(requests.total)} note={`${asText(requests.requests_last_minute)} in the last minute`} icon={Activity} tone="blue" /><MetricCard label="p95 latency" value={`${asText(latency.p95)} ms`} note={`${Math.round(Number(requests.error_rate || 0) * 100)}% error rate`} icon={Gauge} tone="purple" /><MetricCard label="Model calls" value={asText(llm.calls)} note={`${asText(llm.total_tokens)} tokens`} icon={Bot} tone="amber" /><MetricCard label="Persisted rows" value={asText(database.total_rows)} note={formatBytes(database.size_bytes)} icon={Database} tone="blue" /></div>
    <div className="admin-grid">
      <Panel className="span-2 chart-panel"><PanelHeader title="Request latency" description="Rolling process-local samples" action={<StatusBadge value={`${asText(requests.active)} active`} />} /><LatencyChart samples={samples} /></Panel>
      <Panel><PanelHeader title="Daemon process" description="Current runtime footprint" /><div className="key-value-stack"><KeyValue label="PID" value={asText(process.pid)} /><KeyValue label="Python" value={asText(process.python)} /><KeyValue label="Threads" value={asText(process.threads)} /><KeyValue label="RSS" value={formatBytes(process.rss_bytes)} /><KeyValue label="CPU time" value={`${asText(process.cpu_time_seconds)}s`} /></div></Panel>
      <Panel className="table-panel"><PanelHeader title="Most-used routes" description="Normalized route templates" />{routes.length ? <div className="table-wrap"><table><thead><tr><th>Route</th><th>Calls</th></tr></thead><tbody>{routes.map((route, index) => <tr key={index}><td><code>{asText(route.route)}</code></td><td>{asText(route.count)}</td></tr>)}</tbody></table></div> : <EmptyState title="No request samples" icon={Activity} />}</Panel>
      <Panel><PanelHeader title="LLM usage" description="Agent and structured-filter calls" /><div className="key-value-stack"><KeyValue label="Successful" value={asText(llm.successful)} /><KeyValue label="Failures" value={asText(llm.failures)} /><KeyValue label="Input tokens" value={asText(llm.input_tokens)} /><KeyValue label="Output tokens" value={asText(llm.output_tokens)} /><KeyValue label="Models" value={asText(llm.models)} /></div></Panel>
      <Panel><PanelHeader title="Event pipeline" description="SSE history and subscribers" /><div className="key-value-stack"><KeyValue label="Published total" value={asText(events.published_total)} /><KeyValue label="Buffered" value={`${asText(events.buffered)} / ${asText(events.history_capacity)}`} /><KeyValue label="Subscribers" value={asText(events.subscribers)} /><KeyValue label="Event types" value={asText(events.types)} /></div></Panel>
      <Panel><PanelHeader title="Persistence" description="Control-plane evidence database" /><div className="key-value-stack"><KeyValue label="Backend" value={asText(database.backend)} /><KeyValue label="Database size" value={formatBytes(database.size_bytes)} /><KeyValue label="Rows" value={asText(database.counts)} /><KeyValue label="Action status" value={asText(database.action_statuses)} /></div></Panel>
    </div>
  </>;
}

function LatencyChart({ samples }: { samples: JsonRecord[] }) {
  if (!samples.length) return <EmptyState title="No latency samples yet" description="Use the control plane and request history will appear here." icon={Gauge} />;
  const values = samples.map((sample) => Number(sample.duration_ms || 0));
  const max = Math.max(...values, 1);
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 780 + 20},${210 - (value / max) * 170}`).join(" ");
  return <div className="latency-chart"><svg viewBox="0 0 820 230" preserveAspectRatio="none"><defs><linearGradient id="latencyArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#6e8cff" stopOpacity=".28" /><stop offset="1" stopColor="#6e8cff" stopOpacity="0" /></linearGradient></defs><line x1="20" y1="210" x2="800" y2="210" /><line x1="20" y1="40" x2="800" y2="40" /><polygon points={`20,210 ${points} 800,210`} fill="url(#latencyArea)" /><polyline points={points} /></svg><span>0 ms</span><span>{max.toFixed(0)} ms</span></div>;
}

function Harness({ data }: { data: JsonRecord }) {
  const tools = Array.isArray(data.tools) ? data.tools as string[] : [];
  const policies = Array.isArray(data.policies) ? data.policies as JsonRecord[] : [];
  return <><div className="harness-summary"><Panel><Bot /><div><small>Agent model</small><strong>{asText(data.agent_model)}</strong><p>{data.provider_configured ? "Provider configured" : "Deterministic mode"}</p></div></Panel><Panel><Wrench /><div><small>Registered tools</small><strong>{asText(data.tool_count)}</strong><p>Typed evidence surfaces</p></div></Panel><Panel><ShieldCheck /><div><small>Safety boundary</small><strong>Medium risk</strong><p>Approval required and above</p></div></Panel><Panel><Terminal /><div><small>Project roots</small><strong>{Array.isArray(data.project_roots) ? data.project_roots.length : 0}</strong><p>Scan depth {asText(data.project_scan_depth)}</p></div></Panel></div><div className="admin-grid"><Panel><PanelHeader title="Registered tools" description="Read-only evidence and proposal surfaces" /><div className="tool-cloud">{tools.map((tool) => <span key={tool}><Wrench />{tool}</span>)}</div></Panel><Panel className="table-panel"><PanelHeader title="Safety policy" description="Mutation risk classification and approval boundary" /><div className="table-wrap"><table><thead><tr><th>Action</th><th>Risk</th><th>Approval</th></tr></thead><tbody>{policies.map((policy) => <tr key={String(policy.action)}><td><code>{asText(policy.action)}</code></td><td><StatusBadge value={policy.risk} dot={false} /></td><td>{policy.approval_required ? "Required" : "Automatic"}</td></tr>)}</tbody></table></div></Panel></div></>;
}

function Documentation({ data }: { data: JsonRecord }) {
  const sections = Array.isArray(data.sections) ? data.sections as JsonRecord[] : [];
  return <><Panel className="docs-hero"><span><Radio /></span><div><p className="eyebrow">Local developer control plane</p><h2>Operational handbook</h2><p>The agent observes first, builds typed evidence, proposes mutations, waits at the approval boundary, executes the stored action, and records verification.</p></div><div><a className="button primary" href="/docs" target="_blank"><ExternalLink /> Open API explorer</a><a className="button secondary" href="/redoc" target="_blank">ReDoc</a></div></Panel><div className="docs-grid">{sections.map((section) => <Panel key={String(section.title)}><span><FileText /></span><h2>{asText(section.title)}</h2><p>Inspect the live contract and supporting evidence for this control-plane capability.</p><code>{asText(section.endpoint)}</code></Panel>)}</div></>;
}

function record(value: unknown): JsonRecord { return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {}; }
function formatDuration(seconds: number): string { if (!Number.isFinite(seconds)) return "—"; if (seconds < 60) return `${Math.round(seconds)}s`; if (seconds < 3600) return `${Math.floor(seconds / 60)}m`; return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`; }
