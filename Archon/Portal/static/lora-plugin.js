(() => {
  const base = "/api/plugins/lora/";
  const get = (id) => document.getElementById(id);
  const form = () => get("loraPluginDirectories");
  const field = (key) => form().elements.namedItem(key);
  const catalog = () => get("loraPluginCatalog");
  const i18n = window.EverSparkI18n;
  const label = (id, key, args) => i18n.bind(get(id), key, args);
  const required = ["notes_dir", "previews_dir", "thumbnails_dir", "temp_dir"];
  const checkpoint = required.map((key) => "checkpoint_" + key);
  let request;
  let navigate;
  let installed = false;
  let assetLoad;
  let assetNodes = [];
  let checking = false;
  let opening = 0;

  const post = (path, body = {}) => request(base + path, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });

  function failure(id, error) {
    label(id, error.message);
  }

  function renderStatus(data, message) {
    installed = data.installed;
    get("loraPluginNav").hidden = !installed;
    get("loraPluginInstall").disabled = checking;
    get("loraPluginUpdate").hidden = !installed;
    get("loraPluginUpdate").disabled = checking;
    label("loraPluginInstall", installed ? "Open" : "Download and install");
    label("loraPluginStatus", message || (installed ? "Installed · {version}" : "Not installed"), {version: data.version});
  }

  async function status() {
    if (checking) return;
    try {
      const data = await request(base + "status");
      if (!checking) renderStatus(data);
    } catch (error) {
      if (!checking) failure("loraPluginStatus", error);
    }
  }

  async function checkForUpdate() {
    if (checking) return;
    checking = true;
    const wasInstalled = installed;
    get("loraPluginInstall").disabled = true;
    get("loraPluginUpdate").disabled = true;
    label("loraPluginStatus", "Checking Image Model Manager version…");
    try {
      const data = await post("install");
      if (data.changed) {
        ++opening;
        assetNodes.forEach((node) => node.remove());
        assetNodes = [];
        assetLoad = null;
      }
      const message = !data.changed ? "Image Model Manager is up to date · {version}"
        : wasInstalled ? "Image Model Manager updated · {version}" : undefined;
      renderStatus(data, message);
      if (data.changed && get("loraPluginView").classList.contains("active")) await open();
    } catch (error) {
      failure("loraPluginStatus", error);
    } finally {
      checking = false;
      get("loraPluginInstall").disabled = false;
      get("loraPluginUpdate").disabled = false;
    }
  }

  function renderCredential(result) {
    get("loraPluginKey").disabled = !result.available;
    get("loraPluginKeySave").disabled = !result.available;
    get("loraPluginKeyRemove").hidden = !result.configured;
    label("loraPluginCredentialStatus", result.configured ? "Civitai API Key saved on this machine."
      : result.available ? "Optional for browsing your local catalog." : "Saving a Civitai API Key is available on Windows.");
  }

  async function loadCredential() {
    try { renderCredential(await request(base + "credential")); }
    catch (error) { failure("loraPluginCredentialStatus", error); }
  }

  function loadAssets() {
    if (!assetLoad) {
      const style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = base + "assets/panel.css";
      const script = document.createElement("script");
      script.src = base + "assets/panel.js";
      assetNodes = [style, script];
      assetLoad = Promise.all(assetNodes.map((element) => new Promise((resolve, reject) => {
        element.onload = resolve;
        element.onerror = () => reject(new Error("Could not load the model catalog."));
        document.head.append(element);
      }))).catch((error) => {
        style.remove();
        script.remove();
        if (assetNodes.includes(script)) {
          assetNodes = [];
          assetLoad = null;
        }
        throw error;
      });
    }
    return assetLoad;
  }

  async function open(forceConfiguration = false) {
    const turn = ++opening;
    const configuration = get("loraPluginConfiguration");
    get("loraPluginConfigure").hidden = true;
    get("loraPluginRefresh").hidden = true;
    configuration.hidden = true;
    catalog().hidden = true;
    label("loraPluginFeedback", "Loading model catalog…");
    try {
      const {config, can_pick_directory: canPick} = await request(base + "config");
      if (turn !== opening) return;
      for (const key of [...required, ...checkpoint, "vault_root"]) field(key).value = config[key] || "";
      document.querySelectorAll("[data-lora-pick]").forEach((button) => { button.hidden = !canPick; });
      const complete = [required, checkpoint].some((keys) => keys.every((key) => config[key]));
      configuration.hidden = complete && !forceConfiguration;
      if (!configuration.hidden) {
        label("loraPluginFeedback", "");
        get("loraPluginConfigure").hidden = !complete;
        label("loraPluginConfigure", "Back to catalog");
        void loadCredential();
        return;
      }
      get("loraPluginConfigure").hidden = false;
      get("loraPluginRefresh").hidden = false;
      label("loraPluginConfigure", "Settings");
      await loadAssets();
      if (turn !== opening) return;
      const view = document.createElement("div");
      await window.EverSparkLoraCatalog.mount(view, request);
      if (turn !== opening) return;
      catalog().replaceChildren(view);
      catalog().hidden = false;
      label("loraPluginFeedback", "");
    } catch (error) {
      if (turn === opening) failure("loraPluginFeedback", error);
    }
  }

  function init(api, setView) {
    request = api;
    navigate = setView;
    get("loraPluginInstall").onclick = () => installed ? navigate("lora") : checkForUpdate();
    get("loraPluginUpdate").onclick = checkForUpdate;
    get("loraPluginConfigure").onclick = () => open(get("loraPluginConfiguration").hidden);
    get("loraPluginRefresh").onclick = () => open();
    form().onsubmit = async (event) => {
      event.preventDefault();
      const button = event.submitter;
      if (button) button.disabled = true;
      try {
        await post("config", Object.fromEntries(new FormData(form())));
        await open();
      } catch (error) { failure("loraPluginFeedback", error); }
      finally { if (button) button.disabled = false; }
    };
    document.querySelectorAll("[data-lora-pick]").forEach((button) => {
      button.onclick = async () => {
        button.disabled = true;
        try {
          const {path} = await post("pick-directory");
          if (path) field(button.dataset.loraPick).value = path;
        } catch (error) { failure("loraPluginFeedback", error); }
        finally { button.disabled = false; }
      };
    });
    get("loraUseVault").onclick = () => {
      const root = field("vault_root").value.trim().replace(/[\\/]+$/, "");
      if (!root) { field("vault_root").focus(); return; }
      field("notes_dir").value = root + "/lora";
      field("previews_dir").value = root + "/Assets/Loras";
      field("thumbnails_dir").value = root + "/temp/lora_thumb_cache";
      field("temp_dir").value = root + "/temp/lora_plugin";
    };
    get("loraPluginCredential").onsubmit = async (event) => {
      event.preventDefault();
      const input = get("loraPluginKey");
      try {
        const result = await post("credential/save", {key: input.value});
        input.value = "";
        renderCredential(result);
      } catch (error) { failure("loraPluginCredentialStatus", error); }
    };
    get("loraPluginKeyRemove").onclick = async () => {
      try {
        const result = await post("credential/remove");
        get("loraPluginKey").value = "";
        renderCredential(result);
      } catch (error) { failure("loraPluginCredentialStatus", error); }
    };
    void status();
  }

  window.EverSparkLoraPlugin = {init, status, open};
})();
