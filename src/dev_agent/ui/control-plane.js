(() => {
  const cp = window.controlPlane;
  if (!cp) return;

  const state = {
    topology: null,
    topologyScale: 1,
    topologyOffset: { x: 0, y: 0 },
    topologyTypes: new Set(),
    topologyDragging: null,
    topologyPositions: new Map(),
    topologyLayout: "flow",
    topologySelectedId: "",
    topologyFiltered: null,
    topologyFilterResult: null,
    topologyFilterQuery: "",
    workspaces: [],
    processes: [],
    activity: [],
    files: [],
    editor: { projectId: "", path: "", hash: "", original: "" },
    eventSource: null,
    refreshTimer: null,
    lastLiveRefresh: 0,
    resourcePickerGraph: null,
    resourcePickerHydrated: false,
    resourcePickerType: "all",
    selectedResource: null,
    observeTab: "events",
    observePaused: false,
    autoScroll: true,
    logContainerId: "",
    logRaw: "",
    logTimer: null,
    metricTimer: null,
    previewEndpoints: [],
    previewUrl: "",
    adminTimer: null,
    adminData: null,
    adminTab: "observability",
  };

  const $ = cp.$;
  const $$ = cp.$$;
  const esc = cp.esc;
  const colors = {
    project: "#ededed", compose_project: "#a17bf7", compose_service: "#8f9dff",
    container: "#45d483", image: "#52a8ff", volume: "#f2b84b", network: "#e881c3",
    port: "#a17bf7", process: "#f2b84b", dockerfile: "#72b9f2", compose_file: "#9b9b9b",
    makefile: "#e1c65a", make_target: "#d5a95e", env_file: "#7fcf91", runtime: "#9b9b9b",
  };

  const safe = async (task, fallback = null) => {
    try { return await task(); }
    catch (error) { cp.toast(error.message, "error"); return fallback; }
  };
  const resourceButton = resource => `<button class="resource-link" data-inspect-type="${esc(resource.resource_type)}" data-inspect-id="${esc(resource.resource_id)}"><span class="resource-dot" style="--dot:${colors[resource.resource_type] || "#8fa0b2"}"></span>${esc(resource.label)}<small>${esc(resource.resource_type)}</small></button>`;
  const formatTime = value => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "now";

  async function loadControlView(view) {
    const loaders = {
      overview: loadOverviewTelemetry,
      workspaces: loadWorkspaces,
      topology: loadTopology,
      processes: loadProcesses,
      files: loadFilesView,
      activity: loadActivity,
      admin: loadAdmin,
      settings: loadSettings,
    };
    if (loaders[view]) await loaders[view]();
  }

  async function loadProjects() {
    const projects = await safe(() => cp.request("/projects"), []);
    if (!projects) return [];
    cp.state.projects = projects;
    $("#nav-project-count").textContent = projects.length;
    ["#topology-project", "#file-project", "#observe-project"].forEach(selector => {
      const select = $(selector);
      if (!select) return;
      const prior = select.value;
      const first = selector === "#topology-project"
        ? '<option value="">All observed resources</option>'
        : selector === "#observe-project"
          ? '<option value="">All workspaces</option>'
          : '<option value="">Select registered workspace…</option>';
      select.innerHTML = first + projects.map(project => `<option value="${esc(project.id)}">${esc(project.name)}</option>`).join("");
      if (projects.some(project => project.id === prior)) select.value = prior;
    });
    return projects;
  }

  async function loadOverviewTelemetry() {
    const [activity, observation] = await Promise.all([
      safe(() => cp.request("/activity?limit=12"), []),
      safe(() => cp.request("/observation"), {}),
    ]);
    if (activity?.length) state.activity = activity;
    const health = $("#overview-health");
    const runtime = $("#overview-runtime-status");
    if (health) health.textContent = observation?.running ? "Live" : "Unavailable";
    if (runtime) runtime.textContent = observation?.interval_seconds ? `Every ${observation.interval_seconds}s` : "On demand";
    renderOverviewActivity();
    renderOverviewPreviews();
  }

  function renderOverviewActivity() {
    const target = $("#overview-activity");
    if (!target) return;
    const items = state.activity.slice(-6);
    target.innerHTML = items.length
      ? items.map(eventLine).join("")
      : '<div class="empty-inline">No changes observed yet. The live stream is connected and waiting.</div>';
  }

  function probablePreviewEndpoints() {
    const ignored = new Set([22, 25, 53, 110, 143, 389, 465, 587, 993, 995, 1433, 1521, 2375, 2376, 3306, 5432, 5672, 6379, 9092, 27017]);
    const currentPort = Number(location.port || (location.protocol === "https:" ? 443 : 80));
    const likely = /web|http|frontend|ui|app|server|node|next|vite|react|vue|angular|nginx|caddy|traefik|uvicorn|gunicorn|flask|django/i;
    const endpoints = new Map();
    (cp.state.ports || []).forEach(item => {
      const port = Number(item.port);
      if (!port || item.protocol !== "tcp" || ignored.has(port) || port === currentPort) return;
      const owner = item.container || item.process || item.service || "Local service";
      const common = [80, 443, 3000, 3001, 4000, 4173, 4200, 5000, 5173, 5174, 8000, 8080, 8081, 8888].includes(port);
      const score = common ? 3 : likely.test(`${owner} ${item.command || ""}`) ? 2 : 1;
      const protocol = port === 443 ? "https" : "http";
      endpoints.set(port, { port, url: `${protocol}://127.0.0.1:${port}`, label: owner, project: item.project || item.service || "Runtime", score });
    });
    (cp.state.containers || []).forEach(container => (container.ports || []).forEach(binding => {
      const port = Number(binding.host_port);
      if (!port || ignored.has(port) || port === currentPort || endpoints.has(port)) return;
      const protocol = port === 443 ? "https" : "http";
      endpoints.set(port, { port, url: `${protocol}://127.0.0.1:${port}`, label: container.name, project: container.compose_project || container.compose_service || "Container", score: 2 });
    }));
    return [...endpoints.values()].sort((a, b) => b.score - a.score || a.port - b.port).slice(0, 20);
  }

  function renderOverviewPreviews() {
    const target = $("#overview-previews");
    if (!target) return;
    const endpoints = probablePreviewEndpoints().slice(0, 4);
    target.innerHTML = endpoints.length ? endpoints.map(endpoint => `
      <button class="preview-link" data-preview-port="${endpoint.port}"><span>↗</span><span><strong>${esc(endpoint.url)}</strong><small>${esc(endpoint.label)} · ${esc(endpoint.project)}</small></span><i>›</i></button>`).join("")
      : '<div class="empty-inline">No likely HTTP endpoints are listening.</div>';
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
    if (!state.topologyInitialized && !selector.value && cp.state.projects.length) {
      const richest = [...cp.state.projects].sort((a, b) => topologyProjectScore(b) - topologyProjectScore(a))[0];
      if (topologyProjectScore(richest) > 0) selector.value = richest.id;
    }
    state.topologyInitialized = true;
    const project = selector.value;
    const path = project ? `/topology/project/${encodeURIComponent(project)}` : "/topology";
    const graph = await safe(() => cp.request(path), { nodes: [], edges: [], warnings: [] });
    state.topology = graph;
    state.topologyFiltered = null;
    state.topologyFilterResult = null;
    state.topologyFilterQuery = "";
    state.topologySelectedId = "";
    state.topologyPositions = new Map();
    state.topologyScale = 1;
    state.topologyOffset = { x: 0, y: 0 };
    state.topologyTypes = new Set(graph.nodes.map(node => node.resource_type));
    updateSmartFilterStatus();
    renderTopology({ fit: true });
    cp.setSynced();
  }

  const topologyProjectScore = project => (project.services?.length || 0) * 4 + (project.ports?.length || 0) * 3 + (project.compose_files?.length || 0) * 2 + (project.dockerfiles?.length || 0);

  function renderTopology(options = {}) {
    const graph = state.topologyFiltered || state.topology;
    if (!graph) return;
    const query = $("#topology-search").value.trim().toLowerCase();
    const activeTypes = state.topologyTypes;
    let nodes = graph.nodes.filter(node => activeTypes.has(node.resource_type));
    const smartQueryActive = state.topologyFiltered && state.topologyFilterQuery === query;
    if (query && !smartQueryActive) {
      nodes = nodes.filter(node => `${node.label} ${node.status || ""} ${JSON.stringify(node.attributes)}`.toLowerCase().includes(query));
    }
    const sourceCount = nodes.length;
    if (nodes.length > 160 && !query) nodes = nodes.slice(0, 160);
    const selected = new Set(nodes.map(node => node.id));
    const edges = graph.edges.filter(edge => selected.has(edge.source) && selected.has(edge.target));
    renderTopologyLegend(graph.nodes);
    drawTopology(nodes, edges);
    if (options.fit) window.requestAnimationFrame(fitTopology);
    renderTopologySummary(nodes, edges, sourceCount);
  }

  function renderTopologySummary(nodes, edges, sourceCount) {
    const graph = state.topologyFiltered || state.topology;
    const selected = nodes.find(node => node.id === state.topologySelectedId);
    const connectedEdges = selected ? edges.filter(edge => selected.id === edge.source || selected.id === edge.target) : [];
    const connectedIds = new Set(connectedEdges.flatMap(edge => [edge.source, edge.target]).filter(id => id !== selected?.id));
    const connected = nodes.filter(node => connectedIds.has(node.id));
    const result = state.topologyFilterResult;
    const filterSummary = result ? `<div class="smart-plan-card"><div><span class="smart-mode">${cp.icon(result.mode === "ai" ? "brain" : "listFilter")} ${esc(result.mode === "ai" ? "AI interpreted" : "Locally parsed")}</span><strong>${esc(result.plan.explanation)}</strong><p>${result.matched_count} exact matches · ${result.visible_count} with context · ${Math.round((result.plan.confidence || 0) * 100)}% confidence</p></div><button class="mini-button" id="clear-smart-filter">Clear</button></div>` : "";
    const selectedCard = selected ? `<div class="selected-node-card"><div class="selected-node-title"><span class="resource-icon" style="--resource-color:${colors[selected.resource_type] || "#8fa0b2"}">${cp.icon(window.iconPack?.resource(selected.resource_type) || "circleHelp")}</span><div><p class="eyebrow">SELECTED</p><h3>${esc(selected.label)}</h3><p>${esc(selected.resource_type.replaceAll("_", " "))} · ${esc(selected.status || "observed")}</p></div></div><div class="selected-node-stats"><span><b>${connected.length}</b> neighbors</span><span><b>${connectedEdges.length}</b> links</span></div><button class="button secondary wide" data-open-graph-resource="${esc(selected.resource_type)}" data-resource-id="${esc(selected.resource_id)}">${cp.icon("scanSearch")} Inspect evidence</button></div>` : `<div class="graph-help"><span>${cp.icon("move")}</span><div><strong>Explore the graph</strong><p>Wheel to zoom at the pointer. Drag the canvas to pan, drag nodes to untangle them, click to focus, and double-click to inspect.</p></div></div>`;
    const warnings = (graph?.warnings || []).slice(0, 4);
    $("#topology-summary").innerHTML = `
      <div class="topology-statline"><span><b>${nodes.length}</b> visible</span><span><b>${edges.length}</b> relationships</span><span><b>${state.topologyLayout}</b> layout</span></div>
      ${sourceCount > nodes.length ? `<p class="graph-limit-note">Showing the first ${nodes.length} of ${sourceCount} resources. Scope or filter to reveal a useful subgraph.</p>` : ""}
      ${filterSummary}${selectedCard}
      <div class="topology-warnings">${warnings.length ? warnings.map(warning => `<div class="warning-row"><span>${cp.icon("info")}</span><div><b>${esc(warning.severity || "notice")}</b><p>${esc(warning.message)}</p></div></div>`).join("") : '<div class="empty-inline compact">No topology warnings in this scope.</div>'}</div>`;
    window.iconPack?.render($("#topology-summary"));
  }

  function renderTopologyLegend(nodes) {
    const counts = nodes.reduce((all, node) => ({ ...all, [node.resource_type]: (all[node.resource_type] || 0) + 1 }), {});
    $("#topology-legend").innerHTML = Object.entries(counts).sort().map(([type, count]) => `<button class="topology-filter ${state.topologyTypes.has(type) ? "active" : ""}" data-topology-type="${esc(type)}"><i style="background:${colors[type] || "#8fa0b2"}"></i>${esc(type.replaceAll("_", " "))}<b>${count}</b></button>`).join("");
  }

  function drawTopology(nodes, edges) {
    const svg = $("#topology-graph");
    svg.setAttribute("viewBox", "0 0 1200 720");
    svg.innerHTML = '<defs><marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L8,4 L0,8 Z" fill="currentColor"/></marker></defs>';
    const transform = document.createElementNS("http://www.w3.org/2000/svg", "g");
    transform.setAttribute("id", "topology-transform");
    transform.setAttribute("transform", topologyTransform());
    svg.append(transform);
    const positions = ensureTopologyPositions(nodes);
    if (state.topologyLayout === "flow") drawLaneLabels(nodes, positions, transform);
    const connectedIds = topologyConnectedIds(edges);
    edges.forEach(edge => {
      const source = positions.get(edge.source), target = positions.get(edge.target);
      if (!source || !target) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
      line.setAttribute("d", graphEdgePath(source, target));
      const isConnected = state.topologySelectedId && (edge.source === state.topologySelectedId || edge.target === state.topologySelectedId);
      line.setAttribute("class", `graph-edge ${isConnected ? "connected" : state.topologySelectedId ? "dimmed" : ""}`);
      line.setAttribute("marker-end", "url(#graph-arrow)");
      line.dataset.relationship = edge.relationship;
      line.dataset.source = edge.source;
      line.dataset.target = edge.target;
      transform.append(line);
      if (isConnected) {
        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", String((source.x + target.x) / 2));
        label.setAttribute("y", String((source.y + target.y) / 2 - 7));
        label.setAttribute("class", "graph-edge-label");
        label.textContent = edge.relationship.replaceAll("_", " ").toLowerCase();
        transform.append(label);
      }
    });
    nodes.forEach(node => {
      const point = positions.get(node.id);
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const selectionClass = node.id === state.topologySelectedId ? "selected" : state.topologySelectedId && !connectedIds.has(node.id) ? "dimmed" : state.topologySelectedId ? "connected" : "";
      const smartClass = state.topologyFilterResult?.matched_node_ids?.includes(node.id) ? "smart-match" : "";
      group.setAttribute("class", `graph-node ${selectionClass} ${smartClass}`);
      group.setAttribute("transform", `translate(${point.x - 82}, ${point.y - 28})`);
      group.dataset.resourceType = node.resource_type; group.dataset.resourceId = node.resource_id; group.dataset.graphNodeId = node.id;
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("width", "164"); rect.setAttribute("height", "56"); rect.setAttribute("rx", "10"); rect.setAttribute("fill", "#111722"); rect.setAttribute("stroke", colors[node.resource_type] || "#8a8a8a"); group.append(rect);
      const accent = document.createElementNS("http://www.w3.org/2000/svg", "rect"); accent.setAttribute("width", "4"); accent.setAttribute("height", "30"); accent.setAttribute("x", "10"); accent.setAttribute("y", "13"); accent.setAttribute("rx", "2"); accent.setAttribute("fill", colors[node.resource_type] || "#8fa0b2"); group.append(accent);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text"); label.setAttribute("x", "24"); label.setAttribute("y", "23"); label.setAttribute("class", "graph-label"); label.textContent = shorten(node.label, 20); group.append(label);
      const sub = document.createElementNS("http://www.w3.org/2000/svg", "text"); sub.setAttribute("x", "24"); sub.setAttribute("y", "42"); sub.setAttribute("class", "graph-sub"); sub.textContent = shorten(`${node.resource_type.replaceAll("_", " ")} · ${node.status || "observed"}`, 27); group.append(sub);
      const handle = document.createElementNS("http://www.w3.org/2000/svg", "circle"); handle.setAttribute("cx", "151"); handle.setAttribute("cy", "15"); handle.setAttribute("r", "3"); handle.setAttribute("class", "graph-node-handle"); group.append(handle);
      transform.append(group);
    });
    attachGraphInteractions(svg);
  }

  const flowLanes = [
    { name: "Workspace", types: ["project", "compose_project", "compose_file", "env_file"] },
    { name: "Build & orchestration", types: ["dockerfile", "makefile", "make_target", "compose_service"] },
    { name: "Runtime", types: ["container", "process", "runtime"] },
    { name: "Network", types: ["port", "network"] },
    { name: "Storage & artifacts", types: ["image", "volume"] },
  ];
  const laneFor = type => Math.max(0, flowLanes.findIndex(lane => lane.types.includes(type)));
  function ensureTopologyPositions(nodes) {
    const ids = new Set(nodes.map(node => node.id));
    [...state.topologyPositions.keys()].forEach(id => { if (!ids.has(id)) state.topologyPositions.delete(id); });
    if (state.topologyLayout === "radial") {
      const ordered = [...nodes].sort((a, b) => laneFor(a.resource_type) - laneFor(b.resource_type) || a.label.localeCompare(b.label));
      ordered.forEach((node, index) => {
        if (state.topologyPositions.has(node.id)) return;
        const ring = Math.floor(index / 28);
        const ringItems = Math.min(28, ordered.length - ring * 28);
        const angle = ((index % 28) / Math.max(1, ringItems)) * Math.PI * 2 - Math.PI / 2;
        const radiusX = 300 + ring * 205, radiusY = 220 + ring * 145;
        state.topologyPositions.set(node.id, { x: 600 + Math.cos(angle) * radiusX, y: 360 + Math.sin(angle) * radiusY });
      });
      return state.topologyPositions;
    }
    const grouped = flowLanes.map(() => []);
    nodes.forEach(node => grouped[laneFor(node.resource_type)].push(node));
    grouped.forEach(list => list.sort((a, b) => a.resource_type.localeCompare(b.resource_type) || a.label.localeCompare(b.label)));
    grouped.forEach((list, laneIndex) => list.forEach((node, index) => {
      if (!state.topologyPositions.has(node.id)) state.topologyPositions.set(node.id, { x: 120 + laneIndex * 245, y: 105 + index * 82 });
    }));
    return state.topologyPositions;
  }
  function drawLaneLabels(nodes, positions, transform) {
    flowLanes.forEach((lane, index) => {
      if (!nodes.some(node => lane.types.includes(node.resource_type))) return;
      const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
      title.setAttribute("x", String(38 + index * 245)); title.setAttribute("y", "44"); title.setAttribute("class", "graph-group-title"); title.textContent = lane.name; transform.append(title);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      const laneNodes = nodes.filter(node => lane.types.includes(node.resource_type)).map(node => positions.get(node.id));
      line.setAttribute("x1", String(38 + index * 245)); line.setAttribute("x2", String(202 + index * 245)); line.setAttribute("y1", "57"); line.setAttribute("y2", "57"); line.setAttribute("class", "graph-lane-rule"); transform.append(line);
    });
  }
  function topologyConnectedIds(edges) {
    const ids = new Set(state.topologySelectedId ? [state.topologySelectedId] : []);
    edges.forEach(edge => { if (edge.source === state.topologySelectedId || edge.target === state.topologySelectedId) { ids.add(edge.source); ids.add(edge.target); } });
    return ids;
  }
  function graphEdgePath(source, target) {
    const dx = target.x - source.x, direction = dx >= 0 ? 1 : -1;
    const startX = source.x + direction * 82, endX = target.x - direction * 82;
    const bend = Math.max(45, Math.abs(endX - startX) * .48);
    return `M ${startX} ${source.y} C ${startX + direction * bend} ${source.y}, ${endX - direction * bend} ${target.y}, ${endX} ${target.y}`;
  }
  const shorten = (value, length) => String(value || "").length > length ? `${String(value).slice(0, length - 1)}…` : String(value || "");
  const topologyTransform = () => `translate(${state.topologyOffset.x} ${state.topologyOffset.y}) scale(${state.topologyScale})`;
  function updateTopologyTransform() { $("#topology-transform")?.setAttribute("transform", topologyTransform()); updateZoomLabel(); }
  function updateZoomLabel() { const label = $("#topology-zoom-level"); if (label) label.textContent = `${Math.round(state.topologyScale * 100)}%`; }
  function zoomAt(nextScale, point = { x: 600, y: 360 }) {
    const scale = Math.min(3.2, Math.max(.12, nextScale));
    const world = { x: (point.x - state.topologyOffset.x) / state.topologyScale, y: (point.y - state.topologyOffset.y) / state.topologyScale };
    state.topologyOffset = { x: point.x - world.x * scale, y: point.y - world.y * scale };
    state.topologyScale = scale;
    updateTopologyTransform();
  }
  function zoomTopology(direction) {
    if (direction === "fit" || direction === "reset") { fitTopology(); return; }
    zoomAt(state.topologyScale * (direction === "in" ? 1.2 : 1 / 1.2));
  }
  function fitTopology() {
    const points = [...state.topologyPositions.values()];
    if (!points.length) { state.topologyScale = 1; state.topologyOffset = { x: 0, y: 0 }; updateTopologyTransform(); return; }
    const minX = Math.min(...points.map(point => point.x)) - 105, maxX = Math.max(...points.map(point => point.x)) + 105;
    const minY = Math.min(...points.map(point => point.y)) - 75, maxY = Math.max(...points.map(point => point.y)) + 75;
    const scale = Math.min(1.4, 1100 / Math.max(1, maxX - minX), 640 / Math.max(1, maxY - minY));
    state.topologyScale = Math.max(.12, scale);
    state.topologyOffset = { x: 600 - ((minX + maxX) / 2) * state.topologyScale, y: 360 - ((minY + maxY) / 2) * state.topologyScale };
    updateTopologyTransform();
  }
  function clientToSvg(svg, clientX, clientY) {
    const bounds = svg.getBoundingClientRect();
    return { x: (clientX - bounds.left) * 1200 / bounds.width, y: (clientY - bounds.top) * 720 / bounds.height };
  }
  function updateGraphGeometry() {
    $$(".graph-node", $("#topology-graph")).forEach(node => {
      const point = state.topologyPositions.get(node.dataset.graphNodeId);
      if (point) node.setAttribute("transform", `translate(${point.x - 82}, ${point.y - 28})`);
    });
    $$(".graph-edge", $("#topology-graph")).forEach(edge => {
      const source = state.topologyPositions.get(edge.dataset.source), target = state.topologyPositions.get(edge.dataset.target);
      if (source && target) edge.setAttribute("d", graphEdgePath(source, target));
    });
  }
  function selectTopologyNode(identifier) {
    state.topologySelectedId = state.topologySelectedId === identifier ? "" : identifier;
    renderTopology();
  }
  function attachGraphInteractions(svg) {
    svg.onwheel = event => {
      event.preventDefault();
      const point = clientToSvg(svg, event.clientX, event.clientY);
      zoomAt(state.topologyScale * Math.exp(-event.deltaY * .0014), point);
    };
    svg.onpointerdown = event => {
      if (event.button !== 0) return;
      const node = event.target.closest(".graph-node");
      const point = clientToSvg(svg, event.clientX, event.clientY);
      if (node) {
        const position = state.topologyPositions.get(node.dataset.graphNodeId);
        state.topologyDragging = { mode: "node", id: node.dataset.graphNodeId, start: point, origin: { ...position }, moved: false };
      } else {
        state.topologyDragging = { mode: "canvas", start: point, origin: { ...state.topologyOffset }, moved: false };
      }
      svg.setPointerCapture(event.pointerId);
    };
    svg.onpointermove = event => {
      const drag = state.topologyDragging;
      if (!drag) return;
      const point = clientToSvg(svg, event.clientX, event.clientY);
      const dx = point.x - drag.start.x, dy = point.y - drag.start.y;
      drag.moved ||= Math.abs(dx) + Math.abs(dy) > 3;
      if (drag.mode === "canvas") {
        state.topologyOffset = { x: drag.origin.x + dx, y: drag.origin.y + dy };
        updateTopologyTransform();
      } else {
        state.topologyPositions.set(drag.id, { x: drag.origin.x + dx / state.topologyScale, y: drag.origin.y + dy / state.topologyScale });
        updateGraphGeometry();
      }
    };
    svg.onpointerup = event => {
      const drag = state.topologyDragging;
      if (drag?.mode === "node" && !drag.moved) selectTopologyNode(drag.id);
      state.topologyDragging = null;
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    };
    svg.onclick = event => { if (!event.target.closest(".graph-node") && !state.topologyDragging) { state.topologySelectedId = ""; renderTopology(); } event.stopPropagation(); };
    svg.ondblclick = event => {
      const node = event.target.closest(".graph-node");
      if (node) openResource(node.dataset.resourceType, node.dataset.resourceId);
      event.stopPropagation();
    };
  }

  async function applyIntelligentTopologyFilter() {
    const input = $("#topology-search");
    const query = input.value.trim();
    if (!query) { clearIntelligentTopologyFilter(); return; }
    const button = $("#topology-smart-filter");
    button.disabled = true; button.classList.add("loading");
    try {
      const result = await cp.request("/intelligence/filter", { method: "POST", body: JSON.stringify({ query, project: $("#topology-project").value || null, use_ai: true }) });
      state.topologyFiltered = result.graph;
      state.topologyFilterResult = result;
      state.topologyFilterQuery = query.toLowerCase();
      state.topologyPositions = new Map();
      state.topologyTypes = new Set(result.graph.nodes.map(node => node.resource_type));
      updateSmartFilterStatus();
      renderTopology({ fit: true });
      cp.toast(`${result.mode === "ai" ? "AI" : "Local"} filter found ${result.matched_count} exact matches.`, "success");
    } finally { button.disabled = false; button.classList.remove("loading"); }
  }
  function clearIntelligentTopologyFilter() {
    state.topologyFiltered = null; state.topologyFilterResult = null; state.topologyFilterQuery = ""; state.topologyPositions = new Map();
    state.topologyTypes = new Set((state.topology?.nodes || []).map(node => node.resource_type));
    updateSmartFilterStatus(); renderTopology({ fit: true });
  }
  function updateSmartFilterStatus() {
    const target = $("#topology-query-state");
    if (!target) return;
    const result = state.topologyFilterResult;
    target.className = `query-state ${result ? "active" : ""}`;
    target.innerHTML = result ? `${cp.icon(result.mode === "ai" ? "brain" : "listFilter")} ${result.mode === "ai" ? "AI plan active" : "Local plan active"}` : `${cp.icon("search")} Local text filter`;
    window.iconPack?.render(target);
  }

  async function openResource(type, id) {
    const known = [state.resourcePickerGraph, state.topology].filter(Boolean).flatMap(graph => graph.nodes || []).find(node => node.resource_type === type && node.resource_id === id);
    $("#inspector-type").textContent = type.replaceAll("_", " ").toUpperCase();
    $("#inspector-title").textContent = known?.label || "Loading live evidence…";
    $("#inspector-icon").innerHTML = resourceIcon(type);
    $("#inspector-content").innerHTML = '<div class="empty-inline"><span class="spinner"></span>Correlating runtime and configuration evidence…</div>';
    if (known) { state.selectedResource = known; $("#selected-resource-label").textContent = known.label; }
    const panel = $("#resource-inspector"); panel.classList.add("open"); panel.setAttribute("aria-hidden", "false");
    if ($("#resource-picker")?.open) $("#resource-picker").close();
    if ($("#command-palette")?.open) $("#command-palette").close();
    const detail = await safe(() => cp.request(`/resources/${encodeURIComponent(type)}/${encodeURIComponent(id)}`));
    if (!detail) { closeInspector(); return; }
    state.selectedResource = detail.node;
    $("#selected-resource-label").textContent = detail.node.label;
    $("#inspector-type").textContent = detail.node.resource_type.replaceAll("_", " ").toUpperCase();
    $("#inspector-title").textContent = detail.node.label;
    $("#inspector-icon").innerHTML = resourceIcon(detail.node.resource_type);
    const attributes = Object.entries(detail.node.attributes || {}).filter(([key]) => !["content", "command"].includes(key));
    $("#inspector-content").innerHTML = `
      <div class="inspector-status">${cp.badge(detail.node.status || "observed")}<span class="inspector-meta">Observed ${formatTime(detail.generated_at)}</span></div>
      ${resourceActions(detail.node, detail.related)}
      <div class="inspector-section"><div class="inspector-section-head"><p class="eyebrow">OVERVIEW</p><span class="inspector-meta">${attributes.length} attributes</span></div>
      <dl class="attribute-list">${attributes.slice(0, 14).map(([key, value]) => `<div><dt>${esc(key.replaceAll("_", " "))}</dt><dd>${esc(formatAttribute(value))}</dd></div>`).join("") || '<div class="empty-inline">No additional attributes.</div>'}</dl>
      </div>
      <div class="inspector-section"><div class="inspector-section-head"><p class="eyebrow">CONNECTED RESOURCES</p><span class="inspector-meta">${detail.related.length} direct</span></div><div class="inspector-related">${detail.related.length ? detail.related.map(resourceButton).join("") : '<div class="empty-inline">No direct relationships.</div>'}</div></div>
      <div class="inspector-section"><p class="eyebrow">RELATIONSHIPS</p><div class="relationship-list">${detail.relationships.map(edge => `<span>${esc(edge.relationship)}</span>`).join("") || '<span>None</span>'}</div></div>
      <div class="inspector-section"><div class="inspector-section-head"><p class="eyebrow">RAW EVIDENCE</p><span class="inspector-meta">Read only</span></div><pre class="inspector-json">${esc(JSON.stringify({ node: detail.node, relationships: detail.relationships }, null, 2))}</pre></div>`;
  }
  function resourceIcon(type) { return cp.icon(window.iconPack?.resource(type) || "circleHelp"); }
  function resourceActions(node, related = []) {
    if (node.resource_type === "container") {
      const port = node.attributes.ports?.[0]?.host_port || related.find(item => item.resource_type === "port")?.attributes?.port;
      return `<p class="eyebrow">QUICK ACTIONS</p><div class="inspector-actions"><button class="button primary" data-resource-action="observe" data-resource-type="container" data-resource-id="${esc(node.resource_id)}">View live logs</button>${port ? `<button class="button secondary" data-resource-action="preview" data-resource-type="container" data-resource-id="${esc(node.resource_id)}" data-port="${esc(port)}">Preview :${esc(port)}</button>` : ""}<button class="button secondary" data-resource-action="restart" data-resource-type="container" data-resource-id="${esc(node.resource_id)}">Restart</button><button class="button secondary" data-resource-action="stop" data-resource-type="container" data-resource-id="${esc(node.resource_id)}">Stop</button></div>`;
    }
    if (node.resource_type === "project" && node.attributes.registered) return `<p class="eyebrow">QUICK ACTIONS</p><div class="inspector-actions"><button class="button primary" data-resource-action="workspace" data-resource-type="project" data-resource-id="${esc(node.resource_id)}">Open workspace</button><button class="button secondary" data-resource-action="topology" data-resource-type="project" data-resource-id="${esc(node.resource_id)}">Scope topology</button><button class="button secondary" data-resource-action="files" data-resource-type="project" data-resource-id="${esc(node.resource_id)}">Open files</button><button class="button secondary" data-resource-action="prepare" data-resource-type="project" data-resource-id="${esc(node.resource_id)}">Prepare</button></div>`;
    if (node.resource_type === "port" && node.attributes.port && String(node.attributes.protocol || "tcp") === "tcp") return `<p class="eyebrow">QUICK ACTIONS</p><div class="inspector-actions"><button class="button primary" data-resource-action="preview" data-resource-type="port" data-resource-id="${esc(node.resource_id)}" data-port="${esc(node.attributes.port)}">Open preview :${esc(node.attributes.port)}</button></div>`;
    if (node.resource_type === "process" && node.attributes.ports?.length) return `<p class="eyebrow">QUICK ACTIONS</p><div class="inspector-actions"><button class="button secondary" data-resource-action="preview" data-resource-type="process" data-resource-id="${esc(node.resource_id)}" data-port="${esc(node.attributes.ports[0])}">Preview :${esc(node.attributes.ports[0])}</button></div>`;
    if (node.resource_type === "compose_service" && node.attributes.project_id) return `<p class="eyebrow">QUICK ACTIONS</p><div class="inspector-actions"><button class="button secondary" data-resource-action="restart-service" data-resource-type="compose_service" data-resource-id="${esc(node.resource_id)}" data-project-id="${esc(node.attributes.project_id)}">Restart service</button></div>`;
    return "";
  }
  async function performResourceAction(action, type, id, projectId, port) {
    if (action === "preview" && port) { closeInspector(); await openPreviewPort(port); return; }
    if (type === "container" && action === "observe") { closeInspector(); await selectContainer(id); return; }
    if (type === "container") {
      const result = await cp.request(`/containers/${encodeURIComponent(id)}/${action}`, { method: "POST" });
      cp.handleOperation(result, `Container ${action} proposed`);
      return;
    }
    if (type === "project" && action === "workspace") { closeInspector(); cp.navigate("workspaces"); await openWorkspace(id); return; }
    if (type === "project" && action === "topology") { closeInspector(); cp.navigate("topology"); $("#topology-project").value = id; await loadTopology(); return; }
    if (type === "project" && action === "files") { closeInspector(); cp.navigate("files"); await loadFiles(id); return; }
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
    const [activity, containers, ports, observation] = await Promise.all([
      safe(() => cp.request("/activity?limit=250"), []),
      safe(() => cp.request("/containers"), []),
      safe(() => cp.request("/ports"), []),
      safe(() => cp.request("/observation"), {}),
    ]);
    await loadProjects();
    state.activity = activity;
    cp.state.containers = containers;
    cp.state.ports = ports;
    populateContainerSelect(containers);
    populatePreviewSelect();
    $("#observe-events-count").textContent = activity.length;
    $("#observe-running-count").textContent = containers.filter(item => item.state === "running").length;
    $("#observe-listeners-count").textContent = new Set(ports.map(item => `${item.protocol}:${item.port}`)).size;
    $("#observe-interval").textContent = observation.interval_seconds ? `${observation.interval_seconds}s` : "—";
    $("#observe-status-text").textContent = observation.running ? "Observer active" : "Observer unavailable";
    renderActivity();
    if (state.observeTab === "logs" && state.logContainerId) pollContainerLogs();
  }
  function renderActivity() {
    const target = $("#activity-feed");
    if (!target) return;
    const query = $("#observe-search")?.value.trim().toLowerCase() || "";
    const projectId = $("#observe-project")?.value || "";
    const project = cp.state.projects.find(item => item.id === projectId);
    const items = state.activity.filter(event => {
      const encoded = JSON.stringify(event).toLowerCase();
      const matchesQuery = !query || encoded.includes(query);
      const matchesProject = !project || encoded.includes(project.id.toLowerCase()) || encoded.includes(project.name.toLowerCase()) || encoded.includes(String(project.path).toLowerCase());
      return matchesQuery && matchesProject;
    });
    target.innerHTML = items.length ? items.map(eventLine).join("") : '<div class="empty-state">No observed events match the current filters.</div>';
    $("#console-result-count").textContent = `${items.length} ${items.length === 1 ? "entry" : "entries"}`;
    $("#observe-events-count").textContent = state.activity.length;
    if (state.autoScroll) target.scrollTop = target.scrollHeight;
  }
  function eventLine(event) {
    const inspectable = event.resource_type !== "topology" && colors[event.resource_type];
    const inspectId = event.resource_type === "port" && event.data?.port
      ? `${event.data.protocol || "tcp"}:${event.data.port}`
      : event.resource_id;
    return `<div class="event-line"><time>${esc(formatTime(event.created_at))}</time><span class="event-kind ${esc(event.resource_type)}">${esc(event.resource_type)}</span><span class="event-message">${esc(event.message)}</span><span class="event-resource">${esc(event.action || event.type)}${inspectable ? ` <button class="mini-button" data-inspect-type="${esc(event.resource_type)}" data-inspect-id="${esc(inspectId)}">Inspect</button>` : ""}</span></div>`;
  }
  function appendActivity(event) {
    if (state.activity.some(item => item.id === event.id)) return;
    state.activity.push(event); state.activity = state.activity.slice(-250);
    if (!state.observePaused && location.hash.slice(1) === "activity" && state.observeTab === "events") renderActivity();
    if (location.hash.slice(1) === "overview") renderOverviewActivity();
  }
  function startEvents() {
    if (state.eventSource || !window.EventSource) return;
    const source = new EventSource("/api/v1/events/stream"); state.eventSource = source;
    source.onopen = () => setStreamState(true);
    source.onmessage = event => {
      try { const payload = JSON.parse(event.data); appendActivity(payload); scheduleLiveRefresh(payload); }
      catch (_) { /* ignore malformed non-authoritative stream data */ }
    };
    source.onerror = () => { setStreamState(false); source.close(); state.eventSource = null; window.setTimeout(startEvents, 4000); };
  }
  function setStreamState(connected) {
    $("#stream-indicator")?.classList.toggle("offline", !connected);
    const label = $("#observe-status-text");
    if (label) label.textContent = connected ? "Observer active" : "Reconnecting…";
    const mode = $("#console-mode");
    if (mode && state.observeTab === "events") mode.textContent = connected ? "Event stream connected" : "Event stream reconnecting";
  }

  function setObserveTab(tab) {
    state.observeTab = tab === "logs" ? "logs" : "events";
    $$('[data-observe-tab]').forEach(node => node.classList.toggle("active", node.dataset.observeTab === state.observeTab));
    $("#activity-feed").classList.toggle("hidden", state.observeTab !== "events");
    $("#container-log-output").classList.toggle("hidden", state.observeTab !== "logs");
    $("#observe-project").style.display = state.observeTab === "events" ? "block" : "none";
    $("#log-container").style.display = state.observeTab === "logs" ? "block" : "none";
    $("#console-mode").textContent = state.observeTab === "events" ? "Event stream connected" : state.logContainerId ? "Polling logs every 2.5s" : "Select a container";
    if (state.observeTab === "events") { window.clearTimeout(state.logTimer); renderActivity(); }
    else { renderLogs(); if (state.logContainerId) pollContainerLogs(); }
  }

  function populateContainerSelect(containers) {
    const select = $("#log-container");
    if (!select) return;
    const prior = state.logContainerId || select.value;
    select.innerHTML = '<option value="">Select container…</option>' + containers.map(container => `<option value="${esc(container.id)}">${esc(container.name)} · ${esc(container.state)}</option>`).join("");
    if (containers.some(container => container.id === prior)) { select.value = prior; state.logContainerId = prior; }
  }

  async function selectContainer(identifier) {
    cp.navigate("activity");
    if (!cp.state.containers.some(item => item.id === identifier)) await loadActivity();
    state.logContainerId = identifier;
    $("#log-container").value = identifier;
    setObserveTab("logs");
    await pollContainerLogs();
  }

  async function pollContainerLogs() {
    window.clearTimeout(state.logTimer);
    window.clearTimeout(state.metricTimer);
    const identifier = state.logContainerId;
    if (!identifier || state.observePaused) return;
    try {
      const [logs, stats] = await Promise.all([
        cp.request(`/containers/${encodeURIComponent(identifier)}/logs?tail=500`),
        cp.request(`/containers/${encodeURIComponent(identifier)}/stats`).catch(() => null),
      ]);
      if (identifier !== state.logContainerId) return;
      state.logRaw = logs.logs || "";
      renderLogs();
      renderContainerMetrics(stats, cp.state.containers.find(item => item.id === identifier));
      $("#console-mode").textContent = "Polling logs every 2.5s";
    } catch (error) {
      $("#container-log-output").textContent = `Unable to read container logs: ${error.message}`;
      $("#console-mode").textContent = "Log source unavailable";
    }
    if (location.hash.slice(1) === "activity" && state.observeTab === "logs" && state.logContainerId) {
      state.logTimer = window.setTimeout(pollContainerLogs, 2500);
    }
  }

  function renderLogs() {
    const target = $("#container-log-output");
    if (!target) return;
    if (!state.logContainerId) {
      target.textContent = "Select a running container to begin tailing logs.";
      $("#console-result-count").textContent = "0 lines";
      return;
    }
    const query = $("#observe-search")?.value.trim().toLowerCase() || "";
    const allLines = state.logRaw.split("\n");
    const lines = allLines.map((line, index) => ({ line, index: index + 1 })).filter(item => !query || item.line.toLowerCase().includes(query));
    target.innerHTML = lines.length
      ? lines.map(item => `<span class="log-line"><span class="log-line-number">${item.index}</span>${esc(item.line) || " "}</span>`).join("")
      : '<span class="log-line"><span class="log-line-number">—</span>No log lines match the current filter.</span>';
    $("#console-result-count").textContent = `${lines.length} ${lines.length === 1 ? "line" : "lines"}`;
    if (state.autoScroll) target.scrollTop = target.scrollHeight;
  }

  function renderContainerMetrics(stats, container) {
    const target = $("#container-metrics");
    const status = $("#metrics-status");
    if (!stats || !container) {
      status.textContent = "Unavailable";
      target.innerHTML = '<div class="empty-inline">Runtime metrics are unavailable for this container.</div>';
      return;
    }
    const cpuNow = stats.cpu_stats?.cpu_usage?.total_usage || 0;
    const cpuBefore = stats.precpu_stats?.cpu_usage?.total_usage || 0;
    const systemNow = stats.cpu_stats?.system_cpu_usage || 0;
    const systemBefore = stats.precpu_stats?.system_cpu_usage || 0;
    const cpus = stats.cpu_stats?.online_cpus || stats.cpu_stats?.cpu_usage?.percpu_usage?.length || 1;
    const cpuPercent = systemNow > systemBefore ? Math.max(0, ((cpuNow - cpuBefore) / (systemNow - systemBefore)) * cpus * 100) : 0;
    const memoryCache = stats.memory_stats?.stats?.inactive_file || stats.memory_stats?.stats?.cache || 0;
    const memory = Math.max(0, (stats.memory_stats?.usage || 0) - memoryCache);
    const memoryLimit = stats.memory_stats?.limit || 0;
    const networks = Object.values(stats.networks || {});
    const received = networks.reduce((sum, item) => sum + (item.rx_bytes || 0), 0);
    const sent = networks.reduce((sum, item) => sum + (item.tx_bytes || 0), 0);
    status.textContent = container.state;
    status.className = `status-badge ${container.state === "running" ? "ready" : "muted"}`;
    target.innerHTML = `
      <div class="metric-row"><span>CPU usage</span><strong>${cpuPercent.toFixed(2)}%</strong></div>
      <div class="metric-row"><span>Memory</span><strong>${cp.fmtBytes(memory)}${memoryLimit ? ` / ${cp.fmtBytes(memoryLimit)}` : ""}</strong></div>
      <div class="metric-row"><span>Network received</span><strong>${cp.fmtBytes(received)}</strong></div>
      <div class="metric-row"><span>Network sent</span><strong>${cp.fmtBytes(sent)}</strong></div>
      <div class="metric-row"><span>Processes</span><strong>${esc(stats.pids_stats?.current ?? "—")}</strong></div>
      <div class="metric-row"><span>Restarts</span><strong>${esc(container.restart_count ?? 0)}</strong></div>`;
  }

  function populatePreviewSelect() {
    state.previewEndpoints = probablePreviewEndpoints();
    const select = $("#preview-endpoint");
    if (!select) return;
    const prior = state.previewUrl || select.value;
    select.innerHTML = '<option value="">Select detected endpoint…</option>' + state.previewEndpoints.map(endpoint => `<option value="${esc(endpoint.url)}">:${endpoint.port} · ${esc(endpoint.label)} (${esc(endpoint.project)})</option>`).join("");
    if (state.previewEndpoints.some(endpoint => endpoint.url === prior)) select.value = prior;
  }

  function selectPreview(url) {
    state.previewUrl = url || "";
    const frame = $("#preview-frame");
    const empty = $("#preview-empty");
    $("#preview-url").textContent = url || "Select a local endpoint";
    if (!url) { frame.classList.remove("active"); empty.classList.remove("hidden"); return; }
    frame.src = url;
    frame.classList.add("active");
    empty.classList.add("hidden");
    $("#preview-endpoint").value = url;
  }

  async function openPreviewPort(port) {
    cp.navigate("activity");
    await loadActivity();
    const endpoint = state.previewEndpoints.find(item => Number(item.port) === Number(port)) || { url: `http://127.0.0.1:${Number(port)}` };
    if (!state.previewEndpoints.some(item => item.url === endpoint.url)) {
      state.previewEndpoints.unshift({ port: Number(port), url: endpoint.url, label: "Local service", project: "Runtime", score: 4 });
      const select = $("#preview-endpoint");
      select.insertAdjacentHTML("beforeend", `<option value="${esc(endpoint.url)}">:${esc(port)} · Local service</option>`);
    }
    selectPreview(endpoint.url);
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

  async function loadAdmin() {
    window.clearTimeout(state.adminTimer);
    $("#admin-refresh-status").textContent = "Refreshing…";
    const data = await safe(() => cp.request("/admin/overview"), null);
    if (!data) { $("#admin-refresh-status").textContent = "Unavailable"; return; }
    state.adminData = data;
    renderAdmin(data);
    cp.setSynced();
    $("#admin-refresh-status").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    if ((location.hash.slice(1) || "overview") === "admin") state.adminTimer = window.setTimeout(loadAdmin, 5000);
  }

  function renderAdmin(data) {
    const telemetry = data.telemetry || {}, requests = telemetry.requests || {}, llm = telemetry.llm || {};
    const database = data.database || {}, events = data.events || {}, process = data.process || {}, harness = data.harness || {};
    $("#admin-uptime").textContent = formatDuration(telemetry.uptime_seconds || 0);
    $("#admin-api-requests").textContent = Number(requests.total || 0).toLocaleString();
    $("#admin-request-rate").textContent = `${requests.requests_last_minute || 0} in the last minute`;
    $("#admin-p95").textContent = `${Number(requests.latency_ms?.p95 || 0).toFixed(1)} ms`;
    $("#admin-error-rate").textContent = `${((requests.error_rate || 0) * 100).toFixed(2)}% server errors`;
    $("#admin-llm-calls").textContent = Number(llm.calls || 0).toLocaleString();
    $("#admin-token-usage").textContent = `${Number(llm.total_tokens || 0).toLocaleString()} observed tokens`;
    $("#admin-db-rows").textContent = Number(database.total_rows || 0).toLocaleString();
    $("#admin-db-size").textContent = `${cp.fmtBytes(database.size_bytes || 0)} on disk`;
    $("#admin-active-requests").textContent = `${requests.active || 0} active`;
    renderRequestChart(requests.samples || []);
    const statuses = Object.entries(requests.statuses || {});
    const statusTotal = Math.max(1, statuses.reduce((sum, [, count]) => sum + count, 0));
    $("#admin-status-distribution").innerHTML = statuses.length ? statuses.sort().map(([status, count]) => `<div class="distribution-row"><div><span>${esc(status)}</span><b>${esc(count)}</b></div><div><i class="status-${esc(status[0])}" style="width:${Math.max(2, count / statusTotal * 100)}%"></i></div></div>`).join("") : '<div class="empty-inline">No request responses sampled yet.</div>';
    $("#admin-route-table").innerHTML = (requests.routes || []).length ? requests.routes.map(route => `<tr><td class="mono">${esc(route.route)}</td><td>${Number(route.count).toLocaleString()}</td></tr>`).join("") : '<tr><td colspan="2"><div class="empty-inline">No normalized routes recorded.</div></td></tr>';
    const modelNames = Object.entries(llm.models || {}).map(([name, count]) => `${name} (${count})`).join(", ") || "No calls yet";
    $("#admin-llm-panel").innerHTML = detailRows([
      ["Models", modelNames], ["Successful", `${llm.successful || 0} / ${llm.calls || 0}`],
      ["Input tokens", Number(llm.input_tokens || 0).toLocaleString()], ["Output tokens", Number(llm.output_tokens || 0).toLocaleString()],
      ["Last operation", llm.last_call?.operation || "—"], ["Last latency", llm.last_call ? `${llm.last_call.duration_ms} ms` : "—"],
    ]);
    $("#admin-event-panel").innerHTML = detailRows([
      ["Observer", data.observer?.running ? "Running" : "Stopped"], ["Docker stream", data.observer?.docker_event_stream ? "Connected" : "Unavailable"],
      ["Published", Number(events.published_total || 0).toLocaleString()], ["Buffered", `${events.buffered || 0} / ${events.history_capacity || 0}`],
      ["SSE subscribers", events.subscribers || 0], ["Last event", events.last_event?.type || "Waiting for change"],
    ]);
    $("#admin-process-panel").innerHTML = detailRows([
      ["PID", process.pid || "—"], ["Resident memory", cp.fmtBytes(process.rss_bytes || 0)], ["CPU time", `${process.cpu_time_seconds || 0} s`],
      ["Threads", process.threads || 0], ["Python", process.python || "—"], ["Load average", (process.load_average || []).map(value => Number(value).toFixed(2)).join(" · ") || "—"],
    ]);
    renderHarness(harness);
    window.iconPack?.render($("#view-admin"));
  }
  function detailRows(rows) { return rows.map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join(""); }
  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const days = Math.floor(total / 86400), hours = Math.floor(total % 86400 / 3600), minutes = Math.floor(total % 3600 / 60);
    return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m ${total % 60}s`;
  }
  function renderRequestChart(samples) {
    const svg = $("#admin-request-chart"), tooltip = $("#admin-chart-tooltip");
    if (!samples.length) { svg.innerHTML = '<text x="410" y="118" text-anchor="middle" class="chart-empty">Request samples will appear here.</text>'; tooltip.classList.remove("visible"); return; }
    const values = samples.map(sample => Number(sample.duration_ms || 0));
    const max = Math.max(1, ...values, Number(state.adminData?.telemetry?.requests?.latency_ms?.p95 || 0) * 1.25);
    const points = samples.map((sample, index) => ({ x: 20 + index * 780 / Math.max(1, samples.length - 1), y: 205 - Math.min(max, Number(sample.duration_ms || 0)) / max * 175, sample }));
    const line = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
    const area = `${line} L${points.at(-1).x.toFixed(1)},205 L${points[0].x.toFixed(1)},205 Z`;
    const grid = [30, 73.75, 117.5, 161.25, 205].map((y, index) => `<line x1="20" x2="800" y1="${y}" y2="${y}" class="chart-grid"/><text x="8" y="${y + 3}" class="chart-axis">${Math.round(max * (4 - index) / 4)}</text>`).join("");
    svg.innerHTML = `${grid}<defs><linearGradient id="latency-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7aa2ff" stop-opacity=".3"/><stop offset="1" stop-color="#7aa2ff" stop-opacity="0"/></linearGradient></defs><path d="${area}" class="chart-area"/><path d="${line}" class="chart-line"/><circle id="admin-chart-cursor" cx="${points.at(-1).x}" cy="${points.at(-1).y}" r="4" class="chart-cursor"/>`;
    svg.onpointermove = event => {
      const bounds = svg.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
      const point = points[Math.round(ratio * (points.length - 1))];
      const cursor = $("#admin-chart-cursor"); cursor.setAttribute("cx", point.x); cursor.setAttribute("cy", point.y);
      tooltip.innerHTML = `<strong>${esc(point.sample.route)}</strong><span>${esc(point.sample.duration_ms)} ms · HTTP ${esc(point.sample.status_code)}</span><small>${esc(new Date(point.sample.time).toLocaleTimeString())}</small>`;
      tooltip.style.left = `${Math.min(bounds.width - 210, Math.max(8, event.clientX - bounds.left + 12))}px`;
      tooltip.style.top = `${Math.max(8, event.clientY - bounds.top - 72)}px`;
      tooltip.classList.add("visible");
    };
    svg.onpointerleave = () => tooltip.classList.remove("visible");
  }
  function renderHarness(harness) {
    const configured = harness.provider_configured;
    $("#admin-harness-overview").innerHTML = `
      <article><span>${cp.icon("bot")}</span><div><small>Agent model</small><strong>${esc(harness.agent_model || "Deterministic only")}</strong><p>${configured ? "Provider configured" : "No main model configured"}</p></div></article>
      <article><span>${cp.icon("brain")}</span><div><small>Filter interpreter</small><strong>${esc(harness.filter_model || "Disabled")}</strong><p>${harness.structured_filtering ? "Strict output enabled" : "Local parser fallback"}</p></div></article>
      <article><span>${cp.icon("shieldCheck")}</span><div><small>Approval boundary</small><strong>Medium+ always gated</strong><p>Read-only ${harness.auto_approve?.read_only ? "automatic" : "manual"}</p></div></article>
      <article><span>${cp.icon("scanSearch")}</span><div><small>Discovery</small><strong>${esc((harness.project_roots || []).join(", ") || "No roots")}</strong><p>Maximum depth ${esc(harness.project_scan_depth || "—")}</p></div></article>`;
    $("#admin-tool-count").textContent = `${harness.tool_count || 0} tools`;
    $("#admin-tools").innerHTML = (harness.tools || []).map(tool => `<span>${cp.icon("terminal")} ${esc(tool.replaceAll("_", " "))}</span>`).join("") || '<div class="empty-inline">No agent tools registered.</div>';
    $("#admin-policy-table").innerHTML = (harness.policies || []).map(policy => `<tr><td class="mono">${esc(policy.action)}</td><td>${cp.badge(policy.risk)}</td><td>${policy.approval_required ? `${cp.icon("shieldCheck")} Required` : `${cp.icon("check")} Automatic`}</td></tr>`).join("") || '<tr><td colspan="3"><div class="empty-inline">No mutation policies registered.</div></td></tr>';
  }
  function setAdminTab(tab) {
    state.adminTab = tab;
    $$("[data-admin-tab]").forEach(node => node.classList.toggle("active", node.dataset.adminTab === tab));
    $$("[data-admin-pane]").forEach(node => node.classList.toggle("active", node.dataset.adminPane === tab));
  }

  async function loadSettings() {
    const [runtimes, observation] = await Promise.all([safe(() => cp.request("/runtimes"), []), safe(() => cp.request("/observation"), {})]);
    $("#runtime-grid").innerHTML = runtimes.map(runtime => `<article class="runtime-card"><p class="eyebrow">${esc(runtime.support)}</p><h3>${esc(runtime.name)}</h3>${cp.badge(runtime.available ? "available" : "not detected")}<p>${esc(runtime.detail || "No local runtime detail available.")}</p><div>${(runtime.capabilities || []).map(capability => `<span>${esc(capability)}</span>`).join("")}</div></article>`).join("") || '<div class="empty-state">No runtime capability data.</div>';
    $("#observation-status").innerHTML = `<p class="eyebrow">OBSERVATION</p><h3>${observation.running ? "Live observer running" : "Observer is not running"}</h3><p class="muted">Poll interval: ${esc(observation.interval_seconds || "—")} seconds · Docker event stream: ${observation.docker_event_stream ? "connected" : "unavailable or reconnecting"}</p>`;
  }

  async function openResourcePicker() {
    const dialog = $("#resource-picker");
    if (!dialog.open) dialog.showModal();
    $("#resource-picker-input").value = "";
    $("#resource-picker-input").focus();
    if (!state.resourcePickerGraph) state.resourcePickerGraph = quickResourceGraph();
    renderResourcePickerTypes();
    renderResourcePicker();
    if (!state.resourcePickerHydrated) hydrateResourcePicker();
  }

  function quickResourceGraph() {
    const nodes = [];
    (cp.state.projects || []).forEach(project => nodes.push({ id: `project:${project.id}`, resource_type: "project", resource_id: project.id, label: project.name, status: project.status, attributes: project }));
    (cp.state.containers || []).forEach(container => nodes.push({ id: `container:${container.id}`, resource_type: "container", resource_id: container.id, label: container.name, status: container.state, attributes: container }));
    const seenPorts = new Set();
    (cp.state.ports || []).forEach(port => {
      const resourceId = `${port.protocol}:${port.port}`;
      if (seenPorts.has(resourceId)) return;
      seenPorts.add(resourceId);
      nodes.push({ id: `port:${resourceId}`, resource_type: "port", resource_id: resourceId, label: `${port.port}/${port.protocol}`, status: port.state, attributes: port });
    });
    (state.processes || []).forEach(process => nodes.push({ id: `process:${process.pid}`, resource_type: "process", resource_id: String(process.pid), label: process.process || `PID ${process.pid}`, status: process.kind, attributes: process }));
    return { nodes, edges: [], warnings: [] };
  }

  async function hydrateResourcePicker() {
    state.resourcePickerHydrated = true;
    const graph = await safe(() => cp.request("/topology"), null);
    if (!graph) { state.resourcePickerHydrated = false; return; }
    state.resourcePickerGraph = graph;
    if ($("#resource-picker").open) { renderResourcePickerTypes(); renderResourcePicker(); }
  }

  function renderResourcePickerTypes() {
    const nodes = state.resourcePickerGraph?.nodes || [];
    const counts = nodes.reduce((all, node) => ({ ...all, [node.resource_type]: (all[node.resource_type] || 0) + 1 }), {});
    $("#resource-picker-types").innerHTML = `<button class="picker-type ${state.resourcePickerType === "all" ? "active" : ""}" data-picker-type="all">All <b>${nodes.length}</b></button>` + Object.entries(counts).sort().map(([type, count]) => `<button class="picker-type ${state.resourcePickerType === type ? "active" : ""}" data-picker-type="${esc(type)}">${esc(type.replaceAll("_", " "))} <b>${count}</b></button>`).join("");
  }

  function renderResourcePicker() {
    const query = $("#resource-picker-input").value.trim().toLowerCase();
    const nodes = (state.resourcePickerGraph?.nodes || []).filter(node => {
      const matchesType = state.resourcePickerType === "all" || node.resource_type === state.resourcePickerType;
      const matchesQuery = !query || `${node.label} ${node.resource_type} ${JSON.stringify(node.attributes)}`.toLowerCase().includes(query);
      return matchesType && matchesQuery;
    }).sort((a, b) => resourcePriority(a) - resourcePriority(b) || a.label.localeCompare(b.label)).slice(0, 120);
    $("#resource-picker-results").innerHTML = nodes.length ? nodes.map(node => `<button class="palette-result" data-inspect-type="${esc(node.resource_type)}" data-inspect-id="${esc(node.resource_id)}"><span class="inspector-resource-icon" style="width:28px;height:28px;flex-basis:28px;color:${colors[node.resource_type] || "#aaa"}">${resourceIcon(node.resource_type)}</span><span><b>${esc(node.label)}</b><small>${esc(resourceContext(node))}</small></span><span class="picker-meta">${esc(node.status || node.resource_type.replaceAll("_", " "))}</span></button>`).join("") : '<div class="empty-inline">No live resource matches this filter.</div>';
  }

  function resourcePriority(node) {
    return ({ project: 1, container: 2, compose_service: 3, process: 4, port: 5, compose_project: 6 })[node.resource_type] || 20;
  }

  function resourceContext(node) {
    const attributes = node.attributes || {};
    return attributes.path || attributes.project_path || attributes.compose_project || attributes.image || (attributes.port ? `:${attributes.port}` : "") || node.resource_type.replaceAll("_", " ");
  }

  async function searchPalette() {
    const query = $("#palette-input").value.trim();
    const target = $("#palette-results");
    if (!query) { target.innerHTML = '<div class="empty-inline">Try a port, container, project, Make target, or action.</div>'; return; }
    const results = await safe(() => cp.request(`/search?q=${encodeURIComponent(query)}`), []);
    const actions = [
      { label: "Find free port", action: "free-port" },
      { label: "Open topology", action: "topology" },
      { label: "Open observability", action: "activity" },
      { label: "Open approvals", action: "approvals" },
    ].filter(item => item.label.toLowerCase().includes(query.toLowerCase()));
    target.innerHTML = `${results.map(item => `<button class="palette-result" data-inspect-type="${esc(item.resource.resource_type)}" data-inspect-id="${esc(item.resource.resource_id)}"><span class="resource-dot" style="--dot:${colors[item.resource.resource_type] || "#8fa0b2"}"></span><span><b>${esc(item.resource.label)}</b><small>${esc(item.resource.resource_type)}</small></span></button>`).join("")}${actions.map(item => `<button class="palette-result" data-palette-action="${item.action}"><span>⌘</span><span><b>${esc(item.label)}</b><small>action</small></span></button>`).join("")}` || '<div class="empty-inline">No matching local resource or action.</div>';
  }
  function openPalette() { $("#command-palette").showModal(); $("#palette-input").focus(); }
  function closePalette() { $("#command-palette").close(); }

  document.addEventListener("controlplane:view", event => {
    if (event.detail.view !== "activity") { window.clearTimeout(state.logTimer); window.clearTimeout(state.metricTimer); }
    if (event.detail.view !== "admin") window.clearTimeout(state.adminTimer);
    loadControlView(event.detail.view);
  });
  document.addEventListener("click", async event => {
    const target = event.target.closest("button, tr, g.graph-node");
    if (!target) return;
    try {
      if (target.id === "open-palette") openPalette();
      if (target.id === "resource-selector") await openResourcePicker();
      if (target.id === "close-inspector") closeInspector();
      if (target.dataset.openWorkspace) await openWorkspace(target.dataset.openWorkspace);
      if (target.dataset.focusTopology) { cp.navigate("topology"); $("#topology-project").value = target.dataset.focusTopology; await loadTopology(); }
      if (target.dataset.focusFiles) { cp.navigate("files"); await loadFiles(target.dataset.focusFiles); }
      if (target.dataset.openFile) { if (target.dataset.fileProject) await openFile(target.dataset.openFile, target.dataset.fileProject); else await openFile(target.dataset.openFile); }
      if (target.dataset.inspectType) { await openResource(target.dataset.inspectType, target.dataset.inspectId); if ($("#command-palette").open) closePalette(); }
      if (target.dataset.resourceAction) await performResourceAction(target.dataset.resourceAction, target.dataset.resourceType, target.dataset.resourceId, target.dataset.projectId, target.dataset.port);
      if (target.dataset.observeContainer) await selectContainer(target.dataset.observeContainer);
      if (target.dataset.previewPort) await openPreviewPort(target.dataset.previewPort);
      if (target.dataset.observeTab) setObserveTab(target.dataset.observeTab);
      if (target.dataset.topologyType) { const type = target.dataset.topologyType; state.topologyTypes.has(type) ? state.topologyTypes.delete(type) : state.topologyTypes.add(type); renderTopology(); }
      if (target.dataset.topologyZoom) zoomTopology(target.dataset.topologyZoom);
      if (target.id === "topology-smart-filter") await applyIntelligentTopologyFilter();
      if (target.id === "clear-smart-filter") clearIntelligentTopologyFilter();
      if (target.id === "topology-layout-toggle") {
        state.topologyLayout = state.topologyLayout === "flow" ? "radial" : "flow";
        state.topologyPositions = new Map();
        $("#topology-layout-label").textContent = state.topologyLayout === "flow" ? "Flow" : "Radial";
        renderTopology({ fit: true });
      }
      if (target.dataset.openGraphResource) await openResource(target.dataset.openGraphResource, target.dataset.resourceId);
      if (target.dataset.adminTab) setAdminTab(target.dataset.adminTab);
      if (target.dataset.pickerType) { state.resourcePickerType = target.dataset.pickerType; renderResourcePickerTypes(); renderResourcePicker(); }
      if (target.dataset.paletteAction === "topology") { closePalette(); cp.navigate("topology"); }
      if (target.dataset.paletteAction === "activity") { closePalette(); cp.navigate("activity"); }
      if (target.dataset.paletteAction === "approvals") { closePalette(); cp.navigate("approvals"); }
      if (target.dataset.paletteAction === "free-port") { closePalette(); cp.navigate("ports"); }
      if (target.id === "workspace-scan") { await cp.request("/projects/scan", { method: "POST" }); cp.toast("Configured roots scanned", "success"); await loadWorkspaces(); }
      if (target.id === "file-reload") await loadFiles(state.editor.projectId);
      if (target.id === "file-save") await saveFile();
      if (target.id === "file-revert") revertFile();
      if (target.id === "file-undo") await undoFile();
      if (target.id === "observe-pause") {
        state.observePaused = !state.observePaused;
        target.textContent = state.observePaused ? "Resume" : "Pause";
        $("#console-mode").textContent = state.observePaused ? "Output paused" : state.observeTab === "logs" ? "Polling logs every 2.5s" : "Event stream connected";
        if (!state.observePaused) { state.observeTab === "logs" ? pollContainerLogs() : renderActivity(); }
      }
      if (target.id === "observe-clear") {
        if (state.observeTab === "logs") { state.logRaw = ""; renderLogs(); }
        else { state.activity = []; renderActivity(); }
      }
      if (target.id === "copy-logs") {
        const text = state.observeTab === "logs" ? state.logRaw : $("#activity-feed").innerText;
        await navigator.clipboard.writeText(text || ""); cp.toast("Console output copied", "success");
      }
      if (target.id === "console-autoscroll") { state.autoScroll = !state.autoScroll; target.classList.toggle("active", state.autoScroll); }
      if (target.id === "preview-refresh" && state.previewUrl) { const frame = $("#preview-frame"); frame.src = "about:blank"; window.setTimeout(() => { frame.src = state.previewUrl; }, 40); }
      if (target.id === "preview-open") { if (!state.previewUrl) throw new Error("Select a preview endpoint first"); window.open(state.previewUrl, "_blank", "noopener,noreferrer"); }
    } catch (error) { cp.toast(error.message, "error"); }
  });
  $("#workspace-search")?.addEventListener("input", renderWorkspaces);
  $("#process-search")?.addEventListener("input", renderProcesses);
  $("#topology-search")?.addEventListener("input", () => {
    if (state.topologyFiltered) {
      state.topologyFiltered = null; state.topologyFilterResult = null; state.topologyFilterQuery = "";
      state.topologyPositions = new Map();
      state.topologyTypes = new Set((state.topology?.nodes || []).map(node => node.resource_type));
      updateSmartFilterStatus();
    }
    renderTopology();
  });
  $("#topology-search")?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); applyIntelligentTopologyFilter(); } });
  $("#topology-project")?.addEventListener("change", loadTopology);
  $("#file-project")?.addEventListener("change", event => loadFiles(event.target.value));
  $("#file-search")?.addEventListener("input", renderFiles);
  $("#file-editor")?.addEventListener("input", updateEditorGutter);
  $("#editor-find")?.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); findInEditor(); } });
  $("#palette-input")?.addEventListener("input", () => { window.clearTimeout(state.paletteTimer); state.paletteTimer = window.setTimeout(searchPalette, 120); });
  $("#resource-picker-input")?.addEventListener("input", renderResourcePicker);
  $("#observe-search")?.addEventListener("input", () => state.observeTab === "logs" ? renderLogs() : renderActivity());
  $("#observe-project")?.addEventListener("change", renderActivity);
  $("#log-container")?.addEventListener("change", event => { state.logContainerId = event.target.value; state.logRaw = ""; renderLogs(); if (state.logContainerId) pollContainerLogs(); });
  $("#preview-endpoint")?.addEventListener("change", event => selectPreview(event.target.value));
  $("#command-palette")?.addEventListener("click", event => { if (event.target === $("#command-palette")) closePalette(); });
  $("#resource-picker")?.addEventListener("click", event => { if (event.target === $("#resource-picker")) $("#resource-picker").close(); });
  window.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openPalette(); }
    if (event.key === "Escape" && $("#resource-inspector").classList.contains("open")) closeInspector();
    if ((location.hash.slice(1) || "overview") === "topology" && !event.target.matches("input, textarea, select")) {
      if (["+", "="].includes(event.key)) { event.preventDefault(); zoomTopology("in"); }
      if (event.key === "-") { event.preventDefault(); zoomTopology("out"); }
      if (["0", "f", "F"].includes(event.key)) { event.preventDefault(); fitTopology(); }
    }
  });

  startEvents();
  window.setTimeout(() => loadControlView(location.hash.slice(1) || "overview"), 0);
})();
