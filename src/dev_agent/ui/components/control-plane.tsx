"use client";

import {
  Activity,
  Archive,
  Bot,
  Box,
  CheckCircle2,
  ChevronLeft,
  Command,
  Container,
  ExternalLink,
  FileCode2,
  FolderKanban,
  History,
  Home,
  Menu,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Route,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { classes } from "@/lib/format";
import { AdminView } from "@/views/admin";
import { AgentView } from "@/views/agent";
import { DockerView } from "@/views/docker";
import { FilesView } from "@/views/files";
import { ObservabilityView } from "@/views/observability";
import { OverviewView } from "@/views/overview";
import { PortsView } from "@/views/ports";
import { ProjectsView } from "@/views/projects";
import { ContainersView, ProcessesView } from "@/views/runtime";
import { ApprovalsView, AuditView } from "@/views/safety";
import { SettingsView } from "@/views/settings";
import { TopologyView } from "@/views/topology";
import { CommandPalette } from "./command-palette";

type ViewId = "overview" | "workspaces" | "topology" | "activity" | "containers" | "processes" | "ports" | "files" | "docker" | "projects" | "agent" | "approvals" | "history" | "admin" | "settings";
interface NavItem { id: ViewId; label: string; icon: LucideIcon; count?: "projects" | "containers" | "ports" | "approvals" }

const groups: Array<{ label: string; items: NavItem[] }> = [
  { label: "Workspace", items: [{ id: "overview", label: "Overview", icon: Home }, { id: "workspaces", label: "Workspaces", icon: FolderKanban, count: "projects" }, { id: "topology", label: "Topology", icon: Network }] },
  { label: "Runtime", items: [{ id: "activity", label: "Observability", icon: Activity }, { id: "containers", label: "Containers", icon: Container, count: "containers" }, { id: "processes", label: "Processes", icon: Terminal }, { id: "ports", label: "Ports", icon: Route, count: "ports" }] },
  { label: "Manage", items: [{ id: "files", label: "Files", icon: FileCode2 }, { id: "docker", label: "Docker resources", icon: Box }, { id: "projects", label: "Registry", icon: Archive }, { id: "agent", label: "Ask agent", icon: Sparkles }] },
  { label: "Safety", items: [{ id: "approvals", label: "Approvals", icon: ShieldCheck, count: "approvals" }, { id: "history", label: "Audit log", icon: History }, { id: "admin", label: "Admin", icon: Bot }, { id: "settings", label: "Settings", icon: Settings }] },
];
const viewTitles = Object.fromEntries(groups.flatMap((group) => group.items.map((item) => [item.id, item.label]))) as Record<ViewId, string>;
const validViews = new Set(Object.keys(viewTitles));

export function ControlPlane() {
  const [view, setView] = useState<ViewId>("overview");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [healthy, setHealthy] = useState(false);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [toasts, setToasts] = useState<Array<{ id: number; message: string; tone: string }>>([]);

  const navigate = useCallback((target: string) => {
    if (!validViews.has(target)) return;
    const next = target as ViewId;
    setView(next);
    setMobileOpen(false);
    if (window.location.hash !== `#${next}`) window.history.pushState(null, "", `#${next}`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const notify = useCallback((message: string, tone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 4200);
  }, []);

  const refreshCounts = useCallback(async () => {
    const settled = await Promise.allSettled([api<unknown[]>("/projects"), api<unknown[]>("/containers"), api<unknown[]>("/ports"), api<Array<{ status?: string }>>("/approvals")]);
    const value = (index: number) => settled[index].status === "fulfilled" ? (settled[index] as PromiseFulfilledResult<unknown[]>).value : [];
    setCounts({ projects: value(0).length, containers: value(1).length, ports: value(2).length, approvals: (value(3) as Array<{ status?: string }>).filter((item) => item.status === "pending").length });
    setLastSync(new Date());
  }, []);

  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    if (validViews.has(fromHash)) setView(fromHash as ViewId);
    const onHash = () => { const target = window.location.hash.slice(1); if (validViews.has(target)) setView(target as ViewId); };
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setPaletteOpen(true); }
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("hashchange", onHash); window.removeEventListener("keydown", onKey); };
  }, []);

  useEffect(() => {
    const check = async () => { try { await api("/health"); setHealthy(true); } catch { setHealthy(false); } };
    void check(); void refreshCounts();
    const timer = window.setInterval(() => { void check(); void refreshCounts(); }, 15000);
    return () => window.clearInterval(timer);
  }, [refreshCounts]);

  const refresh = () => { setRefreshKey((value) => value + 1); setLastSync(new Date()); void refreshCounts(); };
  const activeContent = useMemo(() => {
    const shared = { refreshKey };
    switch (view) {
      case "overview": return <OverviewView {...shared} onNavigate={navigate} />;
      case "workspaces": return <ProjectsView {...shared} notify={notify} />;
      case "topology": return <TopologyView {...shared} notify={notify} />;
      case "activity": return <ObservabilityView {...shared} notify={notify} />;
      case "containers": return <ContainersView {...shared} notify={notify} />;
      case "processes": return <ProcessesView {...shared} />;
      case "ports": return <PortsView {...shared} />;
      case "files": return <FilesView {...shared} notify={notify} />;
      case "docker": return <DockerView {...shared} notify={notify} />;
      case "projects": return <ProjectsView {...shared} registry notify={notify} />;
      case "agent": return <AgentView notify={notify} />;
      case "approvals": return <ApprovalsView {...shared} notify={notify} />;
      case "history": return <AuditView {...shared} />;
      case "admin": return <AdminView {...shared} />;
      case "settings": return <SettingsView {...shared} />;
    }
  }, [navigate, notify, refreshKey, view]);

  return (
    <div className={classes("app-shell", collapsed && "sidebar-collapsed")}>
      {mobileOpen ? <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" /> : null}
      <aside className={classes("sidebar", mobileOpen && "mobile-open")}>
        <div className="sidebar-top"><button className="brand" onClick={() => navigate("overview")} aria-label="Localhost home"><span className="brand-mark"><Command /></span><span><strong>localhost</strong><small>control plane</small></span></button><button className="collapse-button" onClick={() => setCollapsed((value) => !value)} aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}>{collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}</button><button className="mobile-close" onClick={() => setMobileOpen(false)}><X /></button></div>
        <button className="workspace-switcher" id="resource-selector" onClick={() => setPaletteOpen(true)}><span><Search /></span><span><small>Inspecting</small><strong>All local resources</strong></span><ChevronLeft /></button>
        <nav>{groups.map((group) => <section key={group.label}><p>{group.label}</p>{group.items.map(({ id, label, icon: Icon, count }) => <button key={id} id={id === "admin" ? "view-admin" : undefined} className={view === id ? "active" : ""} onClick={() => navigate(id)} title={collapsed ? label : undefined}><span><Icon /></span><b>{label}</b>{id === "activity" ? <i className="nav-live" /> : count && counts[count] !== undefined ? <em>{counts[count]}</em> : null}</button>)}</section>)}</nav>
        <footer><div className="daemon-state"><i className={healthy ? "online" : ""} /><span><strong>{healthy ? "Daemon online" : "Connecting"}</strong><small>127.0.0.1 · local only</small></span></div><a href="/docs" target="_blank"><ExternalLink /> <span>API reference</span></a></footer>
      </aside>
      <main className="main">
        <header className="topbar"><button className="mobile-menu" onClick={() => setMobileOpen(true)}><Menu /></button><div className="breadcrumbs"><span>Local environment</span><i>/</i><strong>{viewTitles[view]}</strong></div><div className="top-actions"><span className="sync-state">{lastSync ? `Updated ${lastSync.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Syncing…"}</span><span className="live-pill"><i /> Live</span><button className="command-button" onClick={() => setPaletteOpen(true)}><Search /><span>Search resources…</span><kbd>⌘ K</kbd></button><button className="icon-button" onClick={refresh} title="Refresh current view"><RefreshCw /></button><button className="button primary ask-button" onClick={() => navigate("agent")}><Sparkles /> Ask AI</button></div></header>
        <div className="content" key={view}>{activeContent}</div>
      </main>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} onNavigate={navigate} />
      <div className="toast-stack">{toasts.map((toast) => <div key={toast.id} className={`toast ${toast.tone}`}>{toast.tone === "success" ? <CheckCircle2 /> : toast.tone === "error" ? <ShieldCheck /> : <RefreshCw />}<span>{toast.message}</span></div>)}</div>
      <div hidden aria-hidden="true"><pre id="container-log-output" /><iframe id="preview-frame" title="Local application preview" /></div>
    </div>
  );
}
