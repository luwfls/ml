import test from 'node:test';
import assert from 'node:assert/strict';
const model = await import('../frontend/src/model.js').catch(() => ({}));
test('editing a saved state preserves unknown fields and wait-only actions', () => {
  assert.equal(typeof model.editState, 'function');
  const state = {id:'a', name:'旧', extra:{retain:true}, recognition:{type:'text', texts:['好'], region:[.1,.2,.8,.9], custom:42}, actions:[{type:'wait',ms:123,other:true}], conditions:{required_states:['b'], excluded_states:['c'], custom:1}};
  const editor=model.editState(state); editor.name='新';
  const result=model.saveState(editor);
  assert.equal(result.name,'新'); assert.deepEqual(result.actions,state.actions); assert.deepEqual(result.extra,state.extra); assert.deepEqual(result.conditions,state.conditions); assert.equal(result.recognition.custom,42);
});
test('recognition switch excludes incompatible fields while preserving settings of active type', () => {
  assert.equal(typeof model.saveState,'function');
  const editor=model.editState({id:'a',recognition:{type:'image',asset:'a.png',threshold:.9},actions:[]}); editor.kind='text'; editor.texts='确定\n完成';
  const result=model.saveState(editor); assert.equal(result.recognition.asset,undefined); assert.deepEqual(result.recognition.texts,['确定','完成']);
});
test('action form preserves key and swipe fields, trailing waits and unknown fields', () => {
  assert.equal(typeof model.editState,'function');
  for(const action of [{type:'key',key:'home',custom:3},{type:'swipe',points:[.1,.2,.8,.9],duration_ms:789,custom:4}]) {
    const state={id:'a',recognition:{type:'image',asset:'a.png'},actions:[action,{type:'wait',ms:300},{type:'wait',ms:200}]};
    assert.deepEqual(model.saveState(model.editState(state)).actions,state.actions);
  }
});
test('pixel geometry handles reversed selection, CSS scaling and normalized ROI', () => {
  assert.equal(typeof model.pixelPoint,'function');
  assert.deepEqual(model.pixelPoint(60,45,{left:10,top:20,width:100,height:50},[1000,500]),[500,250]);
  assert.deepEqual(model.rectangle([90,80],[10,20]),[10,20,90,80]);
  assert.deepEqual(model.normalizedRegion([10,20,90,80],[100,100]),[.1,.2,.9,.8]);
});
test('independent click region maps relative to match bounds and rejects empty boxes', () => {
  assert.equal(typeof model.relativeTarget,'function');
  assert.deepEqual(model.relativeTarget([100,200,200,250],[250,150,300,175]),[1.5,-1,2,-.5]);
  assert.throws(()=>model.relativeTarget([1,1,1,2],[2,2,3,3]));
});

import {readFile} from 'node:fs/promises';
async function component(relative) {
  const source=await readFile(new URL('../frontend/src/'+relative,import.meta.url),'utf8');
  const script=source.match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace(/import (\w+) from '[^']+\.vue';/g,'const $1 = {};')
    .replace(/from '(?:\.\.\/|\.\/)model.js'/g,`from '${new URL('../frontend/src/model.js',import.meta.url)}'`);
  return (await import('data:text/javascript;base64,'+Buffer.from(script).toString('base64'))).default;
}
test('action selector changes only input and preserves all trailing waits', async()=>{
  const editor=await component('components/StateEditor.vue');
  const context={editor:{actions:[{type:'key',key:'home',custom:7},{type:'wait',ms:123,custom:8},{type:'wait',ms:456}]},inputType:'key'};
  context.inputAction=context.editor.actions[0];
  editor.methods.changeInput.call(context,'swipe');
  assert.deepEqual(context.editor.actions,[{type:'swipe',points:[.5,.8,.5,.2],duration_ms:300},{type:'wait',ms:123,custom:8},{type:'wait',ms:456}]);
  editor.methods.changeInput.call(context,'none');
  assert.deepEqual(context.editor.actions,[{type:'wait',ms:123,custom:8},{type:'wait',ms:456}]);
});
test('apply independent target crops the same recognition anchor instead of retaining old asset',async()=>{
  const app=await component('App.vue');let cropped=false;
  const action={type:'click_match'};
  const context={editor:{kind:'image',asset:'old.png',actions:[action]},selection:{recognition:[100,200,200,250],click:[250,150,300,175]},guard:fn=>fn(),cropAsset:async()=>{cropped=true;context.editor.asset='fresh.png';},$set:(object,key,value)=>object[key]=value};
  await app.methods.applyTarget.call(context);assert.equal(cropped,true);assert.equal(context.editor.asset,'fresh.png');assert.deepEqual(action.target_box,[1.5,-1,2,-.5]);
});
test('terminal ambiguous paused records are not active and cannot lock editing',async()=>{
  const panel=await component('components/RunPanel.vue');
  assert.equal(panel.computed.live.call({run:{status:'paused',live:false,reason:'ambiguous'}}),false);
  assert.equal(panel.computed.live.call({run:{status:'paused',live:true,reason:'user_paused'}}),true);
});
test('crop uses a new independent asset ID and leaves persisted state resource untouched',async()=>{
  const app=await component('App.vue'), requests=[];
  const originalFetch=globalThis.fetch;
  globalThis.fetch=async(path,options)=>{const body=JSON.parse(options.body);requests.push({path,body});return {ok:true,json:async()=>({asset:body.asset_id+'.png'})};};
  try {
    const context={editor:{id:'state-a',asset:'state-a.png',original:{recognition:{asset:'state-a.png'}}},captureId:'capture-a',selection:{recognition:[1,2,20,30]}};
    await app.methods.cropAsset.call(context);const first=context.editor.asset;
    await app.methods.cropAsset.call(context);
    assert.notEqual(context.editor.asset,first);assert.notEqual(context.editor.asset,'state-a.png');assert.equal(context.editor.original.recognition.asset,'state-a.png');
    assert.equal(requests[0].path,'/api/crop');assert.deepEqual(requests[0].body.box,[1,2,20,30]);assert.notEqual(requests[0].body.asset_id,'state-a');
  } finally {globalThis.fetch=originalFetch;}
});
test('single execution confirms input and only submits saved state ID with device',async()=>{
  const app=await component('App.vue'),requests=[];let confirmed=false;
  const originalFetch=globalThis.fetch;globalThis.fetch=async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});return {ok:true,json:async()=>({executed:true,match:{found:true}})};};
  try {
    const context={locked:false,serial:'device-a',editor:{id:'unsaved-change',original:{id:'saved-state'}},guard:fn=>fn(),$confirm:async()=>{confirmed=true;},$message:{success:()=>{},warning:()=>{}}};
    await app.methods.execute.call(context);assert.equal(confirmed,true);assert.deepEqual(requests,[{path:'/api/execute',body:{serial:'device-a',state_id:'saved-state'}}]);
  } finally {globalThis.fetch=originalFetch;}
});
test('preview without eligibility does not claim same-frame conditions passed',()=>{
  assert.equal(typeof model.conditionLabel,'function');
  assert.equal(model.conditionLabel({found:true}),'条件未检查（可用分组预览）');
  assert.equal(model.conditionLabel({eligible:false}),'条件未满足');
  assert.equal(model.conditionLabel({eligible:true}),'条件通过');
});
test('crop response cannot write old image asset into a newly opened State',async()=>{
  const app=await component('App.vue');let resolve;
  const originalFetch=globalThis.fetch;globalThis.fetch=()=>new Promise(r=>{resolve=r;});
  try {
    const a={id:'a',asset:'old-a.png'},b={id:'b',asset:'old-b.png'};
    const context={editor:a,captureId:'capture-a',selection:{recognition:[1,2,20,30]}};
    const pending=app.methods.cropAsset.call(context);context.editor=b;
    resolve({ok:true,json:async()=>({asset:'fresh-a.png'})});await pending;
    assert.equal(b.asset,'old-b.png');assert.equal(a.asset,'fresh-a.png');
  } finally {globalThis.fetch=originalFetch;}
});
test('save snapshots original draft before crop wait and does not save newly selected State',async()=>{
  const app=await component('App.vue');let finishCrop;const saved=[];
  const originalFetch=globalThis.fetch;globalThis.fetch=async(path,options)=>{const body=JSON.parse(options.body);saved.push(body);return {ok:true,json:async()=>body};};
  try {
    const a=model.editState({id:'a',recognition:{type:'image',asset:''},actions:[]}),b=model.editState({id:'b',recognition:{type:'image',asset:'b.png'},actions:[]});
    const context={editor:a,locked:false,canCrop:true,busy:false,selection:{recognition:[1,2,20,30]},captureId:'capture-a',cropAsset:editor=>new Promise(r=>{finishCrop=()=>{(editor||context.editor).asset='fresh-a.png';r();};}),reloadCatalog:async()=>{},$message:{success:()=>{}}};
    const pending=app.methods.persistState.call(context);context.editor=b;finishCrop();await pending;
    assert.equal(saved[0].id,'a');assert.equal(saved[0].recognition.asset,'fresh-a.png');assert.equal(context.editor,b);assert.equal(b.asset,'b.png');
  } finally {globalThis.fetch=originalFetch;}
});
test('double State save rejects while first request is pending and clears busy afterwards',async()=>{
  const app=await component('App.vue');let resolve;let requests=0;
  const originalFetch=globalThis.fetch;globalThis.fetch=()=>{requests++;return new Promise(r=>{resolve=r;});};
  try {
    const state={id:'a',recognition:{type:'image',asset:'a.png'},actions:[]};
    const context={editor:model.editState(state),locked:false,busy:false,canCrop:false,selection:{recognition:[]},captureId:'',reloadCatalog:async()=>{},$message:{success:()=>{}}};
    const first=app.methods.persistState.call(context);
    await assert.rejects(()=>app.methods.persistState.call(context));
    assert.equal(requests,1);resolve({ok:true,json:async()=>state});await first;assert.equal(context.busy,false);
  } finally {globalThis.fetch=originalFetch;}
});
test('late run A detail cannot overwrite selected run B',async()=>{
  const app=await component('App.vue'),resolvers={};const originalFetch=globalThis.fetch;
  globalThis.fetch=path=>new Promise(r=>resolvers[path]=r);
  try {
    const context={runId:'a',runData:null};const a=app.methods.pollDetail.call(context);context.runId='b';const b=app.methods.pollDetail.call(context);
    resolvers['/api/runs/b']({ok:true,json:async()=>({id:'b',status:'paused'})});await b;
    resolvers['/api/runs/a']({ok:true,json:async()=>({id:'a',status:'running'})});await a;
    assert.equal(context.runId,'b');assert.equal(context.runData.id,'b');
  } finally {globalThis.fetch=originalFetch;}
});
test('flow save cannot overwrite a different flow selected while request is pending',async()=>{
  const app=await component('App.vue');let resolve;const originalFetch=globalThis.fetch;
  globalThis.fetch=()=>new Promise(r=>resolve=r);
  try {
    const a={id:'a',name:'A',state_ids:[]},b={id:'b',name:'B',state_ids:[]};
    const context={flow:a,locked:false,busy:false,reloadCatalog:async()=>{}};const save=app.methods.persistFlow.call(context);context.flow=b;
    resolve({ok:true,json:async()=>({...a,name:'saved A'})});await save;assert.equal(context.flow,b);assert.equal(context.busy,false);
  } finally {globalThis.fetch=originalFetch;}
});
test('group rename updates current unsaved draft and original group without discarding edits',async()=>{
  const app=await component('App.vue');const originalFetch=globalThis.fetch;globalThis.fetch=async()=>({ok:true,json:async()=>({ok:true})});
  try {
    const context={groupFilter:'旧分组',editor:{name:'未保存名称',group:'旧分组',original:{group:'旧分组'}},guard:fn=>fn(),$prompt:async()=>({value:'新分组'}),reloadCatalog:async()=>{},$message:{success:()=>{}}};
    await app.methods.groupAction.call(context,'rename');assert.equal(context.editor.group,'新分组');assert.equal(context.editor.original.group,'新分组');assert.equal(context.editor.name,'未保存名称');
  } finally {globalThis.fetch=originalFetch;}
});
