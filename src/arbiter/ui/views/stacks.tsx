"use client";

import {
  ActivityLogIcon as Activity,
  ArchiveIcon as Archive,
  CheckCircledIcon as CheckCircle2,
  ChevronRightIcon as ChevronRight,
  Cross2Icon as X,
  CubeIcon as Box,
  ExclamationTriangleIcon as AlertTriangle,
  LayersIcon as Layers,
  MixerHorizontalIcon as Wrench,
  PlayIcon as Play,
  PlusIcon as Plus,
  ReloadIcon as RefreshCw,
  StopIcon as Stop,
  UpdateIcon as History,
} from "@radix-ui/react-icons";
import * as React from "react";
import { useCallback, useEffect, useState } from "react";

import { Button, EmptyState, LoadingRows, PageHeader, Panel, PanelHeader, StatusBadge } from "@/components/ui";
import { api, post, remove } from "@/lib/api";
import { classes } from "@/lib/format";
import type {
  Project,
  ReadinessGate,
  ReadinessAuthorization,
  ReadinessProbeResult,
  StackBootPlan,
  StackPreset,
  StackSwitchResult,
} from "@/lib/types";

interface StacksViewProps {
  refreshKey?: number;
  notify?: (message: string, tone?: string) => void;
}

export function StacksView({ refreshKey = 0, notify }: StacksViewProps) {
  const [stacks, setStacks] = useState<StackPreset[]>([]);
  const [activeStack, setActiveStack] = useState<StackPreset | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedStackId, setSelectedStackId] = useState<string | null>(null);
  const [bootPlan, setBootPlan] = useState<StackBootPlan | null>(null);
  const [readinessResults, setReadinessResults] = useState<ReadinessProbeResult[]>([]);
  const [readinessAuthorizations, setReadinessAuthorizations] = useState<ReadinessAuthorization[]>([]);
  const [loading, setLoading] = useState(true);
  const [probing, setProbing] = useState(false);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [switchModalResult, setSwitchModalResult] = useState<StackSwitchResult | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Form state for creating a stack
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newTags, setNewTags] = useState("");
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [stacksData, activeData, projectsData, authorizationsData] = await Promise.all([
        api<StackPreset[]>("/stacks"),
        api<StackPreset | null>("/stacks/active"),
        api<Project[]>("/projects"),
        api<ReadinessAuthorization[]>("/readiness/authorizations"),
      ]);
      setStacks(stacksData);
      setActiveStack(activeData);
      setProjects(projectsData);
      setReadinessAuthorizations(authorizationsData);

      const targetId = selectedStackId || activeData?.id || stacksData[0]?.id;
      if (targetId) {
        setSelectedStackId(targetId);
        void loadBootPlanAndReadiness(targetId);
      }
    } catch (err: any) {
      notify?.(err?.message || "Failed to load stack presets", "error");
    } finally {
      setLoading(false);
    }
  }, [notify, selectedStackId]);

  const loadBootPlanAndReadiness = async (stackId: string) => {
    try {
      const [plan, readiness] = await Promise.all([
        api<StackBootPlan>(`/stacks/${stackId}/boot-order`),
        api<ReadinessProbeResult[]>(`/stacks/${stackId}/readiness`),
      ]);
      setBootPlan(plan);
      setReadinessResults(readiness);
    } catch {
      // Ignored if stack missing
    }
  };

  useEffect(() => {
    void loadData();
  }, [loadData, refreshKey]);

  const handleSelectStack = (stackId: string) => {
    setSelectedStackId(stackId);
    void loadBootPlanAndReadiness(stackId);
  };

  const handleSeedDefaults = async () => {
    try {
      const seeded = await post<StackPreset[]>("/stacks/seed-defaults");
      notify?.(`Generated ${seeded.length} default stack preset templates`, "success");
      void loadData();
    } catch (err: any) {
      notify?.(err?.message || "Failed to generate presets", "error");
    }
  };

  const handleRunProbes = async () => {
    if (!selectedStackId) return;
    setProbing(true);
    try {
      const results = await api<ReadinessProbeResult[]>(`/stacks/${selectedStackId}/readiness`);
      setReadinessResults(results);
      notify?.(`Evaluated ${results.length} readiness probes`, "success");
    } catch (err: any) {
      notify?.(err?.message || "Failed to run readiness probes", "error");
    } finally {
      setProbing(false);
    }
  };

  const handleRequestProbeAccess = async () => {
    if (!selectedStackId) return;
    try {
      const requests = await post<Array<{ approval: { id: string } }>>(
        `/stacks/${selectedStackId}/readiness/authorizations`,
      );
      notify?.(
        requests.length ? `Created ${requests.length} scoped readiness approval request(s)` : "No new access is required",
        requests.length ? "info" : "success",
      );
    } catch (err: any) {
      notify?.(err?.message || "Failed to request readiness access", "error");
    }
  };

  const handleRevokeProbeAccess = async (authorization: ReadinessAuthorization) => {
    if (!confirm(`Revoke readiness access to ${authorization.host}:${authorization.port}?`)) return;
    try {
      await remove(`/readiness/authorizations/${authorization.id}`);
      notify?.(`Revoked readiness access to ${authorization.host}:${authorization.port}`, "success");
      void loadData();
    } catch (err: any) {
      notify?.(err?.message || "Failed to revoke readiness access", "error");
    }
  };

  const handleSwitchStack = async (stack: StackPreset) => {
    setSwitchingId(stack.id);
    try {
      const res = await post<any>(`/stacks/${stack.id}/switch`, {
        hibernate_current: true,
        wait_for_readiness: true,
        resolve_port_conflicts: true,
      });

      if (res?.status === "approval_required") {
        notify?.(`Switch proposed (Approval ${res.approval.id})`, "info");
      } else if (res?.status === "readiness_access_required") {
        setReadinessResults(res.readiness as ReadinessProbeResult[]);
        notify?.("Authorize the highlighted readiness destinations before switching", "info");
      } else if (res?.action?.result) {
        const switchRes = res.action.result as StackSwitchResult;
        setSwitchModalResult(switchRes);
        notify?.(`Switched to stack '${stack.name}' successfully!`, "success");
      } else {
        notify?.(`Context switch to '${stack.name}' initiated`, "success");
      }
      void loadData();
    } catch (err: any) {
      notify?.(err?.message || `Failed to switch to stack ${stack.name}`, "error");
    } finally {
      setSwitchingId(null);
    }
  };

  const handleStopStack = async (stack: StackPreset) => {
    try {
      await post<any>(`/stacks/${stack.id}/stop`, { hibernate: true });
      notify?.(`Stack '${stack.name}' stopped/hibernated`, "success");
      void loadData();
    } catch (err: any) {
      notify?.(err?.message || `Failed to stop stack ${stack.name}`, "error");
    }
  };

  const handleDeleteStack = async (stackId: string, name: string) => {
    if (!confirm(`Delete stack preset "${name}"?`)) return;
    try {
      await remove(`/stacks/${stackId}`);
      notify?.(`Deleted stack preset '${name}'`, "success");
      void loadData();
    } catch (err: any) {
      notify?.(err?.message || "Failed to delete stack", "error");
    }
  };

  const handleCreateStack = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const selectedMembers = selectedProjectIds.map((pid, idx) => {
        const p = projects.find((proj) => proj.id === pid);
        return {
          project_id: pid,
          project_name: p?.name || pid,
          boot_stage: idx === 0 ? 0 : 1,
          depends_on: idx > 0 ? [projects.find((proj) => proj.id === selectedProjectIds[0])?.name || ""] : [],
        };
      });

      await post<StackPreset>("/stacks", {
        name: newName.trim(),
        description: newDesc.trim() || undefined,
        tags: newTags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        projects: selectedMembers,
      });

      notify?.(`Created stack preset '${newName}'`, "success");
      setShowCreateModal(false);
      setNewName("");
      setNewDesc("");
      setNewTags("");
      setSelectedProjectIds([]);
      void loadData();
    } catch (err: any) {
      notify?.(err?.message || "Failed to create stack preset", "error");
    }
  };

  const selectedStack = stacks.find((s) => s.id === selectedStackId);

  return (
    <div className="view-container">
      <PageHeader
        eyebrow="Multi-Project Workspace Orchestration"
        title="Stack Presets & Environment Switcher"
        description="Group interdependent repositories into operational stacks. 1-Click switch contexts with dynamic .env port binding & collision resolution, and visualize dependency health checks."
        actions={
          <div className="heading-actions">
            <Button variant="secondary" onClick={handleSeedDefaults}>
              <Box /> Seed Presets
            </Button>
            <Button variant="primary" onClick={() => setShowCreateModal(true)}>
              <Plus /> New Stack Preset
            </Button>
            <Button variant="secondary" onClick={loadData}>
              <RefreshCw /> Refresh
            </Button>
          </div>
        }
      />

      {/* Active Stack Banner */}
      {activeStack ? (
        <Panel className="active-stack-banner">
          <div className="active-banner-content">
            <div className="active-banner-left">
              <span className="live-indicator-dot" />
              <div>
                <small>CURRENT ACTIVE ENVIRONMENT</small>
                <h3>{activeStack.name}</h3>
                <p>{activeStack.description || "Active context with managed port reservations & boot health."}</p>
              </div>
            </div>
            <div className="active-banner-right">
              <span className="active-pill">ACTIVE CONTEXT</span>
              <Button variant="secondary" onClick={() => handleStopStack(activeStack)}>
                <Stop /> Hibernate Stack
              </Button>
            </div>
          </div>
        </Panel>
      ) : null}

      {/* Stack Presets Catalog */}
      <section className="stacks-grid-section">
        <PanelHeader
          title="Configured Stack Presets"
          description="Click 'Switch Context' to hibernate background services and boot the target stack."
        />

        {loading ? (
          <LoadingRows count={3} />
        ) : stacks.length === 0 ? (
          <EmptyState
            title="No Stack Presets Configured"
            description="Create your first stack preset or click 'Seed Presets' to generate pre-configured templates."
            icon={Layers}
          />
        ) : (
          <div className="stack-cards-grid">
            {stacks.map((stack) => {
              const isActive = activeStack?.id === stack.id || stack.is_active;
              const isSelected = selectedStackId === stack.id;
              const isSwitching = switchingId === stack.id;

              return (
                <div
                  key={stack.id}
                  className={classes("stack-card", isActive && "active-card", isSelected && "selected-card")}
                  onClick={() => handleSelectStack(stack.id)}
                >
                  <div className="stack-card-header">
                    <div>
                      <div className="stack-title-row">
                        <h4>{stack.name}</h4>
                        {isActive ? (
                          <span className="status-pill active">ACTIVE</span>
                        ) : (
                          <StatusBadge value={stack.status || "inactive"} />
                        )}
                      </div>
                      <p className="stack-desc">{stack.description || "Multi-project stack preset"}</p>
                    </div>
                  </div>

                  <div className="stack-tags">
                    {(stack.tags || []).map((tag) => (
                      <span key={tag} className="tag-pill">
                        #{tag}
                      </span>
                    ))}
                  </div>

                  <div className="stack-projects-list">
                    <small>MEMBER PROJECTS ({stack.projects.length})</small>
                    <div className="project-chips">
                      {stack.projects.map((p, idx) => (
                        <span key={p.project_id || idx} className="project-chip">
                          <Archive /> {p.project_name}
                          {p.depends_on && p.depends_on.length > 0 ? (
                            <em title={`Depends on: ${p.depends_on.join(", ")}`}>↳ dep</em>
                          ) : null}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="stack-card-actions" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant={isActive ? "secondary" : "primary"}
                      disabled={isSwitching}
                      onClick={() => handleSwitchStack(stack)}
                    >
                      {isSwitching ? <RefreshCw className="spin" /> : <Play />}
                      {isActive ? "Re-apply Stack" : "1-Click Switch"}
                    </Button>
                    <Button variant="ghost" onClick={() => handleSelectStack(stack.id)}>
                      <Activity /> Boot Order
                    </Button>
                    <Button variant="ghost" onClick={() => handleDeleteStack(stack.id, stack.name)}>
                      <X />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Dependency Boot Order & Readiness Gates Visualizer */}
      {selectedStack ? (
        <Panel className="boot-order-panel">
          <PanelHeader
            title={`Dependency Boot Order & Readiness Gates: ${selectedStack.name}`}
            description="Topological execution order. Arbiter checks readiness gates (e.g. Postgres :5432, Redis :6379) before booting dependent services."
            action={
              <div className="panel-actions">
                <Button variant="secondary" disabled={probing} onClick={handleRunProbes}>
                  <RefreshCw className={probing ? "spin" : ""} /> Run Readiness Probes
                </Button>
                {readinessResults.some((result) => result.policy_status === "approval_required") ? (
                  <Button variant="primary" onClick={handleRequestProbeAccess}>
                    <AlertTriangle /> Request Probe Access
                  </Button>
                ) : null}
              </div>
            }
          />

          {bootPlan ? (
            <div className="boot-stages-visualizer">
              {bootPlan.cycle_detected ? (
                <div className="error-notice">
                  <AlertTriangle />
                  <span>Circular dependency detected in stack configuration. Fallback ordering applied.</span>
                </div>
              ) : null}

              <div className="stages-timeline">
                {bootPlan.stages.map((stage, stageIdx) => (
                  <div key={stage.stage} className="stage-block">
                    <div className="stage-marker">
                      <div className="stage-badge">STAGE {stage.stage + 1}</div>
                      {stageIdx < bootPlan.stages.length - 1 ? <div className="stage-connector" /> : null}
                    </div>

                    <div className="stage-body">
                      <div className="stage-projects-box">
                        <strong>Booting Projects in Parallel:</strong>
                        <div className="stage-project-pills">
                          {stage.projects.map((pName) => (
                            <span key={pName} className="stage-project-pill">
                              <Archive /> {pName}
                            </span>
                          ))}
                        </div>
                      </div>

                      {stage.readiness_gates && stage.readiness_gates.length > 0 ? (
                        <div className="stage-gates-box">
                          <small>READINESS GATES ({stage.readiness_gates.length})</small>
                          <div className="gates-grid">
                            {stage.readiness_gates.map((gate, gIdx) => {
                              const probeResult = readinessResults.find(
                                (r) =>
                                  r.service === gate.service ||
                                  r.target.includes(String(gate.port || "")) ||
                                  (gate.service && r.target.includes(gate.service)),
                              );

                              return (
                                <div
                                  key={gIdx}
                                  className={classes(
                                    "gate-card",
                                    probeResult?.healthy ? "gate-healthy" : probeResult ? "gate-unhealthy" : "gate-pending",
                                  )}
                                >
                                  <div className="gate-icon">
                                    {gate.probe_type === "tcp_port" ? (
                                      <Wrench />
                                    ) : gate.probe_type === "http_get" ? (
                                      <Activity />
                                    ) : (
                                      <Box />
                                    )}
                                  </div>
                                  <div className="gate-details">
                                    <div className="gate-name-row">
                                      <b>{gate.service || `${gate.probe_type}`}</b>
                                      {probeResult ? (
                                        <span className={classes("gate-status-pill", probeResult.healthy ? "ok" : probeResult.policy_status === "approval_required" ? "pending" : "fail")}>
                                          {probeResult.healthy ? "HEALTHY" : probeResult.policy_status === "approval_required" ? "ACCESS NEEDED" : probeResult.policy_status === "blocked" ? "BLOCKED" : "OFFLINE"}
                                        </span>
                                      ) : (
                                        <span className="gate-status-pill pending">READY GATE</span>
                                      )}
                                    </div>
                                    <p className="gate-target">
                                      {gate.probe_type === "tcp_port"
                                        ? `TCP port :${gate.port}`
                                        : gate.probe_type === "http_get"
                                        ? `HTTP GET :${gate.port}${gate.path || "/"}`
                                        : `Docker state check`}
                                    </p>
                                    {probeResult ? (
                                      <small className="gate-meta">
                                        {probeResult.message}{probeResult.policy_status === "allowed" ? ` (${probeResult.latency_ms}ms)` : ""}
                                      </small>
                                    ) : (
                                      <small className="gate-meta">Awaits health confirmation</small>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ) : (
                        <p className="no-gates-note">No custom readiness gates required for this stage.</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <LoadingRows count={2} />
          )}
        </Panel>
      ) : null}

      <Panel className="readiness-access-panel">
        <PanelHeader
          title="Readiness Network Access"
          description="Persisted grants are limited to one protocol, host, port, and resolved IP set. Loopback requires no grant."
        />
        {readinessAuthorizations.length ? (
          <div className="readiness-access-list">
            {readinessAuthorizations.map((authorization) => (
              <div className="readiness-access-row" key={authorization.id}>
                <div>
                  <strong>{authorization.protocol.toUpperCase()} {authorization.host}:{authorization.port}</strong>
                  <small>{authorization.resolved_addresses.join(", ")} · approval {authorization.approval_id.slice(0, 8)}</small>
                </div>
                <Button variant="ghost" onClick={() => void handleRevokeProbeAccess(authorization)}><X /> Revoke</Button>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No non-local probe access" description="Loopback probes work automatically. Other destinations require approval." icon={Wrench} />}
      </Panel>

      {/* Switch Result Stepper Modal */}
      {switchModalResult ? (
        <div className="modal-scrim" onClick={() => setSwitchModalResult(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <header className="modal-header">
              <div className="modal-title-row">
                <CheckCircle2 className="success-icon" />
                <h3>Environment Context Switch Completed</h3>
              </div>
              <button className="icon-button" onClick={() => setSwitchModalResult(null)}>
                <X />
              </button>
            </header>

            <div className="modal-body">
              <div className="switch-stepper-summary">
                <div className="step-item done">
                  <div className="step-num">1</div>
                  <div>
                    <strong>Spin Down Old Stack</strong>
                    <p>
                      {switchModalResult.stopped_projects.length > 0
                        ? `Hibernated: ${switchModalResult.stopped_projects.join(", ")}`
                        : "No background projects required shutdown"}
                    </p>
                  </div>
                </div>

                <div className="step-item done">
                  <div className="step-num">2</div>
                  <div>
                    <strong>Dynamic .env Port Reconciliation</strong>
                    <p>
                      {switchModalResult.port_reconciliations.length > 0
                        ? `Reconciled ${switchModalResult.port_reconciliations.length} port collisions dynamically`
                        : "No port collisions detected; bindings verified"}
                    </p>
                  </div>
                </div>

                <div className="step-item done">
                  <div className="step-num">3</div>
                  <div>
                    <strong>Boot Sequence & Readiness Gates</strong>
                    <p>
                      {switchModalResult.started_projects.length > 0
                        ? `Booted ${switchModalResult.started_projects.join(", ")}`
                        : "Stack containers online"}
                    </p>
                  </div>
                </div>
              </div>

              {switchModalResult.readiness_results && switchModalResult.readiness_results.length > 0 ? (
                <div className="modal-readiness-results">
                  <small>READINESS PROBES SUMMARY</small>
                  <ul>
                    {switchModalResult.readiness_results.map((r, i) => (
                      <li key={i} className={r.healthy ? "healthy-item" : "unhealthy-item"}>
                        {r.healthy ? <CheckCircle2 /> : <AlertTriangle />}
                        <span>
                          <b>{r.service || r.target}</b>: {r.message} ({r.latency_ms}ms)
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>

            <footer className="modal-footer">
              <Button variant="primary" onClick={() => setSwitchModalResult(null)}>
                Close
              </Button>
            </footer>
          </div>
        </div>
      ) : null}

      {/* Create Stack Preset Modal */}
      {showCreateModal ? (
        <div className="modal-scrim" onClick={() => setShowCreateModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <form onSubmit={handleCreateStack}>
              <header className="modal-header">
                <h3>Create New Stack Preset</h3>
                <button type="button" className="icon-button" onClick={() => setShowCreateModal(false)}>
                  <X />
                </button>
              </header>

              <div className="modal-body form-body">
                <label>
                  <span>Stack Preset Name *</span>
                  <input
                    type="text"
                    required
                    placeholder="e.g., Billing Microservices"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </label>

                <label>
                  <span>Description</span>
                  <input
                    type="text"
                    placeholder="e.g., Payment processor, postgres ledger, and mock stripe api"
                    value={newDesc}
                    onChange={(e) => setNewDesc(e.target.value)}
                  />
                </label>

                <label>
                  <span>Tags (comma-separated)</span>
                  <input
                    type="text"
                    placeholder="e.g., billing, fintech, backend"
                    value={newTags}
                    onChange={(e) => setNewTags(e.target.value)}
                  />
                </label>

                <div className="form-group">
                  <span>Select Member Projects:</span>
                  <div className="projects-select-grid">
                    {projects.map((proj) => {
                      const isChecked = selectedProjectIds.includes(proj.id);
                      return (
                        <label key={proj.id} className={classes("project-select-label", isChecked && "checked")}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedProjectIds((prev) => [...prev, proj.id]);
                              } else {
                                setSelectedProjectIds((prev) => prev.filter((id) => id !== proj.id));
                              }
                            }}
                          />
                          <div>
                            <strong>{proj.name}</strong>
                            <small>{proj.path}</small>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </div>

              <footer className="modal-footer">
                <Button variant="ghost" onClick={() => setShowCreateModal(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary" disabled={!newName.trim()}>
                  Save Stack Preset
                </Button>
              </footer>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
