export const clone = value => JSON.parse(JSON.stringify(value));
const fullRegion = [0,0,1,1];
export function editState(state = {}) {
  const original = clone(state), r = state.recognition || {}, image = r.type==='combined' ? r.image : r.type==='image' ? r : {}, text = r.type==='combined' ? r.text : r.type==='text' ? r : {};
  const region = r.type==='combined' ? image.region || fullRegion : r.region || fullRegion;
  const ui = state.workbench || {};
  return {...clone(state), original, id:state.id || '', name:state.name || '', group:state.group || '', role:state.role || 'normal', priority:state.priority || 0,
    kind:r.type || 'image', operator:r.operator || 'and', asset:image.asset || '', texts:(text.texts || []).join('\n'), mode:text.mode || 'exact', threshold:image.threshold ?? .85,
    min_confidence:text.min_confidence ?? .8, similarity_threshold:text.similarity_threshold ?? .85, region:clone(region),
    roiEnabled:ui.roi_enabled ?? (!state.recognition || JSON.stringify(region)!==JSON.stringify(fullRegion)),
    recognitionBox:clone(ui.recognition_region || (JSON.stringify(region)!==JSON.stringify(fullRegion) ? region : [])), recognitionDirty:false,
    actions:clone(state.actions || []), conditions:{...clone(state.conditions || {}),required_states:clone(state.conditions?.required_states || []),excluded_states:clone(state.conditions?.excluded_states || [])}};
}
export function saveState(editor) {
  const old = editor.original || {}, previous = old.recognition || {};
  if(editor.kind==='combined' && editor.operator==='or' && editor.actions.some(a=>a.type==='click_match'&&a.target_box)) throw new Error('或 OR 可能只命中文字：请使用匹配中心；独立点击区请改为且 AND');
  if(editor.roiEnabled && (!editor.recognitionBox || editor.recognitionBox.length!==4 || editor.recognitionBox[2]<=editor.recognitionBox[0] || editor.recognitionBox[3]<=editor.recognitionBox[1])) throw new Error('请先框选识别区，或关闭「仅在识别区内搜索」');
  const region = editor.roiEnabled ? editor.recognitionBox : fullRegion;
  const component = kind => {
    const prior = previous.type==='combined' ? previous[kind] || {} : previous.type===kind ? previous : {};
    // Legacy combined States can have distinct regions. Preserve them until reframed or toggled.
    const keepLegacyRegion = previous.type==='combined' && JSON.stringify(previous.image.region)!==JSON.stringify(previous.text.region) && !editor.recognitionDirty && editor.roiEnabled===editState(old).roiEnabled && JSON.stringify(editor.recognitionBox)===JSON.stringify(editState(old).recognitionBox);
    const result = {...clone(prior),type:kind,region:clone(keepLegacyRegion ? prior.region || fullRegion : region)};
    if(kind==='image') {delete result.texts; Object.assign(result,{asset:editor.asset,threshold:editor.threshold});}
    else {delete result.asset; Object.assign(result,{texts:editor.texts.split('\n').map(s=>s.trim()).filter(Boolean),mode:editor.mode,min_confidence:editor.min_confidence,similarity_threshold:editor.similarity_threshold});}
    return result;
  };
  const recognition = editor.kind==='combined' ? {...(previous.type==='combined'?clone(previous):{}),type:'combined',operator:editor.operator,image:component('image'),text:component('text')} : component(editor.kind);
  return {...clone(old),id:editor.id,name:editor.name,group:editor.group,role:editor.role,priority:editor.priority,recognition,workbench:{...clone(old.workbench || {}),roi_enabled:editor.roiEnabled,recognition_region:clone(editor.recognitionBox || [])},actions:clone(editor.actions),conditions:clone(editor.conditions)};
}
export function pixelPoint(x,y,bounds,size) {return [x-bounds.left,y-bounds.top].map((value,i)=>Math.max(0,Math.min(size[i],Math.round(value*size[i]/[bounds.width,bounds.height][i]))));}
export function rectangle(a,b) {return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];}
export function normalizedRegion(box,size) {return box.map((v,i)=>v/size[i%2]);}
export function relativeTarget(box,click) {
  const width=box[2]-box[0],height=box[3]-box[1];
  if(width<=0||height<=0||click[2]<=click[0]||click[3]<=click[1]) throw new Error('识别区与点击区不能为空');
  const target=click.map((v,i)=>(v-box[i%2])/[width,height][i%2]);
  if(target.some(v=>!Number.isFinite(v)||Math.abs(v)>100)) throw new Error('点击区距离识别区过远');
  return target;
}
export async function api(path,body) {
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok) throw new Error(data.error||'请求失败'); return data;
}
export const liveStatuses=['running','pausing','paused','cancelling'];
export function conditionLabel(match) {
  return match.eligible === true ? '条件通过' : match.eligible === false ? '条件未满足' : '条件未检查（可用分组预览）';
}
