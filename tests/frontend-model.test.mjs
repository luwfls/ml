import test from 'node:test';
import assert from 'node:assert/strict';
const model = await import('../frontend/src/model.js').catch(() => ({}));
test('new State gets a unique automatic ID and reopening keeps the saved ID',()=>{
  const a=model.editState(),b=model.editState();
  assert.match(a.id,/^[a-f0-9]{32}$/);assert.notEqual(a.id,b.id);
  assert.equal(model.editState({id:a.id}).id,a.id);
});
test('candidate rows add, update and remove without losing the other alternatives',async()=>{
  const componentDefinition=await component('components/StateEditor.vue');
  const editor=model.editState({id:'text',recognition:{type:'text',texts:['成功','完成']}});
  const context={editor};
  componentDefinition.methods.updateCandidate.call(context,1,'已完成');
  editor.texts+='\n';componentDefinition.methods.updateCandidate.call(context,2,'确认');
  componentDefinition.methods.removeCandidate.call(context,0);
  assert.deepEqual(model.saveState(editor).recognition.texts,['已完成','确认']);
});
test('F4 opens the save drawer without persisting, then saves from a focused form input',async()=>{
  const app=await component('App.vue');let opened=0,saved=0;
  const context={drawer:false,saveDrawer:false,locked:false,openState(){opened++;this.drawer=true;},saveCurrentState(){saved++;}};
  context.openSaveDrawer=()=>app.methods.openSaveDrawer.call(context);
  context.saveHotkey=()=>app.methods.saveHotkey.call(context);
  const previousDocument=globalThis.document;globalThis.document={querySelectorAll:()=>[]};
  try{
    const event={key:'F4',target:{tagName:'INPUT'},preventDefault(){}};
    app.methods.hotkey.call(context,event);
    assert.equal(opened,1);assert.equal(context.saveDrawer,true);assert.equal(saved,0);
    app.methods.hotkey.call(context,event);assert.equal(saved,1);
    app.methods.hotkey.call(context,{...event,repeat:true});assert.equal(saved,1);
    app.methods.closeStateEditor.call(context);assert.equal(context.saveDrawer,false);assert.equal(context.drawer,true);
    context.locked=true;context.openSaveDrawer();assert.equal(context.saveDrawer,false);
  }finally{globalThis.document=previousDocument;}
});
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

test('combined recognition round-trips both settings and unknown component fields',()=>{
  const state={id:'dual',recognition:{type:'combined',operator:'or',custom:7,image:{type:'image',asset:'a.png',threshold:.91,scales:[.9,1],region:[.1,.2,.8,.9]},text:{type:'text',texts:['成功','完成'],mode:'contains',min_confidence:.7,region:[.1,.2,.8,.9]}}};
  const editor=model.editState(state);
  assert.equal(editor.asset,'a.png');assert.equal(editor.texts,'成功\n完成');assert.equal(editor.operator,'or');
  const result=model.saveState(editor);
  assert.equal(result.recognition.type,'combined');assert.equal(result.recognition.custom,7);
  assert.deepEqual(result.recognition.image.scales,[.9,1]);assert.deepEqual(result.recognition.text.texts,['成功','完成']);
  assert.equal(result.recognition.image.threshold,.91);assert.equal(result.recognition.text.mode,'contains');
});
test('new State limits both recognition components to selected area by default and restores switch',()=>{
  const editor=model.editState();editor.id='new';editor.name='new';editor.kind='combined';editor.asset='a.png';editor.texts='成功\n完成';
  assert.equal(editor.roiEnabled,true);
  assert.throws(()=>model.saveState(editor),/识别区/);
  editor.recognitionBox=[.1,.2,.6,.7];
  let saved=model.saveState(editor);
  assert.deepEqual(saved.recognition.image.region,editor.recognitionBox);assert.deepEqual(saved.recognition.text.region,editor.recognitionBox);
  editor.roiEnabled=false;saved=model.saveState(editor);
  assert.deepEqual(saved.recognition.image.region,[0,0,1,1]);assert.deepEqual(saved.recognition.text.region,[0,0,1,1]);
  const restored=model.editState(saved);assert.equal(restored.roiEnabled,false);assert.deepEqual(restored.recognitionBox,[.1,.2,.6,.7]);
  restored.roiEnabled=true;restored.recognitionBox=[.2,.3,.8,.9];
  saved=model.saveState(restored);assert.deepEqual(saved.recognition.image.region,[.2,.3,.8,.9]);
});
test('legacy combined State retains separately configured search regions until explicitly reframed',()=>{
  const state={id:'legacy',recognition:{type:'combined',operator:'and',image:{asset:'a.png',region:[0,0,.5,.5]},text:{texts:['OK'],region:[.5,.5,1,1]}}};
  const saved=model.saveState(model.editState(state));
  assert.deepEqual(saved.recognition.image.region,[0,0,.5,.5]);assert.deepEqual(saved.recognition.text.region,[.5,.5,1,1]);
});
test('saving a reframed State replaces its existing image template',async()=>{
  const app=await component('App.vue'),originalFetch=globalThis.fetch;let cropped=false,saved;
  globalThis.fetch=async(path,options)=>{saved=JSON.parse(options.body);return {ok:true,json:async()=>saved};};
  try {
    const editor=model.editState({id:'a',recognition:{type:'image',asset:'old.png'}});editor.recognitionDirty=true;editor.recognitionBox=[.1,.2,.5,.6];
    const context={editor,locked:false,busy:false,canCrop:true,selection:{recognition:[10,20,50,60],click:[]},captureId:'c',cropAsset:async draft=>{cropped=true;draft.asset='new.png';},reloadCatalog:async()=>{},$message:{success:()=>{}}};
    await app.methods.persistState.call(context);assert.equal(cropped,true);assert.equal(saved.recognition.asset,'new.png');
  } finally {globalThis.fetch=originalFetch;}
});
test('restoring recognition and relative click regions draws both boxes on resized screenshot',async()=>{
  const canvas=await component('components/CaptureCanvas.vue');let selection;
  const context={size:[1000,500],recognitionBox:[.1,.2,.3,.4],targetBox:[1.5,-1,2,0],$emit:(_,value)=>selection=value,$nextTick:()=>{}};
  canvas.methods.restore.call(context);
  assert.deepEqual(selection.recognition,[100,100,300,200]);
  assert.deepEqual(selection.click,[400,0,500,100]);
});
test('legacy independent regions survive repeated save and reopen',()=>{
  let state={id:'legacy',recognition:{type:'combined',operator:'and',image:{asset:'a.png',region:[0,0,.5,.5]},text:{texts:['OK'],region:[.5,.5,1,1]}}};
  for(let i=0;i<3;i++)state=model.saveState(model.editState(state));
  assert.deepEqual(state.recognition.text.region,[.5,.5,1,1]);
});
test('combined OR cannot apply a click target anchored to a possibly missing image',()=>{
  const editor=model.editState({id:'dual',recognition:{type:'combined',operator:'or',image:{asset:'a.png'},text:{texts:['OK']}},actions:[{type:'click_match',target_box:[2,0,3,1]}]});
  assert.throws(()=>model.saveState(editor),/独立点击区/);
  editor.operator='and';assert.deepEqual(model.saveState(editor).actions[0].target_box,[2,0,3,1]);
});
test('clearing the click area removes the unsaved relative target without clearing recognition',async()=>{
  const app=await component('App.vue');const action={type:'click_match',target_box:[1,0,2,1]};
  const context={locked:false,editor:{actions:[action],recognitionBox:[.1,.2,.3,.4]},$delete:(object,key)=>delete object[key]};
  app.methods.updateSelection.call(context,{mode:'click',click:[],recognition:[10,20,30,40],size:[100,100]});
  assert.equal(action.target_box,undefined);assert.deepEqual(context.editor.recognitionBox,[.1,.2,.3,.4]);
});
