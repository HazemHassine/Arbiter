/*
 * Curated Lucide icon subset, bundled locally for an offline control plane.
 * Lucide is licensed under the ISC License: https://lucide.dev/license
 */
(() => {
  const paths = {
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    archive: '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2m16 0h2M9 13v2m6-2v2"/>',
    box: '<path d="m21 8-9-5-9 5 9 5 9-5Z"/><path d="m3 8 9 5 9-5M3 8v8l9 5 9-5V8M12 13v8"/>',
    boxes: '<path d="M2.97 12.92 12 17l9.03-4.08M3 7.5 12 12l9-4.5L12 3 3 7.5Z"/><path d="M3 7.5V16l9 5 9-5V7.5M12 12v9"/>',
    brain: '<path d="M9.5 4.5A2.5 2.5 0 0 0 7 2a2.5 2.5 0 0 0-2.45 3A3.5 3.5 0 0 0 3 11.5V14a4 4 0 0 0 4 4h2.5M14.5 4.5A2.5 2.5 0 0 1 17 2a2.5 2.5 0 0 1 2.45 3A3.5 3.5 0 0 1 21 11.5V14a4 4 0 0 1-4 4h-2.5M12 4v16M8 9h4m0 6h4"/>',
    chart: '<path d="M3 3v18h18"/><path d="m7 16 4-5 4 3 5-7"/>',
    check: '<path d="m20 6-11 11-5-5"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    circleHelp: '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 1 1 5.8 1c0 2-3 2-3 4m.1 4h.01"/>',
    circlePlay: '<circle cx="12" cy="12" r="10"/><path d="m10 8 6 4-6 4Z"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6m6-16-4 20"/>',
    container: '<path d="M3 7h18M6 7v10m4-10v10m4-10v10m4-10v10M3 17h18"/><rect width="20" height="14" x="2" y="5" rx="2"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    cpu: '<rect width="16" height="16" x="4" y="4" rx="2"/><rect width="6" height="6" x="9" y="9" rx="1"/><path d="M9 1v3m6-3v3M9 20v3m6-3v3M20 9h3m-3 5h3M1 9h3m-3 5h3"/>',
    database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
    externalLink: '<path d="M15 3h6v6m0-6-9 9"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    fileCode: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2Z"/><polyline points="14 2 14 8 20 8"/><path d="m10 13-2 2 2 2m4-4 2 2-2 2"/>',
    fileText: '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2Z"/><polyline points="14 2 14 8 20 8"/><path d="M8 13h8m-8 4h8"/>',
    folder: '<path d="M3 5a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    folderCog: '<path d="M3 6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v3"/><path d="M12 20H5a2 2 0 0 1-2-2V6"/><circle cx="18" cy="17" r="3"/><path d="M18 12v2m0 6v2m-5-5h2m6 0h2"/>',
    gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    gitBranch: '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    hardDrive: '<line x1="22" x2="2" y1="12" y2="12"/><path d="m5.45 5.11-2.38 6A2 2 0 0 0 4.93 14h14.14a2 2 0 0 0 1.86-2.73l-2.38-6A2 2 0 0 0 16.69 4H7.31a2 2 0 0 0-1.86 1.11Z"/><line x1="6" x2="6.01" y1="16" y2="16"/><line x1="10" x2="10.01" y1="16" y2="16"/>',
    history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5m4-1v5l4 2"/>',
    home: '<path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10M9 20v-6h6v6"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/>',
    layers: '<path d="m12.83 2.18 8 4a2 2 0 0 1 0 3.58l-8 4a2 2 0 0 1-1.66 0l-8-4a2 2 0 0 1 0-3.58l8-4a2 2 0 0 1 1.66 0Z"/><path d="m22 12.5-9.17 4.58a2 2 0 0 1-1.66 0L2 12.5m20 5-9.17 4.58a2 2 0 0 1-1.66 0L2 17.5"/>',
    listFilter: '<path d="M3 6h18M7 12h10m-7 6h4"/>',
    maximize: '<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3m0 8v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    move: '<path d="M5 9 2 12l3 3m4-10 3-3 3 3m0 14-3 3-3-3m10-4 3-3-3-3M2 12h20M12 2v20"/>',
    network: '<rect width="6" height="6" x="9" y="2" rx="1"/><rect width="6" height="6" x="16" y="16" rx="1"/><rect width="6" height="6" x="2" y="16" rx="1"/><path d="M5 16v-3a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3M12 8v3"/>',
    orbit: '<circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(45 12 12)"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(-45 12 12)"/>',
    panelClose: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M9 3v18m6-6-3-3 3-3"/>',
    panelTop: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/>',
    pause: '<rect width="4" height="16" x="6" y="4" rx="1"/><rect width="4" height="16" x="14" y="4" rx="1"/>',
    play: '<path d="m5 3 14 9-14 9Z"/>',
    plug: '<path d="M12 22v-5m-3-9V2m6 6V2M18 8v3a6 6 0 0 1-12 0V8Z"/>',
    radio: '<path d="M4.9 19.1a10 10 0 0 1 0-14.2M7.8 16.2a6 6 0 0 1 0-8.4m8.4 0a6 6 0 0 1 0 8.4m2.9-11.3a10 10 0 0 1 0 14.2"/><circle cx="12" cy="12" r="2"/>',
    refresh: '<path d="M20 11a8.1 8.1 0 0 0-15.5-2M4 4v5h5m-5 4a8.1 8.1 0 0 0 15.5 2M20 20v-5h-5"/>',
    rotate: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h5.5a3.5 3.5 0 0 0 0-7h-5a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
    scanSearch: '<path d="M3 7V5a2 2 0 0 1 2-2h2m10 0h2a2 2 0 0 1 2 2v2m0 10v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><circle cx="11" cy="11" r="3"/><path d="m16 16-2.8-2.8"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    serverCog: '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6 6h.01M6 18h.01M14 6h4m-4 12h1"/><circle cx="19" cy="18" r="3"/>',
    settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.09a2 2 0 0 1-1-1.74v-.51a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2Z"/><circle cx="12" cy="12" r="3"/>',
    shieldCheck: '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3Z"/><path d="m9 12 2 2 4-4"/>',
    sparkles: '<path d="m12 3-1.9 5.1L5 10l5.1 1.9L12 17l1.9-5.1L19 10l-5.1-1.9ZM5 3v4M3 5h4m12 12v4m-2-2h4"/>',
    terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
    trash: '<path d="M3 6h18m-2 0-1 14H6L5 6m3 0V3h8v3m-6 4v6m4-6v6"/>',
    waypoints: '<circle cx="12" cy="4.5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M12 7v4m0 0-7 5.5m7-5.5 7 5.5"/>',
    wrench: '<path d="M14.7 6.3a4 4 0 0 0-5-5l2.1 2.1-2.8 2.8-2.1-2.1a4 4 0 0 0 5 5l7.6 7.6a2 2 0 0 0 2.8-2.8Z"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    zoomIn: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3M11 8v6m-3-3h6"/>',
    zoomOut: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3M8 11h6"/>',
  };

  const aliases = {
    admin: "panelTop", approvals: "shieldCheck", check: "shieldCheck", container: "container",
    cube: "box", file: "fileCode", history: "history", overview: "home", port: "route",
    process: "terminal", project: "folder", pulse: "activity", registry: "archive",
    settings: "settings", spark: "sparkles", topology: "network",
  };
  const resourceIcons = {
    project: "folder", compose_project: "layers", compose_service: "boxes", container: "container",
    image: "box", volume: "database", network: "network", port: "route", process: "terminal",
    dockerfile: "fileCode", compose_file: "fileCode", makefile: "wrench", make_target: "circlePlay",
    env_file: "fileText", runtime: "cpu",
  };

  function resolve(name) { return aliases[name] || name; }
  function icon(name, className = "") {
    const key = resolve(name);
    const body = paths[key] || paths.circleHelp;
    return `<svg class="lucide-icon ${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
  }
  function render(root = document) {
    root.querySelectorAll("[data-lucide]:not([data-lucide-ready])").forEach(node => {
      node.innerHTML = icon(node.dataset.lucide);
      node.setAttribute("data-lucide-ready", "true");
    });
    root.querySelectorAll("[data-icon]:not([data-lucide-ready])").forEach(node => {
      node.innerHTML = icon(node.dataset.icon);
      node.setAttribute("data-lucide-ready", "true");
    });
  }

  window.iconPack = { icon, render, resource: type => resourceIcons[type] || "circleHelp" };
  document.addEventListener("DOMContentLoaded", () => {
    render();
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      if (node.matches?.("[data-lucide], [data-icon]")) render(node.parentElement || document);
      else if (node.querySelector?.("[data-lucide], [data-icon]")) render(node);
    }))).observe(document.body, { childList: true, subtree: true });
  });
})();
