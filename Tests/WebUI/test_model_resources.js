const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
function setup() {
  const select = value => ({value, disabled: false, replaceChildren() {this.value = '';}});
  const elements = {imageEngineSelect: select('comfyui'), workflowSelect: select('old-workflow'),
    checkpointSelect: select('old.safetensors'), vaeSelect: select('old-vae.safetensors'),
    loraSelect: select('old-lora.safetensors'), conceptProviderSelect: select('api_test'),
    llmSelect: select('custom-model'), addLoraButton: {disabled: false}};
  const context = {elements, encodeURIComponent, Set, t: x => x, showNotice(message) {throw new Error(message);},
    state: {imagePlugins: [{id: 'comfyui', online: true}], selectedLoras: [{name: 'old-lora.safetensors'}, {name: 'keep.safetensors'}]},
    renderSelectedLoras() {}, updateLoraAvailability() {}, updateCreationSettingsSummary() {},
    fillSelect(el, items, key, label, preferred) {
      const values = items.map(key);
      el.value = values.includes(preferred) ? preferred : values[0] || '';
    }};
  context.api = async () => ({workflows: [{id: 'new-workflow', name: 'New'}], checkpoints: ['new.safetensors'],
    vaes: ['new-vae.safetensors'], loras: ['keep.safetensors'], defaults: {workflow: 'new-workflow',
      checkpoint: 'new.safetensors', concept_provider: 'ollama'}, concept_providers: [{id: 'ollama'}, {id: 'api_test'}],
    concept_models: {api_test: ['custom-model']}});
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function updateConceptModels()'), source.indexOf('function fillRemoteSelect(')), context);
  return context;
}
test('resource refresh replaces unavailable image selections and prunes old LoRAs while preserving selected API', async () => {
  const context = setup();
  await context.loadResources();
  assert.equal(context.elements.checkpointSelect.value, 'new.safetensors');
  assert.equal(context.elements.workflowSelect.value, 'new-workflow');
  assert.equal(context.elements.vaeSelect.value, '');
  assert.equal(context.state.selectedLoras.length, 1);
  assert.equal(context.state.selectedLoras[0].name, 'keep.safetensors');
  assert.equal(context.elements.conceptProviderSelect.value, 'api_test');
  assert.equal(context.elements.llmSelect.value, 'custom-model');
});
test('offline image plugin does not prevent third-party model resources from refreshing', async () => {
  const context = setup();
  context.state.imagePlugins[0].online = false;
  await context.loadResources();
  assert.equal(context.elements.conceptProviderSelect.disabled, false);
  assert.equal(context.elements.llmSelect.value, 'custom-model');
});
