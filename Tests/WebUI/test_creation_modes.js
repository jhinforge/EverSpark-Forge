const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
const functions = source.slice(source.indexOf('function generationSelection()'), source.indexOf('function renderImagePlugin()'));
function setup(mode) {
  const hint = {}, controls = Array.from({length: 6}, () => ({hidden: false, classList: {toggle(_name, value) {this.hidden = value;}}}));
  const selector = {value: mode};
  const elements = Object.fromEntries(['llmSelect', 'conceptProviderSelect', 'imageEngineSelect', 'workflowSelect', 'checkpointSelect', 'vaeSelect'].map(key => [key, {value: key}]));
  const context = {elements, state: {selectedLoras: [{name: 'style.safetensors'}]},
    document: {querySelector: id => id === '#creationMode' ? selector : hint, querySelectorAll: () => controls},
    uiText(node, text) {node.textContent = text;}};
  vm.createContext(context); vm.runInContext(functions, context);
  return {context, controls, hint, selector};
}
test('audio mode forwards Concept selection and hides image settings', () => {
  const {context, controls, hint} = setup('audio');
  const selection = JSON.parse(JSON.stringify(context.generationSelection()));
  assert.deepEqual(selection, {creation_mode: 'audio', llm: 'llmSelect', concept_provider: 'conceptProviderSelect'});
  context.updateCreationMode();
  assert.ok(controls.every(node => node.hidden));
  assert.match(hint.textContent, /spoken content, language and voice/);
});
test('image and combined modes retain model choices after switching from audio', () => {
  const {context, controls, selector} = setup('audio');
  context.updateCreationMode();
  for (const mode of ['image', 'image_audio']) {
    selector.value = mode;
    context.updateCreationMode();
    const selection = context.generationSelection();
    assert.equal(selection.creation_mode, mode);
    assert.equal(selection.checkpoint, 'checkpointSelect');
    assert.equal(selection.loras[0].name, 'style.safetensors');
    assert.ok(controls.every(node => !node.hidden));
  }
});
