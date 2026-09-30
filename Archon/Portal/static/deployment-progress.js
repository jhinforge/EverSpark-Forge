(() => {
  const labels = {queued: "Waiting for execution", executing: "Executing",
    initializing: "Initializing environment", installing_runtime: "Installing runtime and dependencies",
    downloading_models: "Downloading models", importing_model: "Importing Concept model",
    starting_service: "Starting Image service", checking_health: "Checking service health",
    health: "Checking service health", revision: "Reading source revision",
    deploy: "Waiting for deployment progress", concept_health: "Checking Concept service",
    read_revision: "Reading source revision"};
  function t(key, args = {}) {
    if (window.EverSparkI18n) return window.EverSparkI18n.t(key, args);
    return key.replace(/\{(\w+)\}/g, (_, name) => args[name] ?? "");
  }
  function format(job) {
    const value = job.progress;
    const phase = value?.stage || job.stage || "queued";
    const seconds = value ? ` · ${t("Current phase: {seconds} seconds", {seconds: Math.floor(value.elapsed_seconds)})}` : "";
    return `${t(labels[phase] || phase)}${seconds}${value?.stale ? ` · ${t("Heartbeat interrupted; waiting for recovery")}` : ""}`;
  }
  function failure(job) {
    const code = job.exit_code == null ? "" : ` · ${t("Exit code: {code}", {code: job.exit_code})}`;
    return `${format(job)}${code}: ${job.detail || t("No error output")}`;
  }
  window.EverSparkDeploymentProgress = {format, failure};
})();
