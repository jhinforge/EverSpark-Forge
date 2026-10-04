const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
const functions = source.slice(source.indexOf('function generationSelection()'), source.indexOf('function renderImagePlugin()'));
function setup(mode) {
  const node = () => ({dataset: {}, hidden: false, classList: {toggle(name, value) {this[name] = value;}},
    setAttribute(name, value) {this[name] = value;}});
  const hint = node(), summary = node(), controls = Array.from({length: 6}, node);
  const radios = ['image', 'audio', 'image_audio'].map(value => ({value, checked: false}));
  const selector = {value: mode};
  const elements = Object.fromEntries(['llmSelect', 'conceptProviderSelect', 'imageEngineSelect', 'workflowSelect', 'checkpointSelect', 'vaeSelect'].map(key => [key, {value: key}]));
  Object.assign(elements, {discussModeButton: node(), generateModeButton: node(), conversationFeed: {...node(), content: 'retained discussion'},
    scenePrompt: {...node(), value: 'unfinished request'}, generateButton: {firstElementChild: node()}});
  const nodes = {'#creationMode': selector, '#creationModeHint': hint, '#creationSettingsSummary': summary,
    '#forgeView .canvas-panel': node(), '#creationTaskTypes': node(), '#creationWorkspaceTitle': node(), '#creationPromptLabel': node()};
  const context = {elements, state: {mode: 'generate', selectedLoras: [{name: 'style.safetensors'}]},
    document: {querySelector: id => nodes[id], querySelectorAll: query => query === '[data-image-control]' ? controls : radios},
    uiText(node, text, args = {}) {node.textContent = text.replace(/\{(\w+)\}/g, (_, key) => args[key] ?? key);},
    uiAttr(node, key, value) {node.setAttribute(key, value);}};
  vm.createContext(context); vm.runInContext(functions, context);
  vm.runInContext(source.slice(source.indexOf('function setMode(mode)'), source.indexOf('async function discuss()')), context);
  return {context, controls, hint, selector, summary, radios, nodes};
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

test('top-level work modes preserve the draft, discussion, task type and resource choices', () => {
  const {context, selector, nodes, summary} = setup('image_audio');
  context.setMode('discuss');
  assert.equal(nodes['#creationTaskTypes'].hidden, true);
  assert.equal(context.elements.conversationFeed.hidden, false);
  assert.equal(context.elements.discussModeButton['aria-pressed'], 'true');
  assert.equal(nodes['#creationWorkspaceTitle'].textContent, 'Discuss');
  assert.doesNotMatch(summary.textContent, /Checkpoint/);
  context.setMode('generate');
  assert.equal(nodes['#creationTaskTypes'].hidden, false);
  assert.equal(context.elements.conversationFeed.hidden, true);
  assert.equal(context.elements.generateModeButton['aria-pressed'], 'true');
  assert.equal(context.elements.generateButton.firstElementChild.textContent, 'Generate');
  assert.equal(context.elements.scenePrompt.value, 'unfinished request');
  assert.equal(context.elements.conversationFeed.content, 'retained discussion');
  assert.equal(selector.value, 'image_audio');
  assert.equal(context.generationSelection().loras[0].name, 'style.safetensors');
});

test('task radios bridge the original change event and keep the request and summary in sync', () => {
  const {context, selector, radios, summary} = setup('image');
  radios.forEach(input => {input.addEventListener = (_, callback) => {input.change = callback;};});
  context.Event = Event;
  selector.dispatchEvent = event => {assert.equal(event.type, 'change'); context.updateCreationMode();};
  const start = source.indexOf('  document.querySelectorAll(\'input[name="creationTask"]\').forEach((input) => {', source.indexOf('function bindEvents()'));
  const end = source.indexOf('  [elements.checkpointSelect', start);
  vm.runInContext(source.slice(start, end), context);
  for (const mode of ['audio', 'image_audio', 'image']) {
    radios.find(input => input.value === mode).checked = true;
    radios.find(input => input.value === mode).change();
    assert.equal(selector.value, mode);
    assert.equal(context.generationSelection().creation_mode, mode);
    assert.deepEqual(radios.filter(input => input.checked).map(input => input.value), [mode]);
    assert.equal(summary.textContent.includes('Checkpoint'), mode !== 'audio');
  }
  context.state.selectedLoras.push({name: 'second.safetensors'});
  context.updateCreationSettingsSummary();
  assert.match(summary.textContent, /LoRA: 2/);
});
