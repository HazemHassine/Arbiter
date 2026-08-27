"use client";

import { CodeIcon as FileCode2, ReloadIcon as RefreshCw, ResetIcon as RotateCcw, CheckIcon as Save, MagnifyingGlassIcon as Search, LockClosedIcon as ShieldCheck } from "@radix-ui/react-icons";
import { useEffect, useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, LoadingRows, PageHeader, Panel, StatusBadge } from "@/components/ui";
import { api, post } from "@/lib/api";
import { formatBytes, formatDate } from "@/lib/format";
import type { FileContent, JsonRecord, Project, ProjectFile } from "@/lib/types";
import { useResource } from "@/hooks/use-resource";

export function FilesView({ refreshKey, notify }: { refreshKey: number; notify: (message: string, tone?: string) => void }) {
  const projects = useResource<Project[]>("/projects", [], refreshKey);
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [selectedPath, setSelectedPath] = useState("");
  const [original, setOriginal] = useState<FileContent | null>(null);
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<JsonRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = Boolean(original && content !== original.content);
  const selectedProject = useMemo(() => projects.data.find((project) => project.id === projectId), [projectId, projects.data]);

  useEffect(() => {
    if (!projectId) { setFiles([]); setSelectedPath(""); setOriginal(null); return; }
    setLoading(true); setError(null);
    void api<ProjectFile[]>(`/projects/${projectId}/files`).then((result) => { setFiles(result); setSelectedPath(result[0]?.path ?? ""); }).catch((reason) => setError(reason instanceof Error ? reason.message : "Unable to load files")).finally(() => setLoading(false));
  }, [projectId, refreshKey]);

  useEffect(() => {
    if (!projectId || !selectedPath) { setOriginal(null); setContent(""); return; }
    setLoading(true); setError(null); setPreview(null);
    void api<FileContent>(`/projects/${projectId}/files/content?path=${encodeURIComponent(selectedPath)}`).then((result) => { setOriginal(result); setContent(result.content); }).catch((reason) => setError(reason instanceof Error ? reason.message : "Unable to read file")).finally(() => setLoading(false));
  }, [projectId, selectedPath]);

  async function previewChange() {
    if (!original || !dirty) return;
    setLoading(true);
    try { setPreview(await post<JsonRecord>(`/projects/${projectId}/files/preview`, { path: original.path, content, expected_sha256: original.sha256 })); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Preview failed", "error"); }
    finally { setLoading(false); }
  }

  async function saveChange() {
    if (!original || !dirty) return;
    setLoading(true);
    try { const result = await post<JsonRecord>(`/projects/${projectId}/files/save`, { path: original.path, content, expected_sha256: original.sha256 }); notify(result.status === "approval_required" ? "File update is waiting for approval" : "File update proposed", "success"); setPreview(result.preview as JsonRecord ?? preview); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Save proposal failed", "error"); }
    finally { setLoading(false); }
  }

  async function undo() {
    if (!original) return;
    try { const result = await post<JsonRecord>(`/projects/${projectId}/files/undo`, { path: original.path }); notify(result.status === "approval_required" ? "Undo is waiting for approval" : "Undo proposed", "success"); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Undo proposal failed", "error"); }
  }

  return (
    <>
      <PageHeader eyebrow="Safe configuration editor" title="Files" description="Review, diff, validate, and approval-protect configuration changes inside registered roots." actions={<select className="heading-select" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">Select a workspace…</option>{projects.data.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}</select>} />
      <ErrorNotice message={projects.error || error} />
      {!projectId ? <EmptyState title="Choose a workspace" description="Only known configuration files inside explicitly registered roots can be opened." icon={FileCode2} /> : <div className="file-layout">
        <Panel className="file-browser">
          <header><div><h2>{selectedProject?.name}</h2><p>{selectedProject?.path}</p></div><Button variant="ghost" onClick={() => setProjectId((value) => value)}><RefreshCw /></Button></header>
          {loading && !files.length ? <LoadingRows /> : <nav>{files.map((file) => <button key={file.path} className={selectedPath === file.path ? "active" : ""} onClick={() => { if (!dirty || window.confirm("Discard the unsaved editor change?")) setSelectedPath(file.path); }}><FileCode2 /><span><strong>{file.path}</strong><small>{file.kind || "configuration"} · {formatBytes(file.size)}</small></span></button>)}</nav>}
          <footer><ShieldCheck /><span><strong>Registered files only</strong><small>Paths are resolved below the project root.</small></span></footer>
        </Panel>
        <Panel className="editor-panel">
          <header className="editor-head"><div><span className="eyebrow">{original?.kind || "Configuration"}</span><h2>{original?.path || "Select a file"}</h2>{original ? <p>SHA {original.sha256.slice(0, 12)} · loaded {formatDate(new Date())}</p> : null}</div><div>{dirty ? <StatusBadge value="modified" /> : <StatusBadge value="saved" />}<Button disabled={!dirty || loading} onClick={() => { if (original) setContent(original.content); setPreview(null); }}>Reset</Button><Button disabled={!dirty || loading} onClick={() => void previewChange()}><Search /> Preview diff</Button><Button variant="primary" disabled={!dirty || loading} onClick={() => void saveChange()}><Save /> Propose save</Button></div></header>
          <textarea className="code-editor" value={content} onChange={(event) => { setContent(event.target.value); setPreview(null); }} disabled={!original || loading} spellCheck={false} aria-label="Project file editor" />
          <footer className="editor-foot"><span>Every save is diffed, validated, backed up, and approval-protected.</span><Button variant="ghost" disabled={!original} onClick={() => void undo()}><RotateCcw /> Undo latest managed edit</Button></footer>
        </Panel>
        {preview ? <Panel className="diff-panel"><header><div><span className="eyebrow">Change preview</span><h2>{String(preview.path ?? original?.path)}</h2></div><StatusBadge value={(preview.validation as JsonRecord)?.valid === false ? "invalid" : "validated"} /></header><pre>{String(preview.diff ?? "No textual diff returned.")}</pre></Panel> : null}
      </div>}
    </>
  );
}
