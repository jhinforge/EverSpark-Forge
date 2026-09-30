/* Local bootstrap setup with inline feedback and bounded, repeatable requests. */
(() => {
  function initialize({ api, bind, notice }) {
    const form = document.querySelector("#nodeConnectionForm");
    const input = document.querySelector("#nodeConnectionKey");
    const reusable = document.querySelector("#nodeConnectionReusable");
    const status = document.querySelector("#nodeConnectionStatus");
    const feedback = document.querySelector("#nodeConnectionFeedback");
    const button = form.querySelector("button");
    let submitting = false;
    let generation = 0;
    const explain = (message, error = false) => {
      bind(feedback, message);
      feedback.classList.toggle("node-connection-error", error);
    };
    async function request(options = {}) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      try {
        return await api("/api/machines/vast/node-connection", { ...options, signal: controller.signal });
      } catch (error) {
        if (error.name === "AbortError") throw new Error("Node connection request timed out. You can retry.");
        throw error;
      } finally { clearTimeout(timer); }
    }
    function showStatus(data) {
      bind(status, data.ready ? (data.reusable ? "Reusable Node connection is ready for additional rentals." : "Automatic Node connection is ready for the next rental.")
        : "Enter a fresh Tailscale auth key before renting an automatic Node.");
    }
    async function refresh() {
      const current = ++generation;
      try {
        const data = await request();
        if (current === generation && !submitting) showStatus(data);
      } catch (error) {
        if (current === generation && !submitting) bind(status, error.message);
      }
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submitting) return;
      const key = input.value.trim();
      if (!key) { explain("Enter a valid Tailscale auth key", true); return; }
      submitting = true; ++generation; button.disabled = true;
      bind(button, "Configuring connection…"); explain("Configuring connection…");
      try {
        const data = await request({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, reusable: reusable.value === "reusable" }) });
        if (!data.ready) throw new Error("Automatic Node connection is not ready. Check Tailscale on this host.");
        input.value = ""; showStatus(data); explain("Automatic Node connection configured.");
        notice("Automatic Node connection configured.", "success");
      } catch (error) { explain(error.message, true); notice(error.message); }
      finally { submitting = false; button.disabled = false; bind(button, "Configure automatic connection"); }
    });
    return { refresh };
  }
  window.EverSparkNodeConnection = { initialize };
})();
