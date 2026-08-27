"use client";

import { Activity, ArrowRight, Box, Container as ContainerIcon, FolderKanban, Gauge, Route, ShieldCheck, Sparkles } from "lucide-react";

import { useResource } from "@/hooks/use-resource";
import { formatDate } from "@/lib/format";
import type { Approval, Container, JsonRecord, PortOwner, Project, SystemEvent } from "@/lib/types";
import { Button, EmptyState, ErrorNotice, LoadingRows, MetricCard, PageHeader, Panel, PanelHeader, ResourceGlyph, StatusBadge } from "@/components/ui";

export function OverviewView({ onNavigate, refreshKey }: { onNavigate: (view: string) => void; refreshKey: number }) {
  const ports = useResource<PortOwner[]>("/ports", [], refreshKey);
  const projects = useResource<Project[]>("/projects", [], refreshKey);
  const containers = useResource<Container[]>("/containers", [], refreshKey);
  const approvals = useResource<Approval[]>("/approvals", [], refreshKey);
  const activity = useResource<SystemEvent[]>("/activity?limit=8", [], refreshKey);
  const resources = useResource<JsonRecord>("/system/resources", {}, refreshKey);
  const running = containers.data.filter((item) => item.state === "running").length;
  const pending = approvals.data.filter((item) => item.status === "pending").length;
  const error = ports.error || projects.error || containers.error;

  return (
    <>
      <PageHeader
        eyebrow="System overview"
        title="Arbiter"
        description="A live view of every workspace, runtime, listener, and pending change on this machine."
        actions={<><Button onClick={() => onNavigate("topology")}>View topology</Button><Button variant="primary" onClick={() => onNavigate("activity")}><Activity /> Open observability</Button></>}
      />
      <ErrorNotice message={error} onRetry={() => { void ports.refresh(); void projects.refresh(); void containers.refresh(); }} />

      <Panel className="hero-card">
        <div className="hero-identity">
          <span className="hero-orbit"><Sparkles /></span>
          <div><span className="hero-kicker">Local environment arbiter</span><h2>System Overview</h2><p>Disclaimer: Use with caution. Ensure you have the necessary approvals before modifying system states.</p></div>
        </div>
        <div className="hero-status"><StatusBadge value={error ? "degraded" : "ready"} /><span><small>Scope</small><strong>Loopback only</strong></span><span><small>Mode</small><strong>Observe first</strong></span></div>
      </Panel>

      <div className="metric-grid">
        <MetricCard label="Listening ports" value={ports.loading ? "—" : ports.data.length} note="Observed on the host" icon={Route} tone="blue" />
        <MetricCard label="Workspaces" value={projects.loading ? "—" : projects.data.length} note="Registered roots" icon={FolderKanban} tone="purple" />
        <MetricCard label="Running containers" value={containers.loading ? "—" : running} note={`${containers.data.length} known to Docker`} icon={ContainerIcon} tone="green" />
        <MetricCard label="Pending approvals" value={approvals.loading ? "—" : pending} note="Waiting at the safety gate" icon={ShieldCheck} tone={pending ? "amber" : "green"} />
      </div>

      <div className="overview-grid">
        <Panel className="span-2">
          <PanelHeader title="Recent activity" description="Live machine and Docker events" action={<button className="text-button" onClick={() => onNavigate("activity")}>View all <ArrowRight /></button>} />
          {activity.loading ? <LoadingRows /> : activity.data.length ? <div className="event-list compact">{activity.data.map((event, index) => <EventRow key={String(event.id ?? index)} event={event} />)}</div> : <EmptyState title="No recent events" description="Runtime events will appear here as they are observed." icon={Activity} />}
        </Panel>
        <Panel>
          <PanelHeader title="System resources" description="Host capacity at a glance" />
          <ResourceBars resources={resources.data} loading={resources.loading} />
        </Panel>
        <Panel className="span-2">
          <PanelHeader title="Workspaces" description="Registered project roots" action={<button className="text-button" onClick={() => onNavigate("workspaces")}>Manage <ArrowRight /></button>} />
          {projects.loading ? <LoadingRows count={3} /> : projects.data.length ? <div className="resource-list">{projects.data.slice(0, 5).map((project) => <button key={project.id} onClick={() => onNavigate("workspaces")}><ResourceGlyph type="project" /><span><strong>{project.name}</strong><small>{project.path}</small></span><StatusBadge value="registered" dot={false} /></button>)}</div> : <EmptyState title="No workspaces registered" description="Scan configured project roots from the Workspaces view." icon={FolderKanban} />}
        </Panel>
        <Panel className="quick-card">
          <span className="quick-card-icon"><Gauge /></span>
          <h2>Trace the machine</h2>
          <p>See how projects, processes, containers, and ports connect.</p>
          <Button variant="primary" onClick={() => onNavigate("topology")}>Open resource map <ArrowRight /></Button>
        </Panel>
      </div>
    </>
  );
}

function EventRow({ event }: { event: SystemEvent }) {
  const type = String(event.event_type ?? event.kind ?? event.action ?? "event");
  const resource = String(event.resource ?? event.resource_id ?? event.source ?? "system");
  const message = String(event.message ?? event.detail ?? type.replaceAll("_", " "));
  return <div className="event-row"><span className="event-dot" /><time>{formatDate(event.timestamp ?? event.created_at)}</time><span><strong>{message}</strong><small>{resource}</small></span><code>{type}</code></div>;
}

function ResourceBars({ resources, loading }: { resources: JsonRecord; loading: boolean }) {
  if (loading) return <LoadingRows count={3} />;
  const memory = resources.memory && typeof resources.memory === "object" ? resources.memory as JsonRecord : {};
  const disk = resources.disk && typeof resources.disk === "object" ? resources.disk as JsonRecord : {};
  const memoryTotal = Number(memory.MemTotal ?? 0);
  const memoryAvailable = Number(memory.MemAvailable ?? 0);
  const swapTotal = Number(memory.SwapTotal ?? 0);
  const swapFree = Number(memory.SwapFree ?? 0);
  const diskTotal = Number(disk.total ?? 0);
  const diskUsed = Number(disk.used ?? 0);
  const memoryPercent = Number(memory.percent ?? resources.memory_percent ?? (memoryTotal ? ((memoryTotal - memoryAvailable) / memoryTotal) * 100 : 0));
  const swapPercent = swapTotal ? ((swapTotal - swapFree) / swapTotal) * 100 : 0;
  const diskPercent = Number(disk.percent ?? resources.disk_percent ?? (diskTotal ? (diskUsed / diskTotal) * 100 : 0));
  const rows = [["Memory", memoryPercent], ["Swap", swapPercent], ["Disk", diskPercent]] as const;
  return <div className="resource-bars">{rows.map(([label, value]) => <div key={label}><span><strong>{label}</strong><b>{Number.isFinite(value) ? `${value.toFixed(0)}%` : "—"}</b></span><i><em style={{ width: `${Math.max(0, Math.min(100, value || 0))}%` }} /></i></div>)}</div>;
}
