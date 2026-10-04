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
  const legacy=[];
  const buttons=primary.map(view=>({dataset:{view},classList:classes()}));
  const panels=[...primary,...legacy].map(viewPanel=>({dataset:{viewPanel},classList:classes()}));
  const assetButtons=['characters','images','audio'].map(assetTab=>({dataset:{assetTab},classList:classes(),setAttribute(key,value){this[key]=value;}}));
  const assetPanels=['characters','images','audio'].map(assetPanel=>({dataset:{assetPanel},classList:classes()}));
  const computeButtons=['machines','runtime'].map(computeTab=>({dataset:{computeTab},classList:classes(),setAttribute(key,value){this[key]=value;}}));
  const computePanels=['machines','runtime'].map(computePanel=>({dataset:{computePanel},classList:classes()}));
  const settingsButtons=['models','connections','storage'].map(settingsTab=>({dataset:{settingsTab},classList:classes(),setAttribute(key,value){this[key]=value;}}));
  const settingsPanels=['models','connections','storage'].map(settingsPanel=>({dataset:{settingsPanel},classList:classes()}));
  const nodes={'#computeView':panels.find(p=>p.dataset.viewPanel==='compute'),'#machinesView':computePanels[0],'#runtimeView':computePanels[1],'#refreshHistoryButton':{classList:classes()},'#legacyPageNavigation':{classList:classes(['hidden'])},'#returnToSectionButton':{dataset:{}},'#viewEyebrow':{},'#viewTitle':{}};
  const calls=[];
  const context={state:{assetTab:'characters',computeTab:'machines',settingsTab:'models'},$$:selector=>selector==='.nav-item'?buttons:selector==='[data-asset-tab]'?assetButtons:selector==='[data-asset-panel]'?assetPanels:selector==='[data-compute-tab]'?computeButtons:selector==='[data-compute-panel]'?computePanels:selector==='[data-settings-tab]'?settingsButtons:selector==='[data-settings-panel]'?settingsPanels:panels,$:selector=>nodes[selector],uiText(node,text){node.textContent=text;},Promise,
    nodeConnection:{refresh(){calls.push('nodeConnection');}}};
  for(const name of ['loadSubjects','loadHistory','loadRuntime','loadMachines','loadVastBalance','loadVastOffers','loadVastGpuNames','loadModelConnections','loadCloudConfiguration','loadDirectDownload']) context[name]=()=>calls.push(name);
  vm.createContext(context);vm.runInContext(copy+navigation,context);
  return {context,buttons,panels,nodes,calls,assetButtons,assetPanels,computeButtons,computePanels,settingsButtons,settingsPanels};
}
test('five primary sections display their own containers without starting unrelated loaders',()=>{
  const {context,buttons,panels,nodes,calls}=setup();
  for(const name of ['forge','assets','compute','resources','settings']) {
    context.setView(name);
    assert.deepEqual(buttons.filter(b=>b.classList.contains('active')).map(b=>b.dataset.view),[name]);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),[name]);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
  assert.deepEqual(calls,['loadSubjects','loadCloudConfiguration','nodeConnection','loadMachines','loadVastBalance','loadVastOffers','loadVastGpuNames','loadCloudConfiguration','loadDirectDownload','loadModelConnections']);
});
test('configuration shortcuts now open matching Settings tabs with original loaders',()=>{
  const cases={'machine-configuration':['connections',['nodeConnection','loadMachines']],'storage-configuration':['storage',['loadCloudConfiguration']],models:['models',['loadModelConnections']]};
  for(const [name,[tab,expected]] of Object.entries(cases)) {
    const {context,buttons,panels,nodes,calls,settingsPanels}=setup();
    context.setView(name);
    assert.deepEqual(buttons.filter(b=>b.classList.contains('active')).map(b=>b.dataset.view),['settings']);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),['settings']);
    assert.deepEqual(settingsPanels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.settingsPanel),[tab]);
    assert.deepEqual(calls,expected);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
});
test('HTML has only five page containers and all configuration shortcuts resolve through Settings',()=>{
  const html=fs.readFileSync('Archon/Portal/static/index.html','utf8');
  const nav=html.slice(html.indexOf('<nav class="nav"'),html.indexOf('</nav>'));
  assert.deepEqual([...nav.matchAll(/data-view="([^"]+)"/g)].map(m=>m[1]),['forge','assets','compute','resources','settings']);
  assert.equal([...html.matchAll(/data-primary-view/g)].length,5);
  for(const name of ['machine-configuration','storage-configuration','models']) {
    assert.ok(!html.includes(`data-view-panel="${name}"`));
  }
  assert.equal([...html.matchAll(/data-view-panel=/g)].length,5);
  assert.equal([...html.matchAll(/id="subjectCount"/g)].length,1);
});

test('Subjects and Gallery aliases open the matching asset tab without a legacy page',()=>{
  for(const [name,tab,loader] of [['subjects','characters','loadSubjects'],['history','images','loadHistory']]) {
    const {context,panels,nodes,calls,assetPanels}=setup();
    context.setView(name);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),['assets']);
    assert.deepEqual(assetPanels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.assetPanel),[tab]);
    assert.deepEqual(calls,name==='subjects'?[loader,'loadCloudConfiguration']:[loader]);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
});
test('asset tabs reuse character/media loaders and preserve the selected tab when returning',()=>{
  const {context,calls,assetPanels,assetButtons,nodes}=setup();
  context.setView('assets');
  for(const tab of ['images','audio','characters']) {
    context.setAssetTab(tab);
    assert.deepEqual(assetPanels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.assetPanel),[tab]);
    assert.equal(assetButtons.find(b=>b.dataset.assetTab===tab)['aria-selected'],'true');
    assert.equal(nodes['#refreshHistoryButton'].classList.contains('hidden'),tab==='characters');
  }
  context.setAssetTab('audio');context.setView('forge');context.setView('assets');
  assert.equal(context.state.assetTab,'audio');
  assert.deepEqual(calls,['loadSubjects','loadCloudConfiguration','loadHistory','loadHistory','loadSubjects','loadCloudConfiguration','loadHistory','loadHistory']);
});


test('Machines and Runtime aliases select compute tabs and reuse their existing loaders',()=>{
  for(const [name,expected] of [['machines',['nodeConnection','loadMachines','loadVastBalance','loadVastOffers','loadVastGpuNames']],['runtime',['loadRuntime']]]) {
    const {context,panels,nodes,calls,computePanels,computeButtons}=setup();
    context.setView(name);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),['compute']);
    assert.deepEqual(computePanels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.computePanel),[name]);
    assert.equal(computeButtons.find(b=>b.dataset.computeTab===name)['aria-selected'],'true');
    assert.deepEqual(calls,expected);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
});
test('compute tab selection persists, and polling visibility stops when leaving Compute',()=>{
  const {context,calls}=setup();
  context.setView('compute');
  assert.ok(context.computePanelVisible('machines'));
  context.setComputeTab('runtime');
  assert.ok(context.computePanelVisible('runtime'));
  assert.ok(!context.computePanelVisible('machines'));
  context.setView('forge');
  assert.ok(!context.computePanelVisible('runtime'));
  context.setView('compute');
  assert.equal(context.state.computeTab,'runtime');
  assert.ok(context.computePanelVisible('runtime'));
  const before=calls.length;
  context.setComputeTab('unknown');
  assert.equal(calls.length,before);
});
test('Compute retains operational IDs while credentials stay outside its container',()=>{
  const html=fs.readFileSync('Archon/Portal/static/index.html','utf8');
  const compute=html.slice(html.indexOf('<section class="view" id="computeView"'),html.indexOf('<section class="view" id="resourcesView"'));
  const config=html.slice(html.indexOf('<section class="view" id="settingsView"'),html.indexOf('</main>'));
  for(const id of ['machinesView','runtimeView','refreshMachines','vastBalance','forgeNodeSummary','toggleVastOffers','vastOffersPanel','vastOfferForm','vastOfferList','vastInstanceList','moreVastInstances','refreshRuntimeButton','runtimeGrid']) {
    assert.ok(compute.includes(`id="${id}"`),id);
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`,'g'))].length,1,id);
  }
  for(const id of ['vastCredentialForm','vastApiKey','saveVastKey','removeVastKey','nodeConnectionForm','nodeConnectionKey','nodeConnectionReusable','nodeConnectionStatus','nodeConnectionFeedback']) {
    assert.ok(!compute.includes(`id="${id}"`),id);
    assert.ok(config.includes(`id="${id}"`),id);
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`,'g'))].length,1,id);
  }
  assert.ok(!html.includes('data-view-panel="machines"'));
  assert.ok(!html.includes('data-view-panel="runtime"'));
});


test('Resources and the old Storage alias reuse configuration and download loaders',()=>{
  for(const name of ['resources','storage']) {
    const {context,buttons,panels,nodes,calls}=setup();
    context.setView(name);
    assert.deepEqual(panels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.viewPanel),['resources']);
    assert.deepEqual(buttons.filter(b=>b.classList.contains('active')).map(b=>b.dataset.view),['resources']);
    assert.deepEqual(calls,['loadCloudConfiguration','loadDirectDownload']);
    assert.ok(nodes['#legacyPageNavigation'].classList.contains('hidden'));
  }
});
test('Resources contains every download and remote model control, leaving configuration and backup outside',()=>{
  const html=fs.readFileSync('Archon/Portal/static/index.html','utf8');
  const resources=html.slice(html.indexOf('<section class="view" id="resourcesView"'),html.indexOf('<section class="view" id="settingsView"'));
  const config=html.slice(html.indexOf('<section class="view" id="settingsView"'),html.indexOf('</main>'));
  const ids=['modelDownloadTargets','imageDownloadForm','loraDownloadForm','vaeDownloadForm','conceptDownloadForm','directDownloadProgress','cancelDirectDownload','retryDirectDownload','storageResourceGrid','remoteCheckpointSelect','remoteDiffusionSelect','remoteLoraSelect','remoteVaeSelect','remoteConceptSelect','storageProgress','refreshStorageButton'];
  for(const id of ids) {
    assert.ok(resources.includes(`id="${id}"`),id);
    assert.ok(!config.includes(`id="${id}"`),id);
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`,'g'))].length,1,id);
  }
  for(const id of ['cloudConfigurationPanel','rcloneConfigFile','rcloneExecutable','remotePathsForm','conceptUploadPath','dataBackupPath']) {
    assert.ok(config.includes(`id="${id}"`),id);
    assert.ok(!resources.includes(`id="${id}"`),id);
  }
  assert.ok(resources.indexOf('id="imageDownloadForm"')<resources.indexOf('id="storageResourceGrid"'));
  assert.ok(resources.includes('data-cloud-storage'));
  assert.ok(config.includes('data-cloud-storage'));
  assert.ok(!html.includes('data-view-panel="storage"'));
});


test('Settings tabs retain selection and reuse configuration loaders without restarting downloads',()=>{
  const {context,calls,settingsButtons,settingsPanels}=setup();
  context.setView('settings');
  for(const name of ['connections','storage','models']) {
    context.setSettingsTab(name);
    assert.deepEqual(settingsPanels.filter(p=>p.classList.contains('active')).map(p=>p.dataset.settingsPanel),[name]);
    const selected=settingsButtons.find(b=>b.dataset.settingsTab===name);
    assert.equal(selected['aria-selected'],'true');
    assert.equal(selected.tabIndex,0);
  }
  context.setSettingsTab('storage');context.setView('forge');context.setView('settings');
  assert.equal(context.state.settingsTab,'storage');
  assert.deepEqual(calls,['loadModelConnections','nodeConnection','loadMachines','loadCloudConfiguration','loadModelConnections','loadCloudConfiguration','loadCloudConfiguration']);
});
test('Settings retains unique configuration IDs, while all backup operations belong to Assets',()=>{
  const html=fs.readFileSync('Archon/Portal/static/index.html','utf8');
  const settings=html.slice(html.indexOf('<section class="view" id="settingsView"'),html.indexOf('</main>'));
  const assets=html.slice(html.indexOf('<section class="view" id="assetsView"'),html.indexOf('<section class="view" id="computeView"'));
  for(const id of ['modelServiceList','modelServiceForm','modelServiceName','modelServiceUrl','modelServiceModel','modelServiceKey','testModelService','saveModelService','cancelModelServiceEdit','vastCredentialForm','nodeConnectionForm','cloudConfigurationPanel','cloudImportForm','rcloneExecutable','remotePathsForm']) {
    assert.ok(settings.includes(`id="${id}"`),id);
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`,'g'))].length,1,id);
  }
  for(const id of ['localDataPanel','downloadDataButton','restoreDataButton','backupPanel','backupMemory','restorePointSelect','startRestoreButton']) {
    assert.ok(!settings.includes(`id="${id}"`),id);
    assert.ok(assets.includes(`id="${id}"`),id);
  }
  assert.ok(assets.indexOf('id="backupPanel"')<assets.indexOf('id="historyView"'));
});
