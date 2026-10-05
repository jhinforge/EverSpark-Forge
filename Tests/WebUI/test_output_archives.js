const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js', 'utf8');
function setup(api) {
  const clicks = [], notices = [];
  const elements = {downloadOutputsButton: {}, downloadAudioOutputsButton: {}};
  const context = {elements, state: {}, api, URL, URLSearchParams, Date,
    window: {location: new URL('http://localhost:8780/'), setTimeout: resolve => resolve()},
    document: {body: {appendChild() {}}, createElement: () => ({click() {clicks.push(this.href);}, remove() {}})},
    hideNotice() {}, showNotice: message => notices.push(message), uiText: (el, text) => el.textContent = text};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function downloadOutputsArchive('), source.indexOf('async function downloadDataArchive(')), context);
  return {context, clicks, notices};
}

test('image and audio ZIPs poll independent jobs and download directly from their own nodes', async () => {
  const calls = [];
  const {context, clicks, notices} = setup(async path => {
    const query = new URL(path, 'http://localhost').searchParams;
    const forge = query.get('forge'); calls.push([forge, query.get('job_id')]);
    if (!query.get('job_id')) return {status: 'preparing', job_id: forge + '-job'};
    return {status: 'ready', url: `http://100.64.0.${forge === 'audio' ? 2 : 1}:9000/archive?signature=fixture`};
  });
  await Promise.all([context.downloadOutputsArchive('image'), context.downloadOutputsArchive('audio')]);
  assert.equal(clicks.length, 2);
  assert.ok(clicks.some(url => url.includes('100.64.0.1')));
  assert.ok(clicks.some(url => url.includes('100.64.0.2')));
  assert.equal(calls.length, 4);
  assert.deepEqual(notices, []);
  assert.equal(context.elements.downloadAudioOutputsButton.disabled, false);
  assert.equal(context.elements.downloadOutputsButton.textContent, 'Download images ZIP');
});

test('failed packaging restores retry controls and never downloads an error payload', async () => {
  const {context, clicks, notices} = setup(async () => ({status: 'failed', error: 'No outputs available'}));
  await context.downloadOutputsArchive('audio');
  assert.equal(clicks.length, 0);
  assert.deepEqual(notices, ['No outputs available']);
  assert.equal(context.state.outputArchiveBusy.audio, false);
  assert.equal(context.elements.downloadAudioOutputsButton.disabled, false);
});

test('duplicate click stays disabled until preparation completes', async () => {
  let release;
  const {context, clicks} = setup(() => new Promise(resolve => release = resolve));
  const running = context.downloadOutputsArchive('image');
  await context.downloadOutputsArchive('image');
  assert.equal(context.elements.downloadOutputsButton.disabled, true);
  release({status: 'ready', url: 'http://100.64.0.1:9000/archive?signature=fixture'});
  await running;
  assert.equal(clicks.length, 1);
});

test('untrusted archive URLs cannot trigger browser navigation', async () => {
  for (const url of ['https://example.com/archive', 'javascript:alert(1)', 'http://user:pass@100.64.0.1/archive']) {
    const {context, clicks, notices} = setup(async () => ({status: 'ready', url}));
    await context.downloadOutputsArchive('image');
    assert.equal(clicks.length, 0);
    assert.equal(notices.length, 1);
  }
});
