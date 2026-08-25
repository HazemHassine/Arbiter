"use client";

import { Brain, Focus, Maximize2, Network, RefreshCw, Search, ZoomIn, ZoomOut } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, KeyValue, LoadingRows, PageHeader, Panel, ResourceGlyph, SearchInput, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { post } from "@/lib/api";
import { asText, classes } from "@/lib/format";
import type { JsonRecord, Project, TopologyGraph, TopologyNode } from "@/lib/types";

interface PositionedNode extends TopologyNode { x: number; y: number }

const typeOrder = ["project", "compose_project", "compose_service", "container", "process", "port", "image", "volume", "network", "dockerfile", "makefile", "make_target", "runtime"];

export function TopologyView({ refreshKey, notify }: { refreshKey: number; notify: (message: string, tone?: string) => void }) {
  const [project, setProject] = useState("");
  const [query, setQuery] = useState("");
  const [interpretedIds, setInterpretedIds] = useState<Set<string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [interpreting, setInterpreting] = useState(false);
  const projects = useResource<Project[]>("/projects", [], refreshKey);
  const graph = useResource<TopologyGraph>(`/topology${project ? `?project=${encodeURIComponent(project)}` : ""}`, { nodes: [], edges: [] }, refreshKey);

  const localMatches = useMemo(() => {
    if (!query.trim()) return null;
    const normalized = query.toLowerCase();
    return new Set(graph.data.nodes.filter((node) => `${node.label} ${node.resource_type} ${JSON.stringify(node.attributes ?? {})}`.toLowerCase().includes(normalized)).map((node) => node.id));
  }, [graph.data.nodes, query]);
  const matchIds = interpretedIds ?? localMatches;
  const positioned = useMemo(() => layoutGraph(graph.data.nodes), [graph.data.nodes]);
  const nodeMap = useMemo(() => new Map(positioned.map((node) => [node.id, node])), [positioned]);
  const selected = graph.data.nodes.find((node) => node.id === selectedId) ?? null;
  const connected = useMemo(() => selectedId ? new Set(graph.data.edges.flatMap((edge) => edge.source === selectedId ? [edge.target] : edge.target === selectedId ? [edge.source] : [])) : new Set<string>(), [graph.data.edges, selectedId]);

  async function interpret() {
    if (!query.trim()) return;
    setInterpreting(true);
    try {
      const result = await post<JsonRecord>("/intelligence/filter", { query: query.trim(), project: project || null, use_ai: true });
      const rawNodes = (result.matched_node_ids ?? result.nodes ?? result.matches ?? result.resources) as unknown;
      const ids = Array.isArray(rawNodes) ? rawNodes.map((item) => typeof item === "string" ? item : String((item as JsonRecord).id ?? "")).filter(Boolean) : [];
      setInterpretedIds(new Set(ids));
      notify(`Structured filter matched ${ids.length} resources`, "success");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Unable to interpret filter", "error"); }
    finally { setInterpreting(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Connected local resources" title="Resource topology" description="Trace relationships from project configuration to processes, containers, and listening ports." actions={<Button onClick={() => void graph.refresh()}><RefreshCw /> Refresh graph</Button>} />
      <div className="topology-toolbar"><SearchInput value={query} onChange={(value) => { setQuery(value); setInterpretedIds(null); }} placeholder="Try ‘running containers on port 5173’" /><Button onClick={() => void interpret()} disabled={!query.trim() || interpreting}><Brain /> {interpreting ? "Interpreting" : "Interpret"}</Button><select value={project} onChange={(event) => { setProject(event.target.value); setSelectedId(null); }}><option value="">All observed resources</option>{projects.data.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select><div className="zoom-controls"><button onClick={() => setZoom((value) => Math.max(.55, value - .15))}><ZoomOut /></button><span>{Math.round(zoom * 100)}%</span><button onClick={() => setZoom((value) => Math.min(1.8, value + .15))}><ZoomIn /></button><button onClick={() => setZoom(1)}><Maximize2 /> Fit</button></div></div>
      <ErrorNotice message={graph.error} onRetry={() => void graph.refresh()} />
      <div className="topology-layout">
        <Panel className="topology-canvas">
          <div className="topology-legend">{Array.from(new Set(graph.data.nodes.map((node) => node.resource_type))).map((type) => <span key={type}><i className={`node-color ${type}`} />{type.replaceAll("_", " ")}</span>)}</div>
          {graph.loading ? <LoadingRows /> : positioned.length ? <div className="graph-scroll"><svg viewBox="0 0 1200 720" style={{ transform: `scale(${zoom})` }} role="img" aria-label="Development resource topology">
            <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
            <g className="graph-edges">{graph.data.edges.map((edge, index) => { const from = nodeMap.get(edge.source); const to = nodeMap.get(edge.target); if (!from || !to) return null; const active = selectedId && (edge.source === selectedId || edge.target === selectedId); return <g key={`${edge.source}-${edge.target}-${index}`} className={active ? "active" : ""}><line x1={from.x + 72} y1={from.y + 24} x2={to.x + 72} y2={to.y + 24} markerEnd="url(#arrow)" /><text x={(from.x + to.x) / 2 + 72} y={(from.y + to.y) / 2 + 18}>{edge.relationship}</text></g>; })}</g>
            <g className="graph-nodes">{positioned.map((node) => { const dim = matchIds !== null && !matchIds.has(node.id); const focus = selectedId === node.id; const related = connected.has(node.id); return <g key={node.id} transform={`translate(${node.x} ${node.y})`} className={classes("graph-node", node.resource_type, dim && "dim", focus && "selected", related && "related")} role="button" tabIndex={0} onClick={() => setSelectedId(node.id)} onKeyDown={(event) => { if (event.key === "Enter") setSelectedId(node.id); }}><rect width="144" height="48" rx="8" /><circle cx="18" cy="24" r="8" /><text className="node-label" x="34" y="21">{node.label.slice(0, 18)}</text><text className="node-type" x="34" y="35">{node.resource_type.replaceAll("_", " ")}</text></g>; })}</g>
          </svg></div> : <EmptyState title="No connected resources" description="Register a project or start a runtime to build the graph." icon={Network} />}
        </Panel>
        <Panel className="topology-detail">
          {selected ? <><header><ResourceGlyph type={selected.resource_type} size="large" /><div><span className="eyebrow">{selected.resource_type.replaceAll("_", " ")}</span><h2>{selected.label}</h2></div></header><StatusBadge value={selected.status || "observed"} /><div className="key-value-stack"><KeyValue label="Resource ID" value={<code>{selected.id}</code>} />{Object.entries(selected.attributes ?? {}).slice(0, 10).map(([key, value]) => <KeyValue key={key} label={key.replaceAll("_", " ")} value={asText(value)} />)}</div>{selected.evidence?.length ? <div className="evidence-block"><h3>Evidence</h3>{selected.evidence.map((item) => <p key={item}><Focus />{item}</p>)}</div> : null}</> : <EmptyState title="Inspect a node" description="Select a resource to see its attributes and connected evidence." icon={Focus} />}
        </Panel>
      </div>
    </>
  );
}

function layoutGraph(nodes: TopologyNode[]): PositionedNode[] {
  const buckets = new Map<string, TopologyNode[]>();
  nodes.forEach((node) => buckets.set(node.resource_type, [...(buckets.get(node.resource_type) ?? []), node]));
  const types = [...buckets.keys()].sort((a, b) => (typeOrder.indexOf(a) < 0 ? 99 : typeOrder.indexOf(a)) - (typeOrder.indexOf(b) < 0 ? 99 : typeOrder.indexOf(b)));
  const columns = Math.min(6, Math.max(1, types.length));
  return types.flatMap((type, typeIndex) => {
    const column = typeIndex % columns;
    const band = Math.floor(typeIndex / columns);
    return (buckets.get(type) ?? []).map((node, row) => ({ ...node, x: 28 + column * 190, y: 42 + band * 310 + row * 66 }));
  });
}
