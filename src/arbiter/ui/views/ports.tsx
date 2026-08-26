"use client";

import { ExternalLink, Route, Search, WandSparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, LoadingRows, PageHeader, Panel, SearchInput, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { asText } from "@/lib/format";
import type { JsonRecord, PortOwner } from "@/lib/types";

export function PortsView({ refreshKey }: { refreshKey: number }) {
  const ports = useResource<PortOwner[]>("/ports", [], refreshKey);
  const conflicts = useResource<JsonRecord[]>("/ports/conflicts", [], refreshKey);
  const [query, setQuery] = useState("");
  const [start, setStart] = useState(3000);
  const [end, setEnd] = useState(4000);
  const [free, setFree] = useState<number[]>([]);
  const [finding, setFinding] = useState(false);
  const filtered = useMemo(() => ports.data.filter((port) => JSON.stringify(port).toLowerCase().includes(query.toLowerCase())), [ports.data, query]);

  async function findPorts() {
    setFinding(true);
    try { setFree(await api<number[]>(`/ports/free?start=${start}&end=${end}&count=8`)); } finally { setFinding(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Host network" title="Port coordination" description="Inspect listeners, runtime owners, declared bindings, and collisions." actions={<Button onClick={() => void ports.refresh()}>Refresh</Button>} />
      <ErrorNotice message={ports.error || conflicts.error} onRetry={() => { void ports.refresh(); void conflicts.refresh(); }} />
      <div className="split-grid">
        <Panel className="status-panel"><span className="eyebrow">Coordination</span><h2>Conflict status</h2><div className="big-status"><span className={conflicts.data.length ? "bad" : "good"}><Route /></span><div><strong>{conflicts.loading ? "Checking…" : conflicts.data.length ? `${conflicts.data.length} conflict${conflicts.data.length === 1 ? "" : "s"}` : "No conflicts detected"}</strong><p>Compared with registered project claims.</p></div></div></Panel>
        <Panel>
          <span className="eyebrow">Allocation</span><h2>Free-port finder</h2>
          <div className="inline-form"><input type="number" value={start} onChange={(event) => setStart(Number(event.target.value))} aria-label="Range start" /><span>to</span><input type="number" value={end} onChange={(event) => setEnd(Number(event.target.value))} aria-label="Range end" /><Button variant="primary" onClick={() => void findPorts()} disabled={finding}><WandSparkles /> {finding ? "Finding" : "Find"}</Button></div>
          <div className="port-pills">{free.map((port) => <button key={port} onClick={() => navigator.clipboard.writeText(String(port))}>{port}</button>)}</div>
        </Panel>
      </div>
      <Panel className="table-panel">
        <div className="table-toolbar"><div><h2>Observed listeners</h2><p>{ports.data.length} endpoints found on this machine</p></div><SearchInput value={query} onChange={setQuery} placeholder="Filter by port, owner, or project" /></div>
        {ports.loading ? <LoadingRows /> : filtered.length ? <div className="table-wrap"><table><thead><tr><th>Port</th><th>Protocol</th><th>Owner</th><th>Project / service</th><th>Source</th><th>Status</th><th /></tr></thead><tbody>{filtered.map((port, index) => { const owner = port.process || port.container || port.container_name || port.owner_type || "Unknown"; const project = port.project || port.project_name || port.service || "—"; return <tr key={`${port.protocol}-${port.port}-${index}`}><td><code className="port-code">:{port.port}</code></td><td>{port.protocol || "tcp"}</td><td><strong>{owner}</strong>{port.pid ? <small>PID {port.pid}</small> : null}</td><td>{project}</td><td>{asText(port.source || port.owner_type)}</td><td><StatusBadge value="listening" /></td><td>{[80, 443, 3000, 4173, 5000, 5173, 8000, 8080].includes(port.port) ? <a className="icon-link" href={`http://127.0.0.1:${port.port}`} target="_blank" rel="noreferrer"><ExternalLink /></a> : null}</td></tr>; })}</tbody></table></div> : <EmptyState title={query ? "No matching listeners" : "No listeners observed"} description="Port ownership evidence will appear after the next host scan." icon={query ? Search : Route} />}
      </Panel>
    </>
  );
}
