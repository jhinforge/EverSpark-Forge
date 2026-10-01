(() => {
  const labels = {queued: "Waiting for execution", executing: "Executing",
    initializing: "Initializing environment", installing_runtime: "Installing runtime and dependencies",
    installing_system_dependencies: "Installing system dependencies",
    downloading_concept_runtime: "Downloading Ollama runtime",
    downloading_image_runtime: "Downloading ComfyUI source",
    installing_python_dependencies: "Preparing Python environment",
    installing_torch: "Downloading and installing PyTorch",
    installing_image_dependencies: "Downloading and installing Image dependencies",
    installing_model_dependencies: "Installing model download dependencies",
    checking_runtime: "Checking runtime compatibility",
    starting_concept_service: "Starting Concept service",
    recovering: "Recovering previous task result",
    recovery_unknown: "Previous task outcome unknown",
    outcome_unknown: "Previous task outcome unknown",
    archon_restart: "Host restarted during task",
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
    const count = phase === "downloading_models" && Number.isInteger(value?.completed) && Number.isInteger(value?.total)
      ? ` · ${t("Models ready: {completed}/{total}", {completed: value.completed, total: value.total})}` : "";
    return `${t(labels[phase] || phase)}${count}${seconds}${value?.stale ? ` · ${t("Heartbeat interrupted; waiting for recovery")}` : ""}`;
  }
  function failure(job) {
    const code = job.exit_code == null ? "" : ` · ${t("Exit code: {code}", {code: job.exit_code})}`;
    return `${format(job)}${code}: ${job.detail || t("No error output")}`;
  }
  window.EverSparkDeploymentProgress = {format, failure};
})();
