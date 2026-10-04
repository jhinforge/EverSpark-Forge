/* Node inventory presentation; no provider provisioning logic. */
(() => {
  function bytes(value) {
    if (value == null || !Number.isFinite(Number(value)) || Number(value) < 0) return "—";
    return `${(Number(value) / 1024 ** 3).toFixed(1)} GiB`;
  }
  function render(raw, { t, bind, diagnose, speedtest, details: detailsContainer }) {
    const node = raw || { status: "unconfigured" };
    const panel = document.createElement("section");
    panel.className = "node-inventory";
    panel.dataset.nodeStatus = node.status;
    const labels = { joining: "Joining", online: "Online", offline: "Offline", unhealthy: "Unhealthy", removed: "Removed", unconfigured: "Not configured" };
    const heading = document.createElement("p");
    heading.className = "node-state status-badge";
    heading.dataset.status = node.status;
    bind(heading, "Node Agent: {status}", { status: { i18nKey: labels[node.status] || "Unknown" } });
    panel.appendChild(heading);
    const details = detailsContainer || document.createElement("details");
    if (!detailsContainer) {
      details.className = "ui-details";
      const summary = document.createElement("summary");
      bind(summary, "Details");
      details.appendChild(summary);
    }
    function field(label, value) {
      const row = document.createElement("p");
      bind(row, "{label}: {value}", { label: { i18nKey: label }, value });
      details.appendChild(row);
    }
    if (node.node_id) field("Node ID", node.node_id);
    if (node.hostname) field("Hostname", node.hostname);
    if (node.system) field("System", [node.system.os, node.system.architecture].filter(Boolean).join(" / "));
    if (node.runtime_id) field("Runtime ID", node.runtime_id);
    if (node.last_seen) {
      const date = document.createElement("p");
      bind(date, "{label}: {value}", { label: { i18nKey: "Last heartbeat" },
        get value() { return new Date(node.last_seen).toLocaleString(window.EverSparkI18n?.language); } });
      details.appendChild(date);
    }
    const messages = { unconfigured: "No Agent registration is associated with this machine. SSH deployment does not verify Node registration.",
      joining: "Waiting for Pod startup and agent registration", unhealthy: "Agent reported an unhealthy Node.",
      removed: "This Node identity has been revoked." };
    if (messages[node.status]) { const note = document.createElement("p"); bind(note, messages[node.status]); details.appendChild(note); }
    const stages = { agent_disconnected: "Heartbeat expired", pod_stopped: "Pod stopped", join_expired_or_revoked: "Join token expired or revoked" };
    if (node.stage && stages[node.stage]) { const note = document.createElement("p"); bind(note, stages[node.stage]); details.appendChild(note); }
    if (node.stage && !stages[node.stage]) field("Node stage", node.stage);
    const speed = node.bandwidth;
    if (speed) {
      const note = document.createElement("p");
      if (speed.status === "completed" && Number.isFinite(speed.download_mb_s)) {
        const regional = ["AS", "EU", "NA", "SA", "AF", "OC"].includes(speed.region) && speed.region === speed.server_region;
        const cloudflare = speed.method === "cloudflare_http" && speed.server_url === "https://speed.cloudflare.com/__down";
        const key = !regional && !cloudflare ? "Download speed: {speed} MB/s; region unverified, for reference only." : speed.download_mb_s >= 50
          ? "This machine downloads at {speed} MB/s, qualified."
          : "This machine downloads at {speed} MB/s; consider replacing the Pod.";
        bind(note, key, { speed: speed.download_mb_s.toFixed(2) });
        panel.appendChild(note);
        field("Test server", speed.server_name || (cloudflare ? "Cloudflare" : "LibreSpeed"));
        if (cloudflare) {
          const source = document.createElement("p");
          bind(source, "Measures downloads from Cloudflare; model sources may have different speeds.");
          panel.appendChild(source);
        }
        if (speed.server_colo) field("Cloudflare edge", speed.server_colo);
      } else {
        bind(note, speed.status === "failed" ? "Download speed test failed. Please retry." : "Testing download speed… (30-second download)");
        panel.appendChild(note);
      }
      if (speed.region) {
        const regions = {AS: "Asia", EU: "Europe", NA: "North America", SA: "South America", AF: "Africa", OC: "Oceania"};
        field("Node test region", { i18nKey: regions[speed.region] || "Unknown" });
      }
      if (speed.country) field("Node egress country", speed.country);
      if (speed.error) { const detail = document.createElement("p"); bind(detail, speed.error); details.appendChild(detail); }
      if (speed.finished_at) {
        const date = document.createElement("p");
        bind(date, "{label}: {value}", { label: { i18nKey: "Test time" },
          get value() { return new Date(speed.finished_at).toLocaleString(window.EverSparkI18n?.language); } });
        details.appendChild(date);
      }
    }
    if (node.status === "online" && speedtest) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "ghost-button";
      button.disabled = ["pending", "running"].includes(speed?.status);
      bind(button, "Retest download speed");
      button.addEventListener("click", () => speedtest(button)); panel.appendChild(button);
    }
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
        for (const value of [label, total, free]) { const cell = document.createElement("td"); bind(cell, "{value}", { value }); row.appendChild(cell); }
        body.appendChild(row);
      }
      resource("CPU", { i18nKey: "{count} cores", count: capacity.cpu }, available ? { i18nKey: "{count} cores", count: available.cpu } : "—");
      resource({ i18nKey: "Memory" }, bytes(capacity.memory), bytes(available?.memory));
      resource({ i18nKey: "Disk" }, bytes(capacity.disk), bytes(available?.disk));
      for (const [id, gpu] of Object.entries(capacity.gpu || {})) {
        const device = (node.hardware?.gpu || []).find((item) => item.id === id);
        resource(device?.name || id, bytes(gpu.vram), bytes(available?.gpu?.[id]?.vram));
      }
      table.appendChild(body); panel.appendChild(table);
    }
    if (["joining", "offline", "unhealthy"].includes(node.status) && diagnose) {
      const button = document.createElement("button"); button.type = "button"; button.className = "ghost-button";
      bind(button, "View startup diagnostics"); button.addEventListener("click", () => diagnose(button));
      // Retain the diagnostics handler without exposing a user-facing entry.
    }
    if (!detailsContainer) panel.appendChild(details);
    return panel;
  }
  window.EverSparkNodeCard = { render, bytes };
})();
