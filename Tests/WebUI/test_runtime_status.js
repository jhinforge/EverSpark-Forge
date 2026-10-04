const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
function setup(services, logging = {ready: false}) {
  const backend = {replaceChildren(...cards) {this.cards = cards;}};
  const elements = {runtimeGrid: {replaceChildren(...cards) {this.cards = cards;}}, healthDot: {}, healthTitle: {}, healthDetail: {}};
  const context = {elements, document: {querySelector: () => backend},
    api: async () => ({services, logging, ready: true}), runtimeCard: (title, online, copy) => ({title, online, copy}),
    uiText(node, text) {node.textContent = text;}, computePanelVisible: () => true,
    showNotice(error) {context.notice=error;}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function loadRuntime()'), source.indexOf('function bindEvents()')), context);
  return {context, backend, elements};
}
test('Runtime shows Archon separately and ordered Forge cards; missing logs do not block readiness', async () => {
  const {context, backend, elements} = setup({archon_backend: {online: true}, concept_forge: {online: true}, image_forge: {online: true}, audio_forge: {online: false}});
  await context.loadRuntime();
  assert.equal(backend.cards[0].title, 'Archon Backend');
  assert.deepEqual(Array.from(elements.runtimeGrid.cards, c => c.title), ['Concept Forge', 'Image Forge', 'Audio Forge']);
  assert.equal(elements.healthTitle.textContent, 'System ready');
  assert.equal(elements.healthDot.className, 'pulse-dot online');
});
test('missing service checks are explicit and server ready/log flags cannot fake a healthy system', async () => {
  const {context, elements} = setup({archon_backend: {online: true}, orchestrator: {online: true}}, {ready: true});
  await context.loadRuntime();
  assert.ok(elements.runtimeGrid.cards.every(c => !c.online && c.copy === 'Service health cannot be verified.'));
  assert.equal(elements.healthTitle.textContent, 'Archon ready');
  assert.equal(elements.healthDot.className, 'pulse-dot partial');
});
test('audio creation is available without Image; offline Archon still prevents global readiness', async () => {
  for (const online of [true, false]) {
    const {context, elements} = setup({archon_backend: {online}, concept_forge: {online: true}, audio_forge: {online: true}});
    await context.loadRuntime();
    assert.equal(elements.healthTitle.textContent, online ? 'System ready' : 'Status unavailable');
  }
});


test('a failed runtime request replaces every stale Online card with unverified and can recover', async () => {
  const {context,backend,elements}=setup(Object.fromEntries(['archon_backend','concept_forge','image_forge','audio_forge'].map(key=>[key,{online:true}])));
  const healthy=context.api;
  await context.loadRuntime();
  context.api=async()=>{throw new Error('network timeout');};
  await context.loadRuntime();
  for(const card of [...backend.cards,...elements.runtimeGrid.cards]) {
    assert.equal(card.online,null);
    assert.match(card.copy,/could not be verified/);
  }
  assert.equal(elements.healthTitle.textContent,'Status unavailable');
  assert.match(elements.healthDetail.textContent,/unverified/);
  assert.equal(elements.healthDot.className,'pulse-dot partial');
  context.api=healthy;
  await context.loadRuntime();
  assert.ok([...backend.cards,...elements.runtimeGrid.cards].every(card=>card.online));
  assert.equal(elements.healthTitle.textContent,'System ready');
});

test('unknown runtime state is distinct from Offline in the actual card DOM', () => {
  const node=()=>({children:[],dataset:{},append(...nodes){this.children.push(...nodes);}});
  const context={document:{createElement:node},uiText(node,text){node.textContent=text;}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function runtimeCard('),source.indexOf('async function loadRuntime()')),context);
  const card=context.runtimeCard('Archon Backend',null,'Request failed');
  const [title,dot,badge]=card.children[0].children;
  assert.equal(badge.textContent,'Unable to verify');
  assert.equal(dot.dataset.status,'unknown');
  assert.equal(badge.dataset.status,'unknown');
  assert.ok(!dot.className.includes('online') && !dot.className.includes('offline'));
});
