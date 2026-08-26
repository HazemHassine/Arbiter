"use client";

import { ArrowRight, FolderKanban, Play, RefreshCw, ScanSearch, Square, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, LoadingRows, PageHeader, Panel, ResourceGlyph, SearchInput, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { post, remove } from "@/lib/api";
import type { JsonRecord, Project } from "@/lib/types";

interface ProjectsViewProps { refreshKey: number; registry?: boolean; notify: (message: string, tone?: string) => void }

export function ProjectsView({ refreshKey, registry = false, notify }: ProjectsViewProps) {
  const projects = useResource<Project[]>("/projects", [], refreshKey);
  const [query, setQuery] = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const filtered = useMemo(() => projects.data.filter((project) => `${project.name} ${project.path}`.toLowerCase().includes(query.toLowerCase())), [projects.data, query]);

  async function run(label: string, operation: () => Promise<unknown>) {
    setBusy(label);
    try {
      const result = await operation() as JsonRecord;
      notify(String(result?.status === "approval_required" ? "Approval created" : "Operation completed"), "success");
      await projects.refresh();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Operation failed", "error"); }
    finally { setBusy(null); }
  }

  async function register() {
    if (!path.trim()) return;
    await run("register", () => post("/projects", { path: path.trim() }));
    setPath("");
  }

  return (
    <>
      <PageHeader
        eyebrow={registry ? "Project registry" : "Connected projects"}
        title={registry ? "Registry" : "Workspaces"}
        description={registry ? "Explicitly register and manage trusted project roots." : "Project-level runtime state, configuration, services, and local processes."}
        actions={<><Button onClick={() => void run("scan", () => post("/projects/scan"))} disabled={busy !== null}><ScanSearch /> Scan roots</Button><Button onClick={() => void projects.refresh()}><RefreshCw /> Refresh</Button></>}
      />
      <ErrorNotice message={projects.error} onRetry={() => void projects.refresh()} />
      {registry ? <Panel className="register-panel"><div><h2>Register a workspace</h2><p>The path must be inside a configured project root.</p></div><div className="register-form"><input value={path} onChange={(event) => setPath(event.target.value)} placeholder="/home/user/dev/project" onKeyDown={(event) => { if (event.key === "Enter") void register(); }} /><Button variant="primary" onClick={() => void register()} disabled={!path.trim() || busy !== null}>Register</Button></div></Panel> : null}
      <div className="table-toolbar standalone"><div><h2>{registry ? "Registered projects" : "Workspace inventory"}</h2><p>{projects.data.length} project roots</p></div><SearchInput value={query} onChange={setQuery} placeholder="Filter workspaces" /></div>
      {projects.loading ? <div className="card-grid"><Panel><LoadingRows /></Panel><Panel><LoadingRows /></Panel></div> : filtered.length ? <div className="card-grid">{filtered.map((project) => <ProjectCard key={project.id} project={project} registry={registry} busy={busy} onRun={run} />)}</div> : <EmptyState title={query ? "No matching workspaces" : "No projects registered"} description={registry ? "Register a trusted root or scan configured project directories." : "Use Scan roots to discover local workspaces."} icon={FolderKanban} />}
    </>
  );
}

function ProjectCard({ project, registry, busy, onRun }: { project: Project; registry: boolean; busy: string | null; onRun: (label: string, operation: () => Promise<unknown>) => Promise<void> }) {
  const services = Array.isArray(project.services) ? project.services : [];
  const ports = Array.isArray(project.ports) ? project.ports : [];
  const disabled = busy !== null;
  return (
    <Panel className="project-card">
      <header><ResourceGlyph type="project" size="large" /><div><h2>{project.name}</h2><p>{project.path}</p></div><StatusBadge value={project.registered === false ? "discovered" : "registered"} /></header>
      <div className="project-stats"><span><small>Services</small><strong>{services.length}</strong></span><span><small>Ports</small><strong>{ports.length}</strong></span><span><small>Compose</small><strong>{project.compose_files?.length || 0}</strong></span></div>
      <div className="tag-list">{services.slice(0, 5).map((service) => <span key={service}>{service}</span>)}{!services.length ? <span>No services declared</span> : null}</div>
      <footer>
        {!registry ? <><Button variant="ghost" disabled={disabled} onClick={() => void onRun(`start-${project.id}`, () => post(`/projects/${project.id}/start`))}><Play /> Start</Button><Button variant="ghost" disabled={disabled} onClick={() => void onRun(`stop-${project.id}`, () => post(`/projects/${project.id}/stop`))}><Square /> Stop</Button><Button variant="primary" disabled={disabled} onClick={() => void onRun(`prepare-${project.id}`, () => post(`/projects/${project.id}/prepare`, { resolve_port_conflicts: true, start: true, verify: true }))}>Inspect & prepare <ArrowRight /></Button></> : <><Button variant="ghost" disabled={disabled} onClick={() => void onRun(`refresh-${project.id}`, () => post(`/projects/${project.id}/diagnose`))}><RefreshCw /> Diagnose</Button><Button variant="danger" disabled={disabled} onClick={() => void onRun(`remove-${project.id}`, () => remove(`/projects/${project.id}`))}><Trash2 /> Unregister</Button></>}
      </footer>
    </Panel>
  );
}
