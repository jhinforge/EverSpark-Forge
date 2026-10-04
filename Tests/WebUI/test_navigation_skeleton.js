const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Archon/Portal/static/app.js','utf8');
const copy = source.slice(source.indexOf('const viewCopy ='),source.indexOf('async function api('));
const navigation = source.slice(source.indexOf('const legacyViewSections ='),source.indexOf('function machineMessage('));
function setup() {
  const classes = (initial=[]) => {const values=new Set(initial);return {toggle(key,on){on?values.add(key):values.delete(key);},contains(key){return values.has(key);}};};
  const primary=['forge','assets','compute','resources','settings'];
  const legacy=['subjects','history','machines','runtime','storage','models'];
  const buttons=primary.map(view=>({dataset:{view},classList:classes()}));
  const panels=[...primary,...legacy].map(viewPanel=>({dataset:{viewPanel},classList:classes()}));
  const nodes={'#legacyPageNavigation':{classList:classes(['hidden'])},'#returnToSectionButton':{dataset:{}},'#viewEyebrow':{},'#viewTitle':{}};
  const calls=[];
  const context={$$:selector=>selector==='.nav-item'?buttons:panels,$:selector=>nodes[selector],uiText(node,text){node.textContent=text;},Promise,
    nodeConnection:{refresh(){calls.push('nodeConnection');}}};
  for(const name of ['loadHistory','loadRuntime','loadMachines','loadVastBalance','loadVastOffers','loadVastGpuNames','loadModelConnections','loadCloudConfiguration','loadDirectDownload']) context[name]=()=>calls.push(name);
  vm.createContext(context);vm.runInContext(copy+navigation,context);
  return {context,buttons,panels,nodes,calls};
}
test('five primary sections display their own containers without starting legacy loaders',()=>{
  const {context,buttons,panels,nodes,calls}=setup();
  for(const name of ['forge','assets','compute','resources','settings']) {
    context.setView(name);
    assert.deepEqual(buttons.filter(b=>b.classList.contains('active')).map(b=>b.dataset.view),[name]);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),[name]);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
  assert.deepEqual(calls,[]);
});
test('legacy shortcuts retain page loaders, parent highlighting and a return target',()=>{
  const cases={subjects:['assets',[]],history:['assets',['loadHistory']],machines:['compute',['nodeConnection','loadMachines','loadVastBalance','loadVastOffers','loadVastGpuNames']],runtime:['compute',['loadRuntime']],storage:['resources',['loadCloudConfiguration','loadDirectDownload']],models:['settings',['loadModelConnections']]};
  for(const [name,[parent,expected]] of Object.entries(cases)) {
    const {context,buttons,panels,nodes,calls}=setup();
    context.setView(name);
    assert.deepEqual(buttons.filter(b=>b.classList.contains('active')).map(b=>b.dataset.view),[parent]);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),[name]);
    assert.deepEqual(calls,expected);
    assert.equal(nodes['#returnToSectionButton'].dataset.viewLink,parent);
    assert.ok(!nodes['#legacyPageNavigation'].classList.contains('hidden'));
    context.setView(nodes['#returnToSectionButton'].dataset.viewLink);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
});
test('HTML keeps five primary entries and every old page accessible',()=>{
  const html=fs.readFileSync('Archon/Portal/static/index.html','utf8');
  const nav=html.slice(html.indexOf('<nav class="nav"'),html.indexOf('</nav>'));
  assert.deepEqual([...nav.matchAll(/data-view="([^"]+)"/g)].map(m=>m[1]),['forge','assets','compute','resources','settings']);
  assert.equal([...html.matchAll(/data-primary-view/g)].length,5);
  for(const name of ['subjects','history','machines','runtime','storage','models']) {
    assert.ok(html.includes(`data-view-panel="${name}"`));
    assert.ok(html.includes(`data-view-link="${name}"`));
  }
  assert.equal([...html.matchAll(/id="subjectCount"/g)].length,1);
});
