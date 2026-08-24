(() => {
  const cp = window.controlPlane;
  if (!cp) return;

  const state = {
    topology: null,
    topologyScale: 1,
    topologyOffset: { x: 0, y: 0 },
    topologyTypes: new Set(),
    topologyDragging: null,
    workspaces: [],
    processes: [],
    activity: [],
    files: [],
    editor: { projectId: "", path: "", hash: "", original: "" },
    eventSource: null,
    refreshTimer: null,
    lastLiveRefresh: 0,
  };

  const $ = cp.$;
  const $$ = cp.$$;
  const esc = cp.esc;
  const colors = {
    project: "#47e6df", compose_project: "#a798ff", compose_service: "#9faeff",
    container: "#65e59a", image: "#82c8ff", volume: "#f4ba62", network: "#f58cd4",
    port: "#47e6df", process: "#ffad75", dockerfile: "#95d8ff", compose_file: "#b8c7d9",
    makefile: "#f6d968", make_target: "#e4bd75", env_file: "#9dd7a6", runtime: "#aeb8c5",
  };

  const safe = async (task, fallback = null) => {
    try { return await task(); }
    catch (error) { cp.toast(error.message, "error"); return fallback; }
  };
  const resourceButton = resource => `<button class="resource-link" data-inspect-type="${esc(resource.resource_type)}" data-inspect-id="${esc(resource.resource_id)}"><span class="resource-dot" style="--dot:${colors[resource.resource_type] || "#8fa0b2"}"></span>${esc(resource.label)}<small>${esc(resource.resource_type)}</small></button>`;
  const formatTime = value => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "now";

  async function loadControlView(view) {
    const loaders = {
      workspaces: loadWorkspaces,
      topology: loadTopology,
      processes: loadProcesses,
      files: loadFilesView,
      activity: loadActivity,
      settings: loadSettings,
    };
    if (loaders[view]) await loaders[view]();
  }

  async function loadProjects() {
    const projects = await safe(() => cp.request("/projects"), []);
    if (!projects) return [];
    cp.state.projects = projects;
    $("#nav-project-count").textContent = projects.length;
    ["#topology-project", "#file-project"].forEach(selector => {
      const select = $(selector);
      if (!select) return;
      const prior = select.value;
      const first = selector === "#topology-project" ? '<option value="">All observed resources</option>' : '<option value="">Select registered workspace…</option>';
      select.innerHTML = first + projects.map(project => `<option value="${esc(project.id)}">${esc(project.name)}</option>`).join("");
      if (projects.some(project => project.id === prior)) select.value = prior;
    });
    return projects;
  }

  async function loadWorkspaces() {
    const projects = await loadProjects();
    state.workspaces = projects;
    renderWorkspaces();
  }

  function renderWorkspaces() {
    const target = $("#workspaces-grid");
    if (!target) return;
    const filter = $("#workspace-search")?.value.trim().toLowerCase() || "";
    const projects = state.workspaces.filter(project => JSON.stringify(project).toLowerCase().includes(filter));
    target.innerHTML = projects.length ? projects.map(project => `
      <article class="workspace-card">
        <div class="workspace-card-head"><span class="project-symbol">${esc(project.name.slice(0, 2).toUpperCase())}</span><div><p class="eyebrow">REGISTERED WORKSPACE</p><h3>${esc(project.name)}</h3><p>${esc(project.path)}</p></div></div>
        <div class="workspace-facts"><span><b>${project.services.length}</b> services</span><span><b>${project.ports.length}</b> declared ports</span><span><b>${project.dockerfiles?.length || 0}</b> Dockerfiles</span></div>
        <div class="workspace-card-actions"><button class="button primary" data-open-workspace="${esc(project.id)}">Open workspace</button><button class="button secondary" data-focus-topology="${esc(project.id)}">Topology</button><button class="button secondary" data-focus-files="${esc(project.id)}">Files</button></div>
      </article>`).join("") : '<div class="empty-state">No registered workspaces. Use the project registry or scan your configured roots.</div>';
  }

  async function openWorkspace(identifier) {
    const [workspace, files] = await Promise.all([
      cp.request(`/projects/${encodeURIComponent(identifier)}/workspace`),
      cp.request(`/projects/${encodeURIComponent(identifier)}/files`),
    ]);
    const graph = workspace.topology;
    const nodes = graph.nodes || [];
    const edges = graph.edges || [];
    const containersByService = new Map();
    edges.filter(edge => edge.relationship === "RUNS").forEach(edge => {
      const list = containersByService.get(edge.source) || [];
      list.push(edge.target); containersByService.set(edge.source, list);
    });
    const byId = new Map(nodes.map(node => [node.id, node]));
    const services = nodes.filter(node => node.resource_type === "compose_service");
    const processes = nodes.filter(node => node.resource_type === "process");
    const targets = nodes.filter(node => node.resource_type === "make_target");
    const detail = $("#workspace-detail");
    detail.classList.remove("hidden");
    detail.innerHTML = `
      <header class="workspace-detail-head"><div><p class="eyebrow">${esc(workspace.status.replaceAll("_", " "))}</p><h2>${esc(workspace.project.name)}</h2><p>${esc(workspace.project.path)}</p></div><div class="workspace-summary"><span>${workspace.summary.containers} containers</span><span>${workspace.summary.processes} host processes</span><span>${workspace.summary.ports} ports</span></div></header>
      <div class="workspace-detail-grid">
        <article class="panel"><p class="eyebrow">SERVICES</p><h3>Compose and runtime state</h3><div class="workspace-list">${services.length ? services.map(service => {
          const containers = (containersByService.get(service.id) || []).map(id => byId.get(id)).filter(Boolean);
          return `<button class="workspace-row" data-inspect-type="compose_service" data-inspect-id="${esc(service.resource_id)}"><span><b>${esc(service.label)}</b><small>${esc(containers.map(item => item.label).join(", ") || "declared; not running")}</small></span>${cp.badge(containers[0]?.status || "declared")}</button>`;
        }).join("") : '<div class="empty-inline">No Compose services detected.</div>'}</div></article>
        <article class="panel"><p class="eyebrow">FILES</p><h3>Configuration surface</h3><div class="workspace-list">${files.length ? files.map(file => `<button class="workspace-row" data-open-file="${esc(file.path)}" data-file-project="${esc(workspace.project.id)}"><span><b>${esc(file.path)}</b><small>${esc(file.kind)} · ${file.size} B</small></span><span>→</span></button>`).join("") : '<div class="empty-inline">No supported config files found.</div>'}</div></article>
        <article class="panel"><p class="eyebrow">LOCAL PROCESSES</p><h3>Outside Docker</h3><div class="workspace-list">${processes.length ? processes.map(resourceButton).join("") : '<div class="empty-inline">No project-correlated host processes observed.</div>'}</div></article>
        <article class="panel"><p class="eyebrow">MAKE TARGETS</p><h3>Operational commands</h3><div class="workspace-list">${targets.length ? targets.map(target => `<button class="workspace-row" data-inspect-type="make_target" data-inspect-id="${esc(target.resource_id)}"><span><b>${esc(target.label)}</b><small>${esc((target.attributes.tools || []).join(", ") || "Make target")}</small></span>${cp.badge(target.attributes.risk || target.status)}</button>`).join("") : '<div class="empty-inline">No Makefile targets detected.</div>'}</div></article>
      </div>`;
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function loadTopology() {
    await loadProjects();
    const selector = $("#topology-project");
    if (!state.topologyInitialized && !selector.value && cp.state.projects.length) selector.value = cp.state.projects[0].id;
    state.topologyInitialized = true;
    const project = selector.value;
    const path = project ? `/topology/project/${encodeURIComponent(project)}` : "/topology";
    const graph = await safe(() => cp.request(path), { nodes: [], edges: [], warnings: [] });
    state.topology = graph;
    state.topologyScale = 1;
    state.topologyOffset = { x: 0, y: 0 };
    state.topologyTypes = new Set(graph.nodes.map(node => node.resource_type));
    renderTopology();
  }

  function renderTopology() {
    const graph = state.topology;
    if (!graph) return;
    const query = $("#topology-search").value.trim().toLowerCase();
    const activeTypes = state.topologyTypes;
    let nodes = graph.nodes.filter(node => activeTypes.has(node.resource_type));
    if (query) nodes = nodes.filter(node => `${node.label} ${JSON.stringify(node.attributes)}`.toLowerCase().includes(query));
    if (nodes.length > 110 && !query) nodes = nodes.slice(0, 110);
    const selected = new Set(nodes.map(node => node.id));
    const edges = graph.edges.filter(edge => selected.has(edge.source) && selected.has(edge.target));
    renderTopologyLegend(graph.nodes);
    drawTopology(nodes, edges);
    const warnings = (graph.warnings || []).slice(0, 6);
    $("#topology-summary").innerHTML = `
      <p class="eyebrow">LIVE GRAPH</p><h3>${nodes.length} resources · ${edges.length} relationships</h3>
      <p class="muted">Click any node to inspect it. Drag the canvas to pan, use the controls to zoom, and scope the graph to a workspace when it becomes dense.</p>
      <div class="topology-warnings">${warnings.length ? warnings.map(warning => `<div class="warning-row"><span>!</span><div><b>${esc(warning.severity || "notice")}</b><p>${esc(warning.message)}</p></div></div>`).join("") : '<div class="empty-inline">No topology warnings in this scope.</div>'}</div>`;
  }

  function renderTopologyLegend(nodes) {
    const counts = nodes.reduce((all, node) => ({ ...all, [node.resource_type]: (all[node.resource_type] || 0) + 1 }), {});
    $("#topology-legend").innerHTML = Object.entries(counts).sort().map(([type, count]) => `<button class="topology-filter ${state.topologyTypes.has(type) ? "active" : ""}" data-topology-type="${esc(type)}"><i style="background:${colors[type] || "#8fa0b2"}"></i>${esc(type.replaceAll("_", " "))}<b>${count}</b></button>`).join("");
  }

  function drawTopology(nodes, edges) {
    const svg = $("#topology-graph");
    const byType = new Map();
    nodes.forEach(node => { const list = byType.get(node.resource_type) || []; list.push(node); byType.set(node.resource_type, list); });
    const types = [...byType.keys()].sort();
    const columnWidth = 210;
    const maxRows = Math.max(1, ...[...byType.values()].map(list => list.length));
    const width = Math.max(1200, types.length * columnWidth + 120);
    const height = Math.max(620, maxRows * 92 + 130);
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = "";
    const transform = document.createElementNS("http://www.w3.org/2000/svg", "g");
    transform.setAttribute("id", "topology-transform");
    transform.setAttribute("transform", topologyTransform());
    svg.append(transform);
    const positions = new Map();
    types.forEach((type, typeIndex) => {
      const items = byType.get(type);
      const x = 120 + typeIndex * columnWidth;
      const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
      title.setAttribute("x", String(x)); title.setAttribute("y", "42"); title.setAttribute("class", "graph-group-title"); title.textContent = type.replaceAll("_", " "); transform.append(title);
      items.forEach((node, index) => positions.set(node.id, { x, y: 88 + index * 92 }));
    });
    edges.forEach(edge => {
      const source = positions.get(edge.source), target = positions.get(edge.target);
      if (!source || !target) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const bend = (target.x - source.x) * 0.45;
      line.setAttribute("d", `M ${source.x + 67} ${source.y} C ${source.x + 67 + bend} ${source.y}, ${target.x - 67 - bend} ${target.y}, ${target.x - 67} ${target.y}`);
      line.setAttribute("class", "graph-edge"); line.dataset.relationship = edge.relationship; transform.append(line);
    });
    nodes.forEach(node => {
      const point = positions.get(node.id);
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.setAttribute("class", "graph-node"); group.setAttribute("transform", `translate(${point.x - 67}, ${point.y - 24})`);
      group.dataset.resourceType = node.resource_type; group.dataset.resourceId = node.resource_id;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("width", "134"); rect.setAttribute("height", "48"); rect.setAttribute("rx", "8"); rect.setAttribute("fill", "#111923"); rect.setAttribute("stroke", colors[node.resource_type] || "#8fa0b2"); group.append(rect);
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle"); dot.setAttribute("cx", "14"); dot.setAttribute("cy", "17"); dot.setAttribute("r", "4"); dot.setAttribute("fill", colors[node.resource_type] || "#8fa0b2"); group.append(dot);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", "24"); label.setAttribute("y", "20"); label.setAttribute("class", "graph-label"); label.textContent = shorten(node.label, 16); group.append(label);
      const sub = document.createElementNS("http://www.w3.org/2000/svg", "text"); sub.setAttribute("x", "12"); sub.setAttribute("y", "37"); sub.setAttribute("class", "graph-sub"); sub.textContent = shorten(node.status || node.resource_type.replaceAll("_", " "), 19); group.append(sub);
      transform.append(group);
    });
    attachGraphPan(svg);
  }

  const shorten = (value, length) => String(value || "").length > length ? `${String(value).slice(0, length - 1)}…` : String(value || "");
  const topologyTransform = () => `translate(${state.topologyOffset.x} ${state.topologyOffset.y}) scale(${state.topologyScale})`;
  function updateTopologyTransform() { $("#topology-transform")?.setAttribute("transform", topologyTransform()); }
  function zoomTopology(direction) {
    state.topologyScale = direction === "in" ? Math.min(2.2, state.topologyScale + .16) : direction === "out" ? Math.max(.45, state.topologyScale - .16) : 1;
    if (direction === "reset") state.topologyOffset = { x: 0, y: 0 };
    updateTopologyTransform();
  }
  function attachGraphPan(svg) {
    svg.onpointerdown = event => { if (event.target.closest(".graph-node")) return; state.topologyDragging = { x: event.clientX, y: event.clientY, offset: { ...state.topologyOffset } }; svg.setPointerCapture(event.pointerId); };
    svg.onpointermove = event => { if (!state.topologyDragging) return; state.topologyOffset = { x: state.topologyDragging.offset.x + (event.clientX - state.topologyDragging.x), y: state.topologyDragging.offset.y + (event.clientY - state.topologyDragging.y) }; updateTopologyTransform(); };
    svg.onpointerup = () => { state.topologyDragging = null; };
  }

  async function openResource(type, id) {
    const detail = await safe(() => cp.request(`/resources/${encodeURIComponent(type)}/${encodeURIComponent(id)}`));
    if (!detail) return;
    $("#inspector-type").textContent = detail.node.resource_type.replaceAll("_", " ").toUpperCase();
    $("#inspector-title").textContent = detail.node.label;
    const attributes = Object.entries(detail.node.attributes || {}).filter(([key]) => !["content", "command"].includes(key));
    $("#inspector-content").innerHTML = `
      <div class="inspector-status">${cp.badge(detail.node.status || "observed")}</div>
      <dl class="attribute-list">${attributes.slice(0, 14).map(([key, value]) => `<div><dt>${esc(key.replaceAll("_", " "))}</dt><dd>${esc(formatAttribute(value))}</dd></div>`).join("") || '<div class="empty-inline">No additional attributes.</div>'}</dl>
      ${resourceActions(detail.node)}
      <p class="eyebrow">CONNECTED RESOURCES</p><div class="inspector-related">${detail.related.length ? detail.related.map(resourceButton).join("") : '<div class="empty-inline">No direct relationships.</div>'}</div>
      <p class="eyebrow">RELATIONSHIPS</p><div class="relationship-list">${detail.relationships.map(edge => `<span>${esc(edge.relationship)}</span>`).join("") || '<span>None</span>'}</div>`;
    const panel = $("#resource-inspector"); panel.classList.add("open"); panel.setAttribute("aria-hidden", "false");
  }
  function resourceActions(node) {
    if (node.resource_type === "container") return `<p class="eyebrow">ACTIONS</p><div class="inspector-actions"><button class="button secondary" data-resource-action="logs" data-resource-type="container" data-resource-id="${esc(node.resource_id)}">Open logs</button><button class="button secondary" data-resource-action="restart" data-resource-type="container" data-resource-id="${esc(node.resource_id)}">Restart</button><button class="button secondary" data-resource-action="stop" data-resource-type="container" data-resource-id="${esc(node.resource_id)}">Stop</button></div>`;
    if (node.resource_type === "project" && node.attributes.registered) return `<p class="eyebrow">ACTIONS</p><div class="inspector-actions"><button class="button secondary" data-resource-action="workspace" data-resource-type="project" data-resource-id="${esc(node.resource_id)}">Open workspace</button><button class="button primary" data-resource-action="prepare" data-resource-type="project" data-resource-id="${esc(node.resource_id)}">Prepare</button></div>`;
    if (node.resource_type === "compose_service" && node.attributes.project_id) return `<p class="eyebrow">ACTIONS</p><div class="inspector-actions"><button class="button secondary" data-resource-action="restart-service" data-resource-type="compose_service" data-resource-id="${esc(node.resource_id)}" data-project-id="${esc(node.attributes.project_id)}">Restart service</button></div>`;
    return "";
  }
  async function performResourceAction(action, type, id, projectId) {
    if (type === "container" && action === "logs") {
      const logs = await cp.request(`/containers/${encodeURIComponent(id)}/logs?tail=200`);
      cp.showDialog("Container logs", "LAST 200 LINES", logs.logs || "No logs available");
      return;
    }
    if (type === "container") {
      const result = await cp.request(`/containers/${encodeURIComponent(id)}/${action}`, { method: "POST" });
      cp.handleOperation(result, `Container ${action} proposed`);
      return;
    }
    if (type === "project" && action === "workspace") { closeInspector(); cp.navigate("workspaces"); await openWorkspace(id); return; }
    if (type === "project" && action === "prepare") {
      const result = await cp.request(`/projects/${encodeURIComponent(id)}/prepare`, { method: "POST", body: JSON.stringify({ resolve_port_conflicts: true, start: true, verify: true }) });
      cp.handleOperation(result, "Workspace preparation proposed");
      return;
    }
    if (type === "compose_service" && action === "restart-service") {
      const service = state.topology?.nodes.find(node => node.resource_id === id)?.label;
      if (!service) throw new Error("Could not resolve Compose service name");
      const result = await cp.request(`/compose/projects/${encodeURIComponent(projectId)}/services/${encodeURIComponent(service)}/restart`, { method: "POST" });
      cp.handleOperation(result, "Service restart proposed");
    }
  }
  function formatAttribute(value) {
    if (value === null || value === undefined) return "—";
    if (Array.isArray(value)) return value.map(item => typeof item === "object" ? item.name || item.path || JSON.stringify(item) : item).join(", ");
    return typeof value === "object" ? JSON.stringify(value) : value;
  }
  function closeInspector() { const panel = $("#resource-inspector"); panel.classList.remove("open"); panel.setAttribute("aria-hidden", "true"); }

  async function loadProcesses() {
    state.processes = await safe(() => cp.request("/processes"), []);
    renderProcesses();
  }
  function renderProcesses() {
    const filter = $("#process-search").value.trim().toLowerCase();
    const items = state.processes.filter(item => JSON.stringify(item).toLowerCase().includes(filter));
    $("#processes-table").innerHTML = items.length ? items.map(item => `<tr data-inspect-type="process" data-inspect-id="${esc(item.pid)}"><td><span class="cell-main">${esc(item.process || "unknown")}</span><span class="cell-sub mono">${esc(shorten(item.command || "", 90))}</span></td><td class="mono">${esc(item.pid)}<span class="cell-sub">parent ${esc(item.ppid || "—")}</span></td><td>${cp.badge(item.kind)}</td><td class="mono">${esc(item.ports?.map(port => `:${port}`).join(", ") || "—")}</td><td><span class="cell-main">${esc(item.project_path || "—")}</span><span class="cell-sub">${esc(item.cwd || "")}</span></td><td>${item.cpu_seconds === undefined || item.cpu_seconds === null ? "—" : `${esc(item.cpu_seconds)} s`}</td><td>${cp.fmtBytes(item.memory_bytes)}</td></tr>`).join("") : '<tr><td colspan="7"><div class="empty-state">No matching observed processes.</div></td></tr>';
  }

  async function loadFilesView() {
    await loadProjects();
    if (state.editor.projectId && $("#file-project").value === state.editor.projectId) await loadFiles(state.editor.projectId);
  }
  async function loadFiles(projectId) {
    if (!projectId) { state.files = []; renderFiles(); return; }
    state.editor.projectId = projectId;
    $("#file-project").value = projectId;
    state.files = await safe(() => cp.request(`/projects/${encodeURIComponent(projectId)}/files`), []);
    renderFiles();
  }
  function renderFiles() {
    const filter = $("#file-search").value.trim().toLowerCase();
    const items = state.files.filter(file => file.path.toLowerCase().includes(filter));
    $("#file-list").innerHTML = state.editor.projectId ? (items.length ? items.map(file => `<button class="file-row ${file.path === state.editor.path ? "active" : ""}" data-open-file="${esc(file.path)}"><span>${esc(file.path)}</span><small>${esc(file.kind)} · ${file.size} B</small></button>`).join("") : '<div class="empty-inline">No supported editable files match this filter.</div>') : '<div class="empty-inline">Select a workspace to show editable configuration files.</div>';
  }
  async function openFile(path, projectId = state.editor.projectId) {
    if (!projectId) throw new Error("Select a workspace first");
    await loadFiles(projectId);
    const file = await cp.request(`/projects/${encodeURIComponent(projectId)}/files/content?path=${encodeURIComponent(path)}`);
    state.editor = { projectId, path: file.path, hash: file.sha256, original: file.content };
    $("#file-editor").value = file.content; $("#file-editor").disabled = false;
    $("#editor-path").textContent = file.path; $("#editor-kind").textContent = `${file.kind.toUpperCase()} · ${file.sha256.slice(0, 12)}`;
    ["#file-save", "#file-revert", "#file-undo"].forEach(selector => { $(selector).disabled = false; });
    updateEditorGutter(); renderFiles();
  }
  function updateEditorGutter() {
    const lines = Math.max(1, $("#file-editor").value.split("\n").length);
    $("#editor-gutter").textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
  }
  async function saveFile() {
    const editor = state.editor;
    if (!editor.path) throw new Error("Select a file first");
    const content = $("#file-editor").value;
    if (content === editor.original) throw new Error("There are no changes to save");
    const result = await cp.request(`/projects/${encodeURIComponent(editor.projectId)}/files/save`, { method: "POST", body: JSON.stringify({ path: editor.path, content, expected_sha256: editor.hash }) });
    const preview = result.preview;
    cp.showDialog("Review configuration diff", `${preview.validation.parser || "FILE"} · ${preview.validation.valid ? "VALID" : "CHECK"}`, `<div class="diff-summary"><p>${esc(preview.path)}</p><p>${esc(JSON.stringify(preview.validation))}</p></div><pre class="diff-view">${esc(preview.diff || "No textual diff")}</pre><p class="dialog-note">The proposed edit has not been written. Approve the exact stored action from the approval queue to apply it atomically with validation and a backup.</p>`, true);
    if (result.status === "approval_required") { cp.toast("Diff is ready; approval is required before the file changes."); cp.refreshCounts(); }
    else cp.handleOperation(result, "File edit processed");
  }
  async function undoFile() {
    const editor = state.editor;
    if (!editor.path) throw new Error("Select a file first");
    const result = await cp.request(`/projects/${encodeURIComponent(editor.projectId)}/files/undo`, { method: "POST", body: JSON.stringify({ path: editor.path }) });
    cp.handleOperation(result, "File undo proposed");
  }
  function revertFile() { if (!state.editor.path) return; $("#file-editor").value = state.editor.original; updateEditorGutter(); cp.toast("Editor reverted to the opened version."); }
  function findInEditor() {
    const needle = $("#editor-find").value;
    const editor = $("#file-editor");
    if (!needle || editor.disabled) return;
    const index = editor.value.toLowerCase().indexOf(needle.toLowerCase(), editor.selectionEnd);
    if (index < 0) { cp.toast("No further match in this file."); return; }
    editor.focus(); editor.setSelectionRange(index, index + needle.length);
  }

  async function loadActivity() {
    state.activity = await safe(() => cp.request("/activity?limit=100"), []);
    renderActivity();
  }
  function renderActivity() {
    $("#activity-feed").innerHTML = state.activity.length ? [...state.activity].reverse().map(event => `<article class="activity-row"><time>${esc(formatTime(event.created_at))}</time><span class="activity-dot ${esc(event.resource_type)}"></span><div><b>${esc(event.message)}</b><p>${esc(event.type)} · ${esc(event.resource_type)} / ${esc(event.resource_id)}</p></div><button class="mini-button" data-inspect-type="${esc(event.resource_type)}" data-inspect-id="${esc(event.resource_id)}">Inspect</button></article>`).join("") : '<div class="empty-state">Waiting for observed local changes.</div>';
  }
  function appendActivity(event) {
    if (state.activity.some(item => item.id === event.id)) return;
    state.activity.push(event); state.activity = state.activity.slice(-100);
    if (location.hash.slice(1) === "activity") renderActivity();
  }
  function startEvents() {
    if (state.eventSource || !window.EventSource) return;
    const source = new EventSource("/api/v1/events/stream"); state.eventSource = source;
    source.onmessage = event => {
      try { const payload = JSON.parse(event.data); appendActivity(payload); scheduleLiveRefresh(payload); }
      catch (_) { /* ignore malformed non-authoritative stream data */ }
    };
    source.onerror = () => { source.close(); state.eventSource = null; window.setTimeout(startEvents, 4000); };
  }
  function scheduleLiveRefresh(event) {
    if (event.resource_type === "topology") return;
    const now = Date.now();
    if (now - state.lastLiveRefresh < 4000) return;
    state.lastLiveRefresh = now;
    window.clearTimeout(state.refreshTimer);
    state.refreshTimer = window.setTimeout(() => {
      const view = location.hash.slice(1) || "overview";
      if (["overview", "workspaces", "topology", "processes", "containers", "ports"].includes(view)) cp.loadView(view);
    }, 900);
  }

  async function loadSettings() {
    const [runtimes, observation] = await Promise.all([safe(() => cp.request("/runtimes"), []), safe(() => cp.request("/observation"), {})]);
    $("#runtime-grid").innerHTML = runtimes.map(runtime => `<article class="runtime-card"><p class="eyebrow">${esc(runtime.support)}</p><h3>${esc(runtime.name)}</h3>${cp.badge(runtime.available ? "available" : "not detected")}<p>${esc(runtime.detail || "No local runtime detail available.")}</p><div>${(runtime.capabilities || []).map(capability => `<span>${esc(capability)}</span>`).join("")}</div></article>`).join("") || '<div class="empty-state">No runtime capability data.</div>';
    $("#observation-status").innerHTML = `<p class="eyebrow">OBSERVATION</p><h3>${observation.running ? "Live observer running" : "Observer is not running"}</h3><p class="muted">Poll interval: ${esc(observation.interval_seconds || "—")} seconds · Docker event stream: ${observation.docker_event_stream ? "connected" : "unavailable or reconnecting"}</p>`;
  }

  async function searchPalette() {
    const query = $("#palette-input").value.trim();
    const target = $("#palette-results");
    if (!query) { target.innerHTML = '<div class="empty-inline">Try a port, container, project, Make target, or action.</div>'; return; }
    const results = await safe(() => cp.request(`/search?q=${encodeURIComponent(query)}`), []);
    const actions = [
      { label: "Find free port", action: "free-port" },
      { label: "Open topology", action: "topology" },
      { label: "Open approvals", action: "approvals" },
    ].filter(item => item.label.toLowerCase().includes(query.toLowerCase()));
    target.innerHTML = `${results.map(item => `<button class="palette-result" data-inspect-type="${esc(item.resource.resource_type)}" data-inspect-id="${esc(item.resource.resource_id)}"><span class="resource-dot" style="--dot:${colors[item.resource.resource_type] || "#8fa0b2"}"></span><span><b>${esc(item.resource.label)}</b><small>${esc(item.resource.resource_type)}</small></span></button>`).join("")}${actions.map(item => `<button class="palette-result" data-palette-action="${item.action}"><span>⌘</span><span><b>${esc(item.label)}</b><small>action</small></span></button>`).join("")}` || '<div class="empty-inline">No matching local resource or action.</div>';
  }
  function openPalette() { $("#command-palette").showModal(); $("#palette-input").focus(); }
  function closePalette() { $("#command-palette").close(); }

  document.addEventListener("controlplane:view", event => { loadControlView(event.detail.view); });
  document.addEventListener("click", async event => {
    const target = event.target.closest("button, tr, g.graph-node");
    if (!target) return;
    try {
      if (target.id === "open-palette") openPalette();
      if (target.id === "close-inspector") closeInspector();
      if (target.dataset.openWorkspace) await openWorkspace(target.dataset.openWorkspace);
      if (target.dataset.focusTopology) { cp.navigate("topology"); $("#topology-project").value = target.dataset.focusTopology; await loadTopology(); }
      if (target.dataset.focusFiles) { cp.navigate("files"); await loadFiles(target.dataset.focusFiles); }
      if (target.dataset.openFile) { if (target.dataset.fileProject) await openFile(target.dataset.openFile, target.dataset.fileProject); else await openFile(target.dataset.openFile); }
      if (target.dataset.inspectType) { await openResource(target.dataset.inspectType, target.dataset.inspectId); if ($("#command-palette").open) closePalette(); }
      if (target.dataset.resourceAction) await performResourceAction(target.dataset.resourceAction, target.dataset.resourceType, target.dataset.resourceId, target.dataset.projectId);
      if (target.dataset.topologyType) { const type = target.dataset.topologyType; state.topologyTypes.has(type) ? state.topologyTypes.delete(type) : state.topologyTypes.add(type); renderTopology(); }
      if (target.dataset.topologyZoom) zoomTopology(target.dataset.topologyZoom);
      if (target.dataset.paletteAction === "topology") { closePalette(); cp.navigate("topology"); }
      if (target.dataset.paletteAction === "approvals") { closePalette(); cp.navigate("approvals"); }
      if (target.dataset.paletteAction === "free-port") { closePalette(); cp.navigate("ports"); }
      if (target.id === "workspace-scan") { await cp.request("/projects/scan", { method: "POST" }); cp.toast("Configured roots scanned", "success"); await loadWorkspaces(); }
      if (target.id === "file-reload") await loadFiles(state.editor.projectId);
      if (target.id === "file-save") await saveFile();
      if (target.id === "file-revert") revertFile();
      if (target.id === "file-undo") await undoFile();
    } catch (error) { cp.toast(error.message, "error"); }
  });
  $("#workspace-search")?.addEventListener("input", renderWorkspaces);
  $("#process-search")?.addEventListener("input", renderProcesses);
  $("#topology-search")?.addEventListener("input", renderTopology);
  $("#topology-project")?.addEventListener("change", loadTopology);
  $("#file-project")?.addEventListener("change", event => loadFiles(event.target.value));
  $("#file-search")?.addEventListener("input", renderFiles);
  $("#file-editor")?.addEventListener("input", updateEditorGutter);
  $("#editor-find")?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); findInEditor(); } });
  $("#palette-input")?.addEventListener("input", () => { window.clearTimeout(state.paletteTimer); state.paletteTimer = window.setTimeout(searchPalette, 120); });
  $("#command-palette")?.addEventListener("click", event => { if (event.target === $("#command-palette")) closePalette(); });
  window.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openPalette(); }
    if (event.key === "Escape" && $("#resource-inspector").classList.contains("open")) closeInspector();
  });

  startEvents();
  window.setTimeout(() => loadControlView(location.hash.slice(1) || "overview"), 0);
})();
