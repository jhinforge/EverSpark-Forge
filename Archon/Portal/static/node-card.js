/* Node inventory presentation; no provider provisioning logic. */
(() => {
  function bytes(value) {
    if (value == null || !Number.isFinite(Number(value)) || Number(value) < 0) return "—";
    return `${(Number(value) / 1024 ** 3).toFixed(1)} GiB`;
  }
  function render(raw, { t, bind, diagnose }) {
    const node = raw || { status: "unconfigured" };
    const panel = document.createElement("section");
    panel.className = "node-inventory";
    panel.dataset.nodeStatus = node.status;
    const labels = { joining: "Joining", online: "Online", offline: "Offline", unhealthy: "Unhealthy", removed: "Removed", unconfigured: "Not configured" };
    const heading = document.createElement("p");
    heading.className = "node-state";
    bind(heading, "Node Agent: {status}", { status: { i18nKey: labels[node.status] || "Unknown" } });
    panel.appendChild(heading);
    function field(label, value) {
      const row = document.createElement("p");
      bind(row, "{label}: {value}", { label: { i18nKey: label }, value });
      panel.appendChild(row);
    }
    if (node.node_id) field("Node ID", node.node_id);
    if (node.hostname) field("Hostname", node.hostname);
    if (node.system) field("System", [node.system.os, node.system.architecture].filter(Boolean).join(" / "));
    if (node.runtime_id) field("Runtime ID", node.runtime_id);
    if (node.last_seen) field("Last heartbeat", new Date(node.last_seen).toLocaleString());
    const messages = { unconfigured: "No Agent registration is associated with this machine. SSH deployment does not verify Node registration.",
      joining: "Waiting for Pod startup and agent registration", unhealthy: "Agent reported an unhealthy Node.",
      removed: "This Node identity has been revoked." };
    if (messages[node.status]) { const note = document.createElement("p"); bind(note, messages[node.status]); panel.appendChild(note); }
    const stages = { agent_disconnected: "Heartbeat expired", pod_stopped: "Pod stopped", join_expired_or_revoked: "Join token expired or revoked" };
    if (node.stage && stages[node.stage]) { const note = document.createElement("p"); bind(note, stages[node.stage]); panel.appendChild(note); }
    if (node.resources?.capacity) {
      const table = document.createElement("table");
      table.className = "node-resources";
      const header = document.createElement("tr");
      for (const key of ["Resource", "Capacity", "Available"]) { const th = document.createElement("th"); bind(th, key); header.appendChild(th); }
      const head = document.createElement("thead"); head.appendChild(header); table.appendChild(head);
      const body = document.createElement("tbody");
      const capacity = node.resources.capacity;
      const available = node.status === "online" ? node.resources.allocatable : null;
      function resource(label, total, free) {
        const row = document.createElement("tr");
        for (const value of [label, total, free]) { const cell = document.createElement("td"); cell.textContent = value; row.appendChild(cell); }
        body.appendChild(row);
      }
      resource("CPU", `${capacity.cpu} ${t("cores")}`, available ? `${available.cpu} ${t("cores")}` : "—");
      resource(t("Memory"), bytes(capacity.memory), bytes(available?.memory));
      resource(t("Disk"), bytes(capacity.disk), bytes(available?.disk));
      for (const [id, gpu] of Object.entries(capacity.gpu || {})) {
        const device = (node.hardware?.gpu || []).find((item) => item.id === id);
        resource(device?.name || id, bytes(gpu.vram), bytes(available?.gpu?.[id]?.vram));
      }
      table.appendChild(body); panel.appendChild(table);
    }
    if (["joining", "offline", "unhealthy"].includes(node.status) && diagnose) {
      const button = document.createElement("button"); button.type = "button"; button.className = "ghost-button";
      bind(button, "View startup diagnostics"); button.addEventListener("click", () => diagnose(button)); panel.appendChild(button);
    }
    return panel;
  }
  window.EverSparkNodeCard = { render, bytes };
})();
