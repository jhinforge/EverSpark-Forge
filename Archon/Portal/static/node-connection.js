/* Local WebUI bootstrap setup. Keys are never returned by the backend. */
(() => {
  function initialize({ api, bind, notice }) {
    const form = document.querySelector("#nodeConnectionForm");
    const input = document.querySelector("#nodeConnectionKey");
    const status = document.querySelector("#nodeConnectionStatus");
    async function refresh() {
      try {
        const data = await api("/api/machines/vast/node-connection");
        bind(status, data.ready ? "Automatic Node connection is ready for the next rental." : "Enter a fresh Tailscale auth key before renting an automatic Node.");
      } catch (error) { status.textContent = error.message; }
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button"); button.disabled = true;
      try {
        await api("/api/machines/vast/node-connection", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: input.value.trim() }) });
        input.value = ""; await refresh(); notice("Automatic Node connection configured.", "success");
      } catch (error) { notice(error.message); }
      finally { button.disabled = false; }
    });
    return { refresh };
  }
  window.EverSparkNodeConnection = { initialize };
})();
