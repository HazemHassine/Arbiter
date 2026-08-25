"use client";

import { Box, Container as ContainerIcon, Cpu, ExternalLink, Play, RefreshCw, Search, Square, Terminal } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, LoadingRows, PageHeader, Panel, SearchInput, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { post } from "@/lib/api";
import { asText, shortId } from "@/lib/format";
import type { Container, JsonRecord } from "@/lib/types";

export function ContainersView({ refreshKey, notify }: { refreshKey: number; notify: (message: string, tone?: string) => void }) {
  const containers = useResource<Container[]>("/containers", [], refreshKey);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const filtered = useMemo(() => containers.data.filter((item) => JSON.stringify(item).toLowerCase().includes(query.toLowerCase())), [containers.data, query]);

  async function action(container: Container, operation: "start" | "stop" | "restart") {
    setBusy(`${container.id}-${operation}`);
    try {
      const result = await post<JsonRecord>(`/containers/${encodeURIComponent(container.id)}/${operation}`);
      notify(result.status === "approval_required" ? "Approval created" : `${container.name} ${operation} requested`, "success");
      await containers.refresh();
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Container operation failed", "error"); }
    finally { setBusy(null); }
  }

  return (
    <>
      <PageHeader eyebrow="Docker runtime" title="Containers" description="Inspect state, project ownership, bindings, and lifecycle operations." actions={<Button onClick={() => void containers.refresh()}><RefreshCw /> Refresh</Button>} />
      <ErrorNotice message={containers.error} onRetry={() => void containers.refresh()} />
      <div className="table-toolbar standalone"><div><h2>Container inventory</h2><p>{containers.data.filter((item) => item.state === "running").length} running of {containers.data.length}</p></div><SearchInput value={query} onChange={setQuery} placeholder="Filter containers" /></div>
      {containers.loading ? <div className="card-grid"><Panel><LoadingRows /></Panel><Panel><LoadingRows /></Panel></div> : filtered.length ? <div className="card-grid">{filtered.map((container) => (
        <Panel className="container-card" key={container.id}>
          <header><span className="container-glyph"><ContainerIcon /></span><div><h2>{container.name}</h2><p>{container.image}</p></div><StatusBadge value={container.state} /></header>
          <dl><div><dt>Container ID</dt><dd><code>{shortId(container.id)}</code></dd></div><div><dt>Compose project</dt><dd>{container.compose_project || "—"}</dd></div><div><dt>Service</dt><dd>{container.compose_service || "—"}</dd></div><div><dt>Networks</dt><dd>{container.networks?.join(", ") || "—"}</dd></div></dl>
          <div className="binding-list">{container.ports?.length ? container.ports.map((binding, index) => <span key={index}>{asText(binding.host_port ?? binding)}</span>) : <span>No published ports</span>}</div>
          <footer>{container.state === "running" ? <Button variant="ghost" disabled={busy !== null} onClick={() => void action(container, "stop")}><Square /> Stop</Button> : <Button variant="ghost" disabled={busy !== null} onClick={() => void action(container, "start")}><Play /> Start</Button>}<Button variant="primary" disabled={busy !== null} onClick={() => void action(container, "restart")}><RefreshCw /> Restart</Button></footer>
        </Panel>
      ))}</div> : <EmptyState title={query ? "No matching containers" : "No containers found"} description="Docker resources appear here when the runtime is available." icon={query ? Search : ContainerIcon} />}
    </>
  );
}

export function ProcessesView({ refreshKey }: { refreshKey: number }) {
  const processes = useResource<JsonRecord[]>("/processes", [], refreshKey);
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => processes.data.filter((item) => JSON.stringify(item).toLowerCase().includes(query.toLowerCase())), [processes.data, query]);
  return (
    <>
      <PageHeader eyebrow="Local runtime" title="Processes" description="Development-runtime evidence joined with host port ownership." actions={<Button onClick={() => void processes.refresh()}><RefreshCw /> Refresh</Button>} />
      <ErrorNotice message={processes.error} onRetry={() => void processes.refresh()} />
      <Panel className="table-panel">
        <div className="table-toolbar"><div><h2>Observed development processes</h2><p>{processes.data.length} correlated processes</p></div><SearchInput value={query} onChange={setQuery} placeholder="Filter PID, command, or cwd" /></div>
        {processes.loading ? <LoadingRows /> : filtered.length ? <div className="table-wrap"><table><thead><tr><th>Process</th><th>PID</th><th>Working directory</th><th>Listening ports</th><th>Kind</th><th>Confidence</th></tr></thead><tbody>{filtered.map((process, index) => <tr key={String(process.pid ?? index)}><td className="process-cell"><span><Terminal /></span><div><strong>{asText(process.process ?? process.name)}</strong><small>{asText(process.command)}</small></div></td><td><code>{asText(process.pid)}</code></td><td className="path-cell">{asText(process.cwd)}</td><td><div className="port-pills compact">{Array.isArray(process.ports) ? process.ports.map((port) => <button key={String(port)}>{asText(port)}</button>) : "—"}</div></td><td><StatusBadge value={process.kind} dot={false} /></td><td>{Number(process.confidence) ? `${Math.round(Number(process.confidence) * 100)}%` : "—"}</td></tr>)}</tbody></table></div> : <EmptyState title={query ? "No matching processes" : "No development processes detected"} description="Only processes with development-runtime or listener evidence are shown." icon={query ? Search : Cpu} />}
      </Panel>
    </>
  );
}

export function RuntimeDetailLink({ port }: { port: number }) {
  return <a href={`http://127.0.0.1:${port}`} target="_blank" rel="noreferrer"><ExternalLink /> Open</a>;
}
