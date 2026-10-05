const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
function element(tag) {
  return {tag, dataset: {}, children: [], append(...items) {this.children.push(...items);},
    appendChild(item) {this.children.push(item);}, replaceChildren(...items) {this.children = items;}};
}
function setup(jobs) {
  const progress = element('progress'), stage = element('stage');
  stage.append(element('Concept placeholder'));
  const context = {document: {createElement: element}, elements: {creationProgress: progress},
    uiText(node, text, args = {}) {node.textContent = text.replace(/\{(\w+)\}/g, (_, key) => args[key]);},
    setTimeout: fn => fn(), t: key => key, transientApiError: () => false, states: [], renders: [],
    api: async () => {
      if (!jobs.length) throw new Error('Unexpected poll');
      return {job: jobs.shift()};
    },
    setGenerationState(...args) {context.states.push(args);},
    renderCreation(result) {stage.replaceChildren(result); context.renders.push(result);}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function renderCreationProgress('), source.indexOf('async function generate(')), context);
  return {context, progress, stage};
}

test('pure audio exposes Audio running before results and removes Concept placeholder', async () => {
  const task = {id: 'speech', forge: 'audio', status: 'running', target_node_id: 'b'.repeat(32)};
  const {context, progress, stage} = setup([{status: 'running', tasks: [task]},
    {status: 'completed', tasks: [{...task, status: 'completed'}], response: {ok: true}}]);
  await context.waitForGeneration('audio');
  assert.ok(context.states.some(([key, , args]) => key === '{forge} Forge is generating' && args.forge === 'Audio'));
  assert.equal(context.renders.length, 2);
  assert.equal(context.renders[0].tasks[0].status, 'running');
  assert.equal(stage.children[0].tasks[0].status, 'completed');
  assert.equal(progress.children[0].children[1].textContent, 'Execution node: bbbbbbbb');
  assert.equal(progress.children[0].dataset.status, 'completed');
});

test('combined generation shows both nodes and preserves completed media across audio status updates', async () => {
  const image = {id: 'image', forge: 'image', status: 'completed', target_node_id: 'a'.repeat(32), result: {outputs: []}};
  const audio = {id: 'speech', forge: 'audio', status: 'preparing', target_node_id: 'b'.repeat(32)};
  const {context, progress} = setup([
    {status: 'running', tasks: [image, audio]},
    {status: 'running', tasks: [image, {...audio, status: 'running'}]},
    {status: 'failed', error: 'Audio backend error', tasks: [image, {...audio, status: 'failed', error: '<backend detail>'}]},
  ]);
  await assert.rejects(context.waitForGeneration('combined'), /Audio backend error/);
  assert.equal(context.renders.length, 1, 'progress updates must not reload completed media');
  assert.equal(progress.children.length, 2);
  assert.equal(progress.children[0].children[1].textContent, 'Execution node: aaaaaaaa');
  assert.equal(progress.children[1].children[1].textContent, 'Execution node: bbbbbbbb');
  assert.equal(progress.children[1].dataset.status, 'failed');
  assert.equal(progress.children[1].children[3].textContent, '<backend detail>');
});

test('shared nodes remain separate tasks; waiting, preparation and skipped states are explicit', () => {
  const {context, progress} = setup([]);
  context.renderCreationProgress([
    {forge: 'image', status: 'preparing', target_node_id: 'a'.repeat(32)},
    {forge: 'audio', status: 'queued', target_node_id: 'a'.repeat(32)},
  ]);
  assert.equal(progress.children.length, 2);
  assert.equal(progress.children[0].children[2].textContent, 'Concept Forge is preparing task input');
  assert.equal(progress.children[1].children[2].textContent, 'Waiting to start');
  context.renderCreationProgress([{forge: 'audio', status: 'skipped', target_instance_id: 123}]);
  assert.equal(progress.children[0].children[1].textContent, 'Execution Pod: 123');
  assert.equal(progress.children[0].children[2].textContent, 'Not run');
  context.renderCreationProgress([]);
  assert.equal(progress.hidden, true);
});
