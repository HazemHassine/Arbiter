"use client";

import { CheckIcon as Check, ClockIcon as Clock3, UpdateIcon as History, ReloadIcon as RefreshCw, ExclamationTriangleIcon as ShieldAlert, Cross2Icon as X } from "@radix-ui/react-icons";
import { useMemo, useState } from "react";

import { Button, EmptyState, ErrorNotice, LoadingRows, PageHeader, Panel, StatusBadge } from "@/components/ui";
import { useResource } from "@/hooks/use-resource";
import { post } from "@/lib/api";
import { asText, formatDate, shortId } from "@/lib/format";
import type { ActionRecord, Approval } from "@/lib/types";

export function ApprovalsView({ refreshKey, notify }: { refreshKey: number; notify: (message: string, tone?: string) => void }) {
  const approvals = useResource<Approval[]>("/approvals", [], refreshKey);
  const [busy, setBusy] = useState<string | null>(null);
  const pending = approvals.data.filter((item) => item.status === "pending");

  async function decide(approval: Approval, decision: "approve" | "reject") {
    setBusy(approval.id);
    try { await post(`/approvals/${approval.id}/${decision}`); notify(decision === "approve" ? "Action approved and executed" : "Approval rejected", "success"); await approvals.refresh(); }
    catch (reason) { notify(reason instanceof Error ? reason.message : "Decision failed", "error"); }
    finally { setBusy(null); }
  }

  return (
    <>
      <PageHeader eyebrow="Safety gate" title="Approvals" description="Review the exact operation and arguments before anything changes." actions={<Button onClick={() => void approvals.refresh()}><RefreshCw /> Refresh</Button>} />
      <ErrorNotice message={approvals.error} onRetry={() => void approvals.refresh()} />
      {approvals.loading ? <Panel><LoadingRows /></Panel> : pending.length ? <div className="approval-list">{pending.map((approval) => <Panel className="approval-card" key={approval.id}>
        <div className={`risk-stripe ${approval.risk.toLowerCase()}`}><ShieldAlert /><strong>{approval.risk.replaceAll("_", " ")}</strong></div>
        <div className="approval-copy"><header><div><span className="eyebrow">{approval.action}</span><h2>{approval.summary}</h2></div><StatusBadge value={approval.status} /></header><div className="approval-args"><pre>{JSON.stringify(approval.arguments ?? {}, null, 2)}</pre></div><footer><span><Clock3 /> {formatDate(approval.created_at)} · {shortId(approval.id)}</span><div><Button variant="danger" disabled={busy !== null} onClick={() => void decide(approval, "reject")}><X /> Reject</Button><Button variant="primary" disabled={busy !== null} onClick={() => void decide(approval, "approve")}><Check /> Approve & execute</Button></div></footer></div>
      </Panel>)}</div> : <EmptyState title="No pending approvals" description="Operations that cross the safety boundary will wait here for an explicit decision." icon={Check} />}
    </>
  );
}

export function AuditView({ refreshKey }: { refreshKey: number }) {
  const actions = useResource<ActionRecord[]>("/actions", [], refreshKey);
  const [filter, setFilter] = useState("all");
  const filtered = useMemo(() => filter === "all" ? actions.data : actions.data.filter((action) => action.status === filter), [actions.data, filter]);
  return (
    <>
      <PageHeader eyebrow="Action history" title="Audit log" description="Every proposed operation, decision, execution result, and verification outcome." actions={<Button onClick={() => void actions.refresh()}><RefreshCw /> Refresh</Button>} />
      <ErrorNotice message={actions.error} onRetry={() => void actions.refresh()} />
      <div className="filter-tabs"><button className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>All</button><button className={filter === "completed" ? "active" : ""} onClick={() => setFilter("completed")}>Completed</button><button className={filter === "failed" ? "active" : ""} onClick={() => setFilter("failed")}>Failed</button></div>
      <Panel className="table-panel">
        {actions.loading ? <LoadingRows /> : filtered.length ? <div className="table-wrap"><table><thead><tr><th>Action</th><th>Risk</th><th>Status</th><th>Verification</th><th>Request</th></tr></thead><tbody>{filtered.map((action) => <tr key={action.id}><td><strong>{action.action}</strong>{action.error ? <small className="error-text">{action.error}</small> : null}</td><td><StatusBadge value={action.risk} dot={false} /></td><td><StatusBadge value={action.status} /></td><td>{asText(action.verification)}</td><td><code>{shortId(action.request_id || action.id)}</code></td></tr>)}</tbody></table></div> : <EmptyState title="No actions recorded" description="Proposed and executed operations will appear in this append-only history." icon={History} />}
      </Panel>
    </>
  );
}
