const API = "/api/v1";
const state = {
  ports: [], projects: [], containers: [], approvals: [], actions: [],
  dockerTab: "disk", historyFilter: "all",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
})[char]);
const shortId = value => value ? String(value).slice(0, 10) : "—";
const fmtBytes = value => {
  if (!Number.isFinite(Number(value))) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(value), index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
};
const statusClass = value => String(value || "unknown").toLowerCase().replaceAll(" ", "_");
const badge = value => `<span class="badge ${statusClass(value)}">${esc(value || "unknown")}</span>`;
const icon = (name, className = "") => window.iconPack?.icon(name, className) || "";

async function request(path, options = {}) {
  const config = { ...options, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } };
  const direct = path === "/health" || path.startsWith("/api/") || path.startsWith("/.");
  const url = direct ? path : `${API}${path.startsWith("/") ? path : `/${path}`}`;
  const response = await fetch(url, config);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail || body.error : body;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return body;
}

function toast(message, type = "info") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  $("#toasts").append(node);
  setTimeout(() => node.remove(), 4200);
}

function showDialog(title, eyebrow, content, raw = false) {
  $("#dialog-title").textContent = title;
  $("#dialog-eyebrow").textContent = eyebrow;
  const target = $("#dialog-content");
  if (raw) target.innerHTML = content;
  else {
    target.innerHTML = "";
    const pre = document.createElement("pre");
    pre.textContent = typeof content === "string" ? content : JSON.stringify(content, null, 2);
    target.append(pre);
  }
  $("#detail-dialog").showModal();
}

function setSynced() {
  $("#last-sync").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

async function safeLoad(fn, fallback = []) {
  try { return await fn(); }
  catch (error) { toast(error.message, "error"); return fallback; }
}

function navigate(view) {
  const target = document.getElementById(`view-${view}`) ? view : "overview";
  $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${target}`));
  $$(".nav a[data-view]").forEach(node => node.classList.toggle("active", node.dataset.view === target));
  const section = $(`#view-${target}`);
  $("#page-title").textContent = section.dataset.title;
  $("#page-eyebrow").textContent = section.dataset.eyebrow;
  $(".sidebar").classList.remove("open");
  if (location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
  loadView(target);
}

async function refreshCounts() {
  const [ports, projects, containers, approvals] = await Promise.all([
    safeLoad(() => request("/ports")), safeLoad(() => request("/projects")),
    safeLoad(() => request("/containers")), safeLoad(() => request("/approvals")),
  ]);
  state.ports = ports; state.projects = projects; state.containers = containers; state.approvals = approvals;
  const pending = approvals.filter(item => item.status === "pending");
  $("#nav-port-count").textContent = ports.length;
  $("#nav-project-count").textContent = projects.length;
  $("#nav-container-count").textContent = containers.length;
  $("#nav-approval-count").textContent = pending.length;
  $("#metric-ports").textContent = ports.length;
  $("#metric-projects").textContent = projects.length;
  $("#metric-containers").textContent = containers.filter(item => item.state === "running").length;
  $("#metric-approvals").textContent = pending.length;
  $("#metric-port-note").textContent = `${new Set(ports.map(item => item.port)).size} unique host ports`;
  $("#metric-project-note").textContent = projects.length ? "Registry available" : "Register your first project";
  $("#metric-container-note").textContent = `${containers.length} total known`;
  $("#metric-approval-note").textContent = pending.length ? "Needs your decision" : "Queue is clear";
  setSynced();
}

async function loadOverview() {
  await refreshCounts();
  renderOverviewPorts();
  renderOverviewProjects();
  const resources = await safeLoad(() => request("/system/resources"), null);
  renderResources(resources);
}

function renderOverviewPorts() {
  const rows = state.ports.slice(0, 5);
  $("#overview-ports").innerHTML = rows.length ? rows.map(item => `
    <div class="port-line">
      <span class="port-number">:${esc(item.port)}</span>
      <span class="port-owner">${esc(item.container || item.process || "Unknown listener")}</span>
      <span class="port-type">${esc(item.owner_type)} · ${esc(item.protocol)}</span>
    </div>`).join("") : '<div class="empty-inline">No listening ports found.</div>';
}

function renderOverviewProjects() {
  const target = $("#overview-projects");
  target.innerHTML = state.projects.length ? state.projects.slice(0, 4).map(project => `
    <div class="compact-row"><span class="project-symbol">${esc(project.name.slice(0, 2).toUpperCase())}</span>
    <div><strong>${esc(project.name)}</strong><small>${esc(project.path)}</small></div>
    <span class="row-meta">${project.services.length} svc · ${project.ports.length} ports</span></div>`).join("")
    : '<div class="empty-inline">No projects registered yet.</div>';
  $("#quick-project").innerHTML = '<option value="">Select project…</option>' + state.projects.map(
    project => `<option value="${esc(project.id)}">${esc(project.name)}</option>`).join("");
}

function renderResources(resources) {
  if (!resources) { $("#resource-gauges").innerHTML = '<div class="empty-inline">Resource data unavailable.</div>'; return; }
  const disk = resources.disk || {}, memory = resources.memory || {};
  const diskPercent = disk.total ? Math.round((disk.used / disk.total) * 100) : 0;
  const memUsed = (memory.MemTotal || 0) - (memory.MemAvailable || 0);
  const memPercent = memory.MemTotal ? Math.round((memUsed / memory.MemTotal) * 100) : 0;
  $("#resource-gauges").innerHTML = `
    <div><div class="gauge-head"><span>DISK</span><b>${diskPercent}% · ${fmtBytes(disk.free)} free</b></div><div class="gauge"><i style="width:${diskPercent}%"></i></div></div>
    <div><div class="gauge-head"><span>MEMORY</span><b>${memPercent}% · ${fmtBytes(memory.MemAvailable)} free</b></div><div class="gauge green"><i style="width:${memPercent}%"></i></div></div>`;
}

async function loadPorts() {
  const [ports, conflicts] = await Promise.all([
    safeLoad(() => request("/ports")), safeLoad(() => request("/ports/conflicts")),
  ]);
  state.ports = ports;
  renderPorts();
  const summary = $("#conflict-summary");
  summary.className = `big-status ${conflicts.length ? "bad" : "good"}`;
  summary.innerHTML = conflicts.length
    ? `<strong>${conflicts.length} conflict${conflicts.length === 1 ? "" : "s"}</strong> detected across registered claims and runtime owners.`
    : "✓ No registered project conflicts detected.";
  $("#nav-port-count").textContent = ports.length;
  setSynced();
}

function renderPorts() {
  const filter = $("#port-search").value.trim().toLowerCase();
  const items = state.ports.filter(item => JSON.stringify(item).toLowerCase().includes(filter));
  $("#ports-table").innerHTML = items.length ? items.map(item => `
    <tr><td><span class="cell-main mono">:${esc(item.port)}</span><span class="cell-sub">${esc(item.host || "*")}</span></td>
    <td class="mono">${esc(item.protocol.toUpperCase())}</td>
    <td><span class="cell-main">${esc(item.container || item.process || "Unknown")}</span><span class="cell-sub">${item.pid ? `PID ${esc(item.pid)}` : esc(shortId(item.container_id))}</span></td>
    <td><span class="cell-main">${esc(item.project || "—")}</span><span class="cell-sub">${esc(item.service || "unassigned")}</span></td>
    <td class="muted">${esc(item.source ? item.source.split("/").pop() : "runtime")}</td><td>${badge(item.state)}</td><td><div class="table-actions"><button class="mini-button" data-inspect-type="port" data-inspect-id="${esc(`${item.protocol}:${item.port}`)}">Inspect</button>${item.protocol === "tcp" ? `<button class="mini-button" data-preview-port="${esc(item.port)}">Preview</button>` : ""}</div></td></tr>`).join("")
    : '<tr><td colspan="7"><div class="empty-state">No ports match this filter.</div></td></tr>';
}

async function findFreePorts() {
  const start = $("#range-start").value, end = $("#range-end").value, count = $("#range-count").value;
  const ports = await request(`/ports/free?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&count=${encodeURIComponent(count)}`);
  $("#free-results").innerHTML = ports.length ? ports.map(port => `<button class="port-pill" data-copy="${port}" title="Copy port">:${port}</button>`).join("") : '<span class="muted">No free ports in range.</span>';
}

async function loadProjects() {
  state.projects = await safeLoad(() => request("/projects"));
  $("#nav-project-count").textContent = state.projects.length;
  renderProjects(); setSynced();
}

function renderProjects() {
  $("#projects-grid").innerHTML = state.projects.length ? state.projects.map(project => `
    <article class="project-card">
      <div class="project-card-head"><span class="project-symbol">${esc(project.name.slice(0, 2).toUpperCase())}</span><div><h3>${esc(project.name)}</h3><div class="path" title="${esc(project.path)}">${esc(project.path)}</div></div></div>
      <div class="project-facts"><div><strong>${project.services.length}</strong><small>SERVICES</small></div><div><strong>${project.ports.length}</strong><small>PORTS</small></div><div><strong>${project.compose_files.length}</strong><small>COMPOSE</small></div></div>
      <div class="project-card-actions"><button class="button secondary" data-project-action="inspect" data-id="${esc(project.id)}">Inspect</button><button class="button primary" data-project-action="prepare" data-id="${esc(project.id)}">Prepare</button><button class="button secondary" data-project-action="more" data-id="${esc(project.id)}">•••</button></div>
    </article>`).join("") : '<div class="empty-state">No projects registered. Add an explicit path or scan your configured roots.</div>';
}

async function inspectProject(id) {
  const project = await request(`/projects/${encodeURIComponent(id)}`);
  const [diagnosis, environment, targets] = await Promise.all([
    safeLoad(() => request(`/projects/${encodeURIComponent(id)}/status`), {}),
    safeLoad(() => request(`/projects/${encodeURIComponent(id)}/environment`), {}),
    project.has_makefile ? safeLoad(() => request(`/projects/${encodeURIComponent(id)}/make/targets`), []) : [],
  ]);
  const html = `<div class="compact-list">
    <div class="compact-row"><strong>Path</strong><span class="row-meta">${esc(project.path)}</span></div>
    <div class="compact-row"><strong>Status</strong><span class="row-meta">${badge(diagnosis.status)}</span></div>
    <div class="compact-row"><strong>Services</strong><span class="row-meta">${esc(project.services.join(", ") || "None")}</span></div>
    <div class="compact-row"><strong>Ports</strong><span class="row-meta">${esc(project.ports.map(p => `${p.service}:${p.host_port}`).join(", ") || "None")}</span></div>
  </div><p class="eyebrow" style="margin-top:22px">REDACTED ENVIRONMENT</p><pre>${esc(JSON.stringify(environment, null, 2))}</pre>
  <p class="eyebrow" style="margin-top:22px">MAKE TARGETS</p><pre>${esc(JSON.stringify(targets, null, 2))}</pre>`;
  showDialog(project.name, "PROJECT INSPECTION", html, true);
}

async function prepareProject(id) {
  const result = await request(`/projects/${encodeURIComponent(id)}/prepare`, { method: "POST", body: JSON.stringify({ resolve_port_conflicts: true, start: true, verify: true }) });
  handleOperation(result, "Project inspected");
}

async function projectMenu(id) {
  const project = state.projects.find(item => item.id === id);
  const html = `<div class="compact-list">
    <button class="button secondary wide" data-project-lifecycle="start" data-id="${esc(id)}">Start project</button>
    <button class="button secondary wide" data-project-lifecycle="stop" data-id="${esc(id)}">Stop project</button>
    <button class="button secondary wide" data-project-lifecycle="restart" data-id="${esc(id)}">Restart project</button>
    <button class="button danger wide" data-project-lifecycle="remove" data-id="${esc(id)}">Unregister project</button>
  </div>`;
  showDialog(project?.name || "Project actions", "OPERATIONS", html, true);
}

async function loadContainers() {
  state.containers = await safeLoad(() => request("/containers"));
  $("#nav-container-count").textContent = state.containers.length;
  renderContainers(); setSynced();
}

function renderContainers() {
  const filter = $("#container-search").value.trim().toLowerCase();
  const items = state.containers.filter(item => JSON.stringify(item).toLowerCase().includes(filter));
  $("#containers-table").innerHTML = items.length ? items.map(item => `
    <tr data-inspect-type="container" data-inspect-id="${esc(item.id)}"><td><span class="cell-main">${esc(item.name)}</span><span class="cell-sub">${esc(shortId(item.id))}</span></td>
    <td class="mono">${esc(item.image)}</td><td>${badge(item.state)}</td><td>${badge(item.health || "none")}</td>
    <td class="mono">${esc(item.ports.map(p => `${p.host_port}→${p.container_port}`).join(", ") || "—")}</td>
    <td><span class="cell-main">${esc(item.compose_project || "—")}</span><span class="cell-sub">${esc(item.compose_service || "standalone")}</span></td>
    <td><div class="table-actions"><button class="mini-button" data-observe-container="${esc(item.id)}">Logs</button>${item.ports?.length ? `<button class="mini-button" data-preview-port="${esc(item.ports[0].host_port)}">Preview</button>` : ""}<button class="mini-button" data-container-action="restart" data-id="${esc(item.id)}">Restart</button><button class="mini-button" data-container-action="more" data-id="${esc(item.id)}">•••</button></div></td></tr>`).join("")
    : '<tr><td colspan="7"><div class="empty-state">No containers match this filter.</div></td></tr>';
}

async function containerAction(id, action) {
  if (action === "logs") {
    const result = await request(`/containers/${encodeURIComponent(id)}/logs?tail=200`);
    const item = state.containers.find(c => c.id === id);
    showDialog(item?.name || shortId(id), "LAST 200 LOG LINES", result.logs || "No logs"); return;
  }
  if (action === "stats") {
    const result = await request(`/containers/${encodeURIComponent(id)}/stats`);
    showDialog("Container stats", "RUNTIME METRICS", result); return;
  }
  if (action === "more") {
    const item = state.containers.find(c => c.id === id);
    const html = `<div class="compact-list"><button class="button secondary wide" data-container-action="stats" data-id="${esc(id)}">Inspect stats</button><button class="button secondary wide" data-container-action="start" data-id="${esc(id)}">Start</button><button class="button secondary wide" data-container-action="stop" data-id="${esc(id)}">Stop</button><button class="button secondary wide" data-container-action="restart" data-id="${esc(id)}">Restart</button></div>`;
    showDialog(item?.name || "Container actions", "OPERATIONS", html, true); return;
  }
  const result = await request(`/containers/${encodeURIComponent(id)}/${action}`, { method: "POST" });
  handleOperation(result, `Container ${action} proposed`);
}

async function loadDocker(tab = state.dockerTab) {
  state.dockerTab = tab;
  $$("[data-docker-tab]").forEach(node => node.classList.toggle("active", node.dataset.dockerTab === tab));
  const target = $("#docker-content"); target.innerHTML = '<div class="skeleton block"></div>';
  try {
    if (tab === "disk") {
      const data = await request("/docker/disk-usage");
      target.innerHTML = `<div class="docker-stat-grid">${["images", "containers", "volumes", "build_cache"].map(key => `<article class="docker-stat"><small>${esc(key.replace("_", " "))}</small><strong>${esc(data[key]?.count ?? 0)}</strong><p class="muted">Tracked by Docker</p></article>`).join("")}</div>`;
    } else {
      const data = await request(`/${tab}`);
      renderDockerList(tab, data);
    }
    setSynced();
  } catch (error) { target.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`; toast(error.message, "error"); }
}

function renderDockerList(tab, data) {
  const target = $("#docker-content");
  if (!data.length) { target.innerHTML = `<div class="panel empty-state">No ${esc(tab)} found.</div>`; return; }
  const columns = {
    images: ["Identifier", "Tags", "Size", "Used", ""],
    volumes: ["Name", "Driver", "Mountpoint", "Size", "Users", ""],
    networks: ["Name", "Driver", "Scope", "Members", ""],
  }[tab];
  const rows = data.map(item => {
    if (tab === "images") return `<tr><td class="mono">${esc(shortId(item.id))}</td><td>${esc(item.tags?.join(", ") || "untagged")}</td><td>${fmtBytes(item.size)}</td><td>${badge(item.used ? "used" : "unused")}</td><td><button class="mini-button" data-inspect-type="image" data-inspect-id="${esc(item.id)}">Inspect</button>${item.used ? "" : `<button class="mini-button" data-docker-remove="images" data-id="${esc(item.id)}">Remove</button>`}</td></tr>`;
    if (tab === "volumes") {
      const users = item.users?.map(user => typeof user === "string" ? user : `${user.name} → ${user.destination || "?"}`).join(", ");
      return `<tr><td class="mono">${esc(item.name)}</td><td>${esc(item.driver)}</td><td class="muted">${esc(item.mountpoint)}</td><td>${fmtBytes(item.size)}</td><td>${esc(users || "None")}</td><td><button class="mini-button" data-inspect-type="volume" data-inspect-id="${esc(item.name)}">Inspect</button>${item.users?.length ? "" : `<button class="mini-button" data-docker-remove="volumes" data-id="${esc(item.name)}">Remove</button>`}</td></tr>`;
    }
    const members = item.members?.map(member => typeof member === "string" ? member : member.name).join(", ");
    return `<tr><td>${esc(item.name)}</td><td>${esc(item.driver)}</td><td>${esc(item.scope)}</td><td>${esc(members || "None")}</td><td><button class="mini-button" data-inspect-type="network" data-inspect-id="${esc(item.id || item.name)}">Inspect</button></td></tr>`;
  }).join("");
  target.innerHTML = `<article class="panel table-panel"><div class="table-wrap"><table><thead><tr>${columns.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div></article>`;
}

async function loadApprovals() {
  state.approvals = await safeLoad(() => request("/approvals"));
  const pending = state.approvals.filter(item => item.status === "pending");
  $("#nav-approval-count").textContent = pending.length;
  $("#approval-list").innerHTML = state.approvals.length ? state.approvals.map(item => `
    <article class="approval-card"><div class="risk-block">${badge(item.risk)}</div><div><h3>${esc(item.summary)}</h3><p>${esc(item.action)} · expires ${esc(new Date(item.expires_at).toLocaleString())}</p></div><div class="approval-actions">${item.status === "pending" ? `<button class="button secondary" data-approval-action="reject" data-id="${esc(item.id)}">Reject</button><button class="button primary" data-approval-action="approve" data-id="${esc(item.id)}">Approve & execute</button>` : badge(item.status)}</div></article>`).join("")
    : '<div class="empty-state">No approval requests yet.</div>';
  setSynced();
}

async function approvalAction(id, action) {
  if (action === "approve" && !confirm("Execute exactly this stored action and its approved arguments?")) return;
  const result = await request(`/approvals/${encodeURIComponent(id)}/${action}`, { method: "POST" });
  toast(action === "approve" ? `Action ${result.status}` : "Approval rejected", result.status === "failed" ? "error" : "success");
  if (result.status === "failed" || result.status === "verification_failed") showDialog("Action result", "VERIFICATION", result);
  await loadApprovals();
}

async function loadHistory() {
  state.actions = await safeLoad(() => request("/actions")); renderHistory(); setSynced();
}

function renderHistory() {
  const items = state.historyFilter === "all" ? state.actions : state.actions.filter(item => item.status === state.historyFilter);
  $("#history-table").innerHTML = items.length ? items.map(item => `
    <tr data-show-action="${esc(item.id)}"><td><span class="cell-main">${esc(item.action)}</span><span class="cell-sub">${esc(shortId(item.id))}</span></td><td>${badge(item.risk)}</td><td>${badge(item.status)}</td><td>${badge(item.verification?.verified ? "completed" : "unverified")}</td><td class="mono">${esc(shortId(item.request_id))}</td></tr>`).join("")
    : '<tr><td colspan="5"><div class="empty-state">No matching actions.</div></td></tr>';
}

function handleOperation(result, message) {
  if (result.status === "approval_required") {
    toast(`${message}. Approval required.`, "info");
    refreshCounts();
    showDialog("Approval required", result.approval.risk, result);
  } else {
    toast(message, result.status === "failed" ? "error" : "success");
    showDialog("Operation result", "VERIFICATION", result);
  }
}

async function askAgent(message) {
  $("#agent-intro").style.display = "none";
  const conversation = $("#conversation");
  conversation.insertAdjacentHTML("beforeend", `<div class="message user">${esc(message)}</div><div class="message agent" id="agent-thinking"><span class="spinner"></span> Inspecting real state…</div>`);
  conversation.scrollTop = conversation.scrollHeight;
  try {
    const result = await request("/agent/query", { method: "POST", body: JSON.stringify({ message }) });
    $("#agent-thinking")?.remove();
    const observations = result.observations?.length ? `<pre>${esc(JSON.stringify(result.observations, null, 2))}</pre>` : "";
    conversation.insertAdjacentHTML("beforeend", `<div class="message agent">${esc(result.message)}${observations}</div>`);
    if (result.approval_required) { toast("The agent created an approval request."); refreshCounts(); }
  } catch (error) {
    $("#agent-thinking")?.remove();
    conversation.insertAdjacentHTML("beforeend", `<div class="message agent">Could not complete the request: ${esc(error.message)}</div>`);
  }
  conversation.scrollTop = conversation.scrollHeight;
}

async function loadView(view) {
  const loaders = { overview: loadOverview, ports: loadPorts, projects: loadProjects, containers: loadContainers, docker: loadDocker, approvals: loadApprovals, history: loadHistory };
  if (loaders[view]) await loaders[view]();
  document.dispatchEvent(new CustomEvent("controlplane:view", { detail: { view } }));
}

document.addEventListener("click", async event => {
  const target = event.target.closest("button, a, [data-show-action]");
  if (!target) return;
  try {
    if (target.dataset.go) navigate(target.dataset.go);
    if (target.hasAttribute("data-open-agent")) navigate("agent");
    if (target.hasAttribute("data-close-dialog")) $("#detail-dialog").close();
    if (target.dataset.refresh) await loadView(target.dataset.refresh);
    if (target.id === "refresh-all") await loadView(location.hash.slice(1) || "overview");
    if (target.id === "mobile-menu") $(".sidebar").classList.toggle("open");
    if (target.id === "run-free-search" || target.id === "find-free-button") await findFreePorts();
    if (target.id === "scan-projects") { await request("/projects/scan", { method: "POST" }); toast("Configured roots scanned", "success"); await loadProjects(); }
    if (target.id === "quick-prepare") { const id = $("#quick-project").value; if (!id) throw new Error("Select a project first"); await prepareProject(id); }
    if (target.dataset.projectAction === "inspect") await inspectProject(target.dataset.id);
    if (target.dataset.projectAction === "prepare") await prepareProject(target.dataset.id);
    if (target.dataset.projectAction === "more") await projectMenu(target.dataset.id);
    if (target.dataset.projectLifecycle) {
      const action = target.dataset.projectLifecycle, id = target.dataset.id;
      if (action === "remove") { if (confirm("Unregister this project? No project files will be deleted.")) { await request(`/projects/${encodeURIComponent(id)}`, { method: "DELETE" }); $("#detail-dialog").close(); await loadProjects(); toast("Project unregistered", "success"); } }
      else { const result = await request(`/projects/${encodeURIComponent(id)}/${action}`, { method: "POST" }); $("#detail-dialog").close(); handleOperation(result, `Project ${action} proposed`); }
    }
    if (target.dataset.containerAction) await containerAction(target.dataset.id, target.dataset.containerAction);
    if (target.dataset.dockerTab) await loadDocker(target.dataset.dockerTab);
    if (target.dataset.dockerRemove) { if (confirm(`Propose removal of this ${target.dataset.dockerRemove.slice(0, -1)}?`)) { const result = await request(`/${target.dataset.dockerRemove}/${encodeURIComponent(target.dataset.id)}`, { method: "DELETE" }); handleOperation(result, "Removal proposed"); } }
    if (target.dataset.networkInspect) showDialog("Network details", "DOCKER NETWORK", await request(`/networks/${encodeURIComponent(target.dataset.networkInspect)}`));
    if (target.dataset.approvalAction) await approvalAction(target.dataset.id, target.dataset.approvalAction);
    if (target.dataset.historyFilter) { state.historyFilter = target.dataset.historyFilter; $$("[data-history-filter]").forEach(node => node.classList.toggle("active", node === target)); renderHistory(); }
    if (target.dataset.showAction) { const item = state.actions.find(action => action.id === target.dataset.showAction); showDialog(item.action, "ACTION RECORD", item); }
    if (target.dataset.copy) { await navigator.clipboard.writeText(target.dataset.copy); toast(`Copied port ${target.dataset.copy}`, "success"); }
    if (target.classList.contains("suggestion")) { navigate("agent"); $("#agent-input").value = target.textContent.trim(); $("#agent-input").focus(); }
  } catch (error) { toast(error.message, "error"); }
});

$("#register-form").addEventListener("submit", async event => {
  event.preventDefault();
  try { await request("/projects", { method: "POST", body: JSON.stringify({ path: $("#project-path").value.trim() }) }); $("#project-path").value = ""; toast("Project registered", "success"); await loadProjects(); }
  catch (error) { toast(error.message, "error"); }
});

$("#agent-form").addEventListener("submit", async event => {
  event.preventDefault(); const input = $("#agent-input"), message = input.value.trim();
  if (!message) return; input.value = ""; await askAgent(message);
});
$("#port-search").addEventListener("input", renderPorts);
$("#container-search").addEventListener("input", renderContainers);
window.addEventListener("hashchange", () => navigate(location.hash.slice(1)));

async function boot() {
  try {
    const health = await request("/health");
    $("#daemon-label").textContent = "Agent online";
    $("#daemon-detail").textContent = `v${health.version} · 127.0.0.1`;
  } catch (error) {
    $(".pulse").classList.add("offline"); $("#daemon-label").textContent = "Agent unavailable";
    $("#daemon-detail").textContent = error.message;
  }
  if ((location.hash.slice(1) || "overview") !== "overview") await refreshCounts();
  navigate(location.hash.slice(1) || "overview");
}

boot();

window.controlPlane = {
  $, $$, API, state, esc, fmtBytes, badge, icon, request, toast, showDialog, setSynced,
  navigate, loadView, refreshCounts, handleOperation,
};
