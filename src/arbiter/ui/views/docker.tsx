"use client";

import { CubeIcon as Box, ArchiveIcon as Database, DiscIcon as HardDrive, Share2Icon as Network, ReloadIcon as RefreshCw, MagnifyingGlassIcon as Search, TrashIcon as Trash2 } from "@radix-ui/react-icons";
import { useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, KeyValue, LoadingRows, PageHeader, Panel, SearchInput, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { remove } from "@/lib/api";
import { asText, formatBytes, shortId } from "@/lib/format";
import type { JsonRecord } from "@/lib/types";

type DockerTab = "disk" | "images" | "volumes" | "networks";

export function DockerView({ refreshKey, notify }: { refreshKey: number; notify: (message: string, tone?: string) => void }) {
  const [tab, setTab] = useState<DockerTab>("disk");
  const [query, setQuery] = useState("");
  const disk = useResource<JsonRecord>(tab === "disk" ? "/docker/disk-usage" : null, {}, refreshKey);
  const list = useResource<JsonRecord[]>(tab === "disk" ? null : `/${tab}`, [], refreshKey);
  const filtered = useMemo(() => list.data.filter((item) => JSON.stringify(item).toLowerCase().includes(query.toLowerCase())), [list.data, query]);

  async function deleteResource(item: JsonRecord) {
    const identifier = String(item.id ?? item.name ?? "");
    if (!identifier) return;
    try { const result = await remove<JsonRecord>(`/${tab}/${encodeURIComponent(identifier)}`); notify(result.status === "approval_required" ? "Destructive action is waiting for approval" : "Operation proposed", "success"); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Unable to propose removal", "error"); }
  }

  return (
    <>
      <PageHeader eyebrow="Runtime storage" title="Docker resources" description="Inspect disk consumption, images, volumes, and networks without losing project context." actions={<Button onClick={() => { void disk.refresh(); void list.refresh(); }}><RefreshCw /> Refresh</Button>} />
      <div className="tab-bar">{(["disk", "images", "volumes", "networks"] as DockerTab[]).map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => { setTab(value); setQuery(""); }}>{value === "disk" ? <HardDrive /> : value === "images" ? <Box /> : value === "volumes" ? <Database /> : <Network />}{value === "disk" ? "Disk usage" : value[0].toUpperCase() + value.slice(1)}</button>)}</div>
      <ErrorNotice message={disk.error || list.error} onRetry={() => { void disk.refresh(); void list.refresh(); }} />
      {tab === "disk" ? <DiskUsage data={disk.data} loading={disk.loading} /> : <>
        <div className="table-toolbar standalone"><div><h2>{tab[0].toUpperCase() + tab.slice(1)}</h2><p>{list.data.length} resources</p></div><SearchInput value={query} onChange={setQuery} placeholder={`Filter ${tab}`} /></div>
        {list.loading ? <Panel><LoadingRows /></Panel> : filtered.length ? <div className="card-grid docker-grid">{filtered.map((item, index) => <DockerCard key={String(item.id ?? item.name ?? index)} tab={tab} item={item} onRemove={() => void deleteResource(item)} />)}</div> : <EmptyState title={query ? `No matching ${tab}` : `No ${tab} found`} description="Docker runtime resources will appear here when available." icon={Search} />}
      </>}
    </>
  );
}

function DiskUsage({ data, loading }: { data: JsonRecord; loading: boolean }) {
  if (loading) return <Panel><LoadingRows /></Panel>;
  const sections = ["images", "containers", "volumes", "build_cache"];
  return <div className="docker-disk-grid">{sections.map((key) => { const item = data[key] && typeof data[key] === "object" ? data[key] as JsonRecord : {}; return <Panel key={key} className="disk-card"><span className="disk-icon">{key === "volumes" ? <Database /> : key === "containers" ? <Box /> : <HardDrive />}</span><div><small>{key.replaceAll("_", " ")}</small><strong>{formatBytes(item.size ?? item.total_size ?? item.reclaimable_size)}</strong><p>{asText(item.count)} resources · {formatBytes(item.reclaimable ?? item.reclaimable_size)} reclaimable</p></div></Panel>; })}</div>;
}

function DockerCard({ tab, item, onRemove }: { tab: Exclude<DockerTab, "disk">; item: JsonRecord; onRemove: () => void }) {
  const title = String(item.name ?? (Array.isArray(item.tags) ? item.tags[0] : "") ?? shortId(item.id));
  const consumers = item.users ?? item.members;
  return <Panel className="docker-card"><header><span>{tab === "images" ? <Box /> : tab === "volumes" ? <Database /> : <Network />}</span><div><h2>{title || "Unnamed resource"}</h2><p>{shortId(item.id ?? item.name)}</p></div><StatusBadge value={item.status ?? (item.used || item.in_use ? "in use" : "observed")} dot={false} /></header><div className="key-value-grid compact"><KeyValue label="Created" value={asText(item.created_at ?? item.created)} /><KeyValue label="Size" value={formatBytes(item.size)} /><KeyValue label={tab === "networks" ? "Members" : "Users"} value={Array.isArray(consumers) ? consumers.length : "—"} /></div>{tab !== "networks" ? <footer><Button variant="danger" onClick={onRemove}><Trash2 /> Propose removal</Button></footer> : null}</Panel>;
}
