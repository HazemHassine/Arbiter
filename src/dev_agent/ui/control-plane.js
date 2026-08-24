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
      rect.setAttribute("width", "134"); rect.setAttribute("height", "48"); rect.setAttribute("rx", "7"); rect.setAttribute("fill", "#0d0d0d"); rect.setAttribute("stroke", colors[node.resource_type] || "#8a8a8a"); group.append(rect);
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
    const known = [state.resourcePickerGraph, state.topology].filter(Boolean).flatMap(graph => graph.nodes || []).find(node => node.resource_type === type && node.resource_id === id);
    $("#inspector-type").textContent = type.replaceAll("_", " ").toUpperCase();
    $("#inspector-title").textContent = known?.label || "Loading live evidence…";
    $("#inspector-icon").textContent = resourceGlyph(type);
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
    $("#inspector-icon").textContent = resourceGlyph(detail.node.resource_type);
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
  function resourceGlyph(type) {
    return ({ project: "◇", compose_project: "◈", compose_service: "S", container: "□", image: "⬡", volume: "◉", network: "⌘", port: "⇄", process: ">_", dockerfile: "D", compose_file: "C", makefile: "M", make_target: "↗", env_file: "E", runtime: "R" })[type] || "◇";
  }
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
    $("#resource-picker-results").innerHTML = nodes.length ? nodes.map(node => `<button class="palette-result" data-inspect-type="${esc(node.resource_type)}" data-inspect-id="${esc(node.resource_id)}"><span class="inspector-resource-icon" style="width:28px;height:28px;flex-basis:28px;font-size:10px;background:${colors[node.resource_type] || "#aaa"}">${esc(resourceGlyph(node.resource_type))}</span><span><b>${esc(node.label)}</b><small>${esc(resourceContext(node))}</small></span><span class="picker-meta">${esc(node.status || node.resource_type.replaceAll("_", " "))}</span></button>`).join("") : '<div class="empty-inline">No live resource matches this filter.</div>';
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
  $("#topology-search")?.addEventListener("input", renderTopology);
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
  });

  startEvents();
  window.setTimeout(() => loadControlView(location.hash.slice(1) || "overview"), 0);
})();
