const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../Archon/Portal/static/i18n.js"), "utf8");

function setup(savedLanguage = null, browserLanguage = "zh-CN") {
  const settings = new Map(savedLanguage ? [["everspark.language", savedLanguage]] : []);
  const staticText = {
    textContent: "  Character subjects  ", nodeType: 3, isConnected: true,
    parentElement: { closest: () => null },
  };
  const dynamic = { textContent: "", isConnected: true };
  const input = { placeholder: "", isConnected: true, setAttribute(name, value) { this[name] = value; } };
  const selector = { value: "" };
  const document = {
    body: {}, documentElement: { lang: "en" },
    getElementById: () => selector,
    querySelectorAll: () => [],
    createTreeWalker: () => ({
      currentNode: null,
      nextNode() { if (this.currentNode) return false; this.currentNode = staticText; return true; },
    }),
  };
  let observerCallback;
  const context = {
    MutationObserver: class { constructor(callback) {observerCallback=callback;} observe() {} },
    window: {}, document, NodeFilter: { SHOW_TEXT: 4 }, Node: { TEXT_NODE: 3 },
    localStorage: { getItem: (key) => settings.get(key), setItem: (key, value) => settings.set(key, value) },
    navigator: { language: browserLanguage },
  };
  vm.runInNewContext(source, context);
  return { i18n: context.window.EverSparkI18n, document, staticText, dynamic, input, selector, settings,
    removed: (...nodes) => observerCallback(nodes.map(node=>({removedNodes:[node]}))) };
}

test("switches visible copy and restores English without changing names or field values", () => {
  const { i18n, document, staticText, dynamic, input, selector, settings } = setup();
  i18n.bindStatic();
  i18n.bind(dynamic, "{name}: {status}{progress}", { name: "model.gguf", status: { i18nKey: "running" }, progress: " · 10%" });
  i18n.bind(input, "Tell Concept Forge what to change in {group}", { group: { i18nKey: "Subject JSON" } }, "placeholder");
  assert.equal(staticText.textContent, "  角色主体  ");
  assert.equal(dynamic.textContent, "model.gguf：进行中 · 10%");
  assert.equal(input.placeholder, "告诉 Concept Forge 如何修改主体形象 JSON");
  assert.equal(document.documentElement.lang, "zh-CN");
  assert.equal(selector.value, "zh-CN");
  i18n.setLanguage("en");
  assert.equal(staticText.textContent, "  Character subjects  ");
  assert.equal(dynamic.textContent, "model.gguf: running · 10%");
  assert.equal(input.placeholder, "Tell Concept Forge what to change in Subject JSON");
  assert.equal(settings.get("everspark.language"), "en");
  assert.equal(i18n.t("EverSpark Forge"), "EverSpark Forge");
  assert.equal(i18n.t("identity"), "identity");
});

test("honors saved preference ahead of browser language", () => {
  const { i18n } = setup("en", "zh-CN");
  assert.equal(i18n.language, "en");
  i18n.setLanguage("zh-CN");
  assert.equal(i18n.t("Storage"), "存储");
});


test("removed subtrees release bindings without a language refresh; moved and pending nodes survive", () => {
  const {i18n, dynamic, removed} = setup("en");
  i18n.bind(dynamic, "Offline");
  const moved = {textContent:"",isConnected:true};
  const pending = {textContent:"",isConnected:false};
  i18n.bind(moved, "Online");
  i18n.bind(pending, "Ready");
  dynamic.isConnected=false;
  removed({contains: node=>node===dynamic || node===moved});
  // Reconnecting proves that the old binding was actually removed, rather than
  // merely skipped by refresh while the node was disconnected.
  dynamic.isConnected=true;pending.isConnected=true;
  i18n.setLanguage("zh-CN");
  assert.equal(dynamic.textContent,"Offline");
  assert.equal(moved.textContent,"在线");
  assert.equal(pending.textContent,"就绪");
});

test("translation keys are unique and Offline has one consistent meaning", () => {
  const keys=[...source.matchAll(/^\s*("(?:[^"\\]|\\.)*")\s*:/gm)].map(match=>JSON.parse(match[1]));
  assert.equal(new Set(keys).size,keys.length);
  const {i18n}=setup();
  assert.equal(i18n.t("Offline"),"离线");
  assert.equal(i18n.t("{value}",{value:{i18nKey:"{count} cores",count:8}}),"8 核");
});


test("Forge node selection labels use the same wording for all three roles",()=>{
  const {i18n}=setup('zh-CN');
  for(const role of ['Concept','Image','Audio']) {
    assert.equal(i18n.t(`Use for ${role} Forge`),`选为 ${role} 节点`);
    assert.equal(i18n.t(`Selected ${role} Node`),`当前 ${role} 节点`);
  }
});
