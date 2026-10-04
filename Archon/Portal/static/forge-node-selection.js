/* Manual remote endpoint choices. Selection stores EverSpark Node IDs. */
(() => {
  const roles = [
    { id: "concept", state: "forge", label: "Use for Concept Forge", selected: "Selected Concept Node" },
    { id: "image", state: "image_forge", label: "Use for Image Forge", selected: "Selected Image Node" },
    { id: "audio", state: "audio_forge", label: "Use for Audio Forge", selected: "Selected Audio Node" },
  ];
  function initialize({ api, bind, notice, changed }) {
    let selection = { bindings: {}, ready: false };
    let submitting = false;
    const summary = document.querySelector("#forgeNodeSummary");
    const downloadTargets = document.querySelector("#modelDownloadTargets");
    function show() {
      const bindings = selection.bindings || {};
      if (downloadTargets) bind(downloadTargets, "Model download targets: Image Forge → {image}; GGUF → Concept Forge {concept}. Third-party APIs do not require GGUF downloads.", {
        image: bindings.image?.slice(0, 8) || { i18nKey: "Not selected" },
        concept: bindings.concept?.slice(0, 8) || { i18nKey: "Not selected" },
      });
      const missing = roles.filter((role) => role.id !== "audio" && !bindings[role.id]);
      const message = selection.error || (selection.ready ? "Remote Concept and Image Nodes are connected. Open Creation to generate."
        : missing.length === 2 ? "Select the ready Concept and Image machines below to connect generation."
        : missing[0]?.id === "concept" ? "Select a ready Concept machine or choose an OpenAI Compatible service in Creation."
        : missing[0]?.id === "image" ? "Select a ready Image machine to complete the generation connection."
        : "Selected Nodes are unavailable. Check their connection or select replacements.");
      bind(summary, message);
    }
    async function refresh() {
      try { selection = await api("/api/forge-bindings"); show(); }
      catch (error) { bind(summary, error.message); }
    }
    function render(machine) {
      const panel = document.createElement("div");
      panel.className = "machine-actions";
      const node = machine.node;
      if (!node?.node_id) return panel;
      for (const role of roles) {
        const active = selection.bindings?.[role.id] === node.node_id;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "ghost-button";
        bind(button, active && selection.ready ? role.selected : role.label);
        button.disabled = submitting || node.status !== "online" || machine.actual_status !== "running"
          || machine[role.state]?.status !== "ready" || (active && selection.ready);
        button.addEventListener("click", async () => {
          if (submitting) return;
          submitting = true; button.disabled = true;
          let selected = false;
          try {
            selection = await api("/api/forge-bindings", { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ forge: role.id, node_id: node.node_id }) });
            show(); notice("Remote Forge Node selected.", "success");
            selected = true;
          } catch (error) { bind(summary, error.message); notice(error.message); }
          finally { submitting = false; button.disabled = false; }
          if (selected) await changed(selection);
        });
        panel.appendChild(button);
      }
      return panel;
    }
    return { refresh, render };
  }
  window.EverSparkForgeNodes = { initialize };
})();
