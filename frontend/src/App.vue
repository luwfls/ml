<template>
  <main>
    <h1>安卓 State 自动化工作台</h1>
    <p>选择设备、截图制作图片或文字 State，再运行有限循环。OCR：{{ ocrReady ? 'RapidOCR 已启用' : '未启用（仅图片模式）' }}。</p>
    <el-alert v-if="error" :title="error" type="error" @close="error = ''" />
    <el-card>
      <el-select v-model="serial" placeholder="选择 ADB 设备">
        <el-option v-for="d in devices" :key="d.serial" :label="d.serial + ' · ' + d.status" :value="d.serial" :disabled="d.status !== 'device'" />
      </el-select>
      <el-button @click="refreshDevices">刷新设备</el-button>
      <el-button type="primary" :disabled="!serial || running" @click="capture">设备截图</el-button>
      <input type="file" accept="image/png" @change="importImage" />
      <p>在截图上拖动框选。坐标按原始截图像素保存；导入图片可用于离线制作和预览。</p>
      <canvas ref="canvas" @mousedown="beginSelection" @mouseup="endSelection" />
      <p v-if="box.length">框选区域：{{ box.join(', ') }}</p>
    </el-card>
    <div class="columns">
      <el-card>
        <h2>State 编辑</h2>
        <el-form label-width="80px">
          <el-form-item label="ID"><el-input v-model="editor.id" placeholder="例如 receive-success" /></el-form-item>
          <el-form-item label="名称"><el-input v-model="editor.name" /></el-form-item>
          <el-form-item label="角色"><el-select v-model="editor.role"><el-option v-for="role in roles" :key="role.value" :label="role.label" :value="role.value" /></el-select></el-form-item>
          <el-form-item label="识别"><el-radio-group v-model="recognitionType"><el-radio label="image">图片</el-radio><el-radio label="text">文字</el-radio></el-radio-group></el-form-item>
          <template v-if="recognitionType === 'image'">
            <el-form-item label="资源"><el-input v-model="asset" /><el-button :disabled="!box.length || !captureId || running" @click="crop">保存框选图片</el-button></el-form-item>
          </template>
          <template v-else>
            <el-form-item label="文案"><el-input v-model="texts" type="textarea" placeholder="每行一个候选文案，任一命中即识别成功" /></el-form-item>
            <el-form-item label="模式"><el-select v-model="textMode"><el-option v-for="m in ['exact', 'contains', 'fuzzy']" :key="m" :value="m" :label="m" /></el-select></el-form-item>
          </template>
          <el-form-item label="优先级"><el-input-number v-model="editor.priority" :min="-10000" :max="10000" /></el-form-item>
          <el-form-item label="动作"><el-input v-model="actions" type="textarea" :rows="3" /><small>[] 只识别；点击需显式填写 [{"type":"click_match"}]。</small></el-form-item>
        </el-form>
        <el-button type="primary" :disabled="running" @click="saveState">保存 State</el-button>
        <el-button :disabled="!captureId || (recognitionType === 'text' && !ocrReady)" @click="preview">识别预览</el-button>
        <pre v-if="probe">{{ JSON.stringify(probe, null, 2) }}</pre>
      </el-card>
      <el-card>
        <h2>State 与流程</h2>
        <el-checkbox-group v-model="selected"><p v-for="s in states" :key="s.id"><el-checkbox :label="s.id">{{ s.name }} · {{ s.role }} · {{ s.recognition.type }}</el-checkbox><el-button size="mini" @click="editState(s)">编辑</el-button></p></el-checkbox-group>
        <el-form label-width="100px">
          <el-form-item label="最多轮数"><el-input-number v-model="flow.max_rounds" :min="1" :max="10000" /></el-form-item>
          <el-form-item label="超时（秒）"><el-input-number v-model="flow.timeout_seconds" :min="1" :max="3600" /></el-form-item>
          <el-form-item label="轮间等待 ms"><el-input-number v-model="flow.poll_ms" :min="0" :max="10000" /></el-form-item>
          <el-form-item label="完成次数"><el-input-number v-model="flow.completion_count" :min="1" :max="1000" /></el-form-item>
          <el-form-item label="只识别"><el-switch v-model="flow.dry_run" /></el-form-item>
        </el-form>
        <el-button :disabled="running" @click="saveFlow">保存流程</el-button>
        <el-button type="primary" :disabled="!serial || running" @click="run">运行流程</el-button>
        <el-button type="danger" :disabled="!running" @click="cancel">停止</el-button>
        <p v-if="runData">状态：{{ runData.status }} · {{ runData.reason || '' }} <strong v-if="runData.dry_run">（仅识别，未发送输入）</strong></p>
        <pre v-if="runData">{{ JSON.stringify(runData.events || [], null, 2) }}</pre>
      </el-card>
    </div>
  </main>
</template>

<script>
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

export default {
  data: () => ({devices: [], serial: '', error: '', ocrReady: false, states: [], selected: [], captureId: '', image: null, start: null, box: [],
    editor: {id: '', name: '', role: 'normal', priority: 0}, recognitionType: 'image', asset: '', texts: '', textMode: 'exact', actions: '[]', extras: {}, probe: null,
    roles: [{value: 'normal', label: '普通'}, {value: 'success', label: '成功断言'}, {value: 'failure', label: '失败断言'}, {value: 'fallback', label: '兜底（须命中）'}],
    flow: {max_rounds: 200, timeout_seconds: 300, poll_ms: 1000, completion_count: 1, dry_run: true}, runData: null, runId: '', timer: null}),
  computed: {running() {return this.runData && this.runData.status === 'running';}},
  mounted() {this.guard(async () => {this.ocrReady = (await api('/api/health')).ocr === 'ready'; this.states = await api('/api/states'); const f = await api('/api/flow'); if (f) {this.flow = f; this.selected = f.state_ids;} });},
  beforeDestroy() {clearInterval(this.timer);},
  methods: {
    async guard(fn) {this.error = ''; try {await fn();} catch (e) {this.error = e.message;}},
    refreshDevices() {this.guard(async () => {this.devices = await api('/api/devices');});},
    capture() {this.guard(async () => {const c = await api('/api/capture', {serial: this.serial}); this.captureId = c.id; this.loadImage(c.url);});},
    importImage(event) {this.guard(async () => {const file = event.target.files[0]; if (!file) return; const raw = new Uint8Array(await file.arrayBuffer()); let binary = ''; for (const byte of raw) binary += String.fromCharCode(byte); const c = await api('/api/import', {png: btoa(binary)}); this.captureId = c.id; this.loadImage(c.url);});},
    loadImage(url) {this.box = []; const image = new Image(); image.onload = () => {this.image = image; this.draw();}; image.onerror = () => {this.error = '截图加载失败';}; image.src = url;},
    draw() {const canvas = this.$refs.canvas; if (!this.image) return; canvas.width = this.image.width; canvas.height = this.image.height; const ctx = canvas.getContext('2d'); ctx.drawImage(this.image, 0, 0); if (this.box.length) {ctx.strokeStyle = '#e65c33'; ctx.lineWidth = 2; ctx.strokeRect(this.box[0], this.box[1], this.box[2] - this.box[0], this.box[3] - this.box[1]);}},
    point(event) {const canvas = this.$refs.canvas, r = canvas.getBoundingClientRect(); return [Math.max(0, Math.min(canvas.width, Math.round((event.clientX-r.left)*canvas.width/r.width))), Math.max(0, Math.min(canvas.height, Math.round((event.clientY-r.top)*canvas.height/r.height)))];},
    beginSelection(e) {if (this.image) this.start = this.point(e);},
    endSelection(e) {if (!this.start) return; const p = this.point(e); this.box = [Math.min(p[0], this.start[0]), Math.min(p[1], this.start[1]), Math.max(p[0], this.start[0]), Math.max(p[1], this.start[1])]; this.start = null; this.draw();},
    stateData() {return {...this.extras, ...this.editor, actions: JSON.parse(this.actions), recognition: this.recognitionType === 'image' ? {...(this.extras.recognition?.type === 'image' ? this.extras.recognition : {}), type: 'image', asset: this.asset} : {...(this.extras.recognition?.type === 'text' ? this.extras.recognition : {}), type: 'text', texts: this.texts.split('\n').map(s => s.trim()).filter(Boolean), mode: this.textMode}};},
    crop() {this.guard(async () => {const result = await api('/api/crop', {capture_id: this.captureId, asset_id: this.editor.id, box: this.box}); this.asset = result.asset;});},
    saveState() {this.guard(async () => {await api('/api/states', this.stateData()); this.states = await api('/api/states');});},
    preview() {this.guard(async () => {this.probe = await api('/api/preview', {capture_id: this.captureId, state: this.stateData()});});},
    editState(s) {this.extras = JSON.parse(JSON.stringify(s)); this.editor = {id: s.id, name: s.name, role: s.role, priority: s.priority}; this.recognitionType = s.recognition.type; this.asset = s.recognition.asset || ''; this.texts = (s.recognition.texts || []).join('\n'); this.textMode = s.recognition.mode || 'exact'; this.actions = JSON.stringify(s.actions, null, 2);},
    saveFlow() {this.guard(async () => {this.flow = await api('/api/flow', {...this.flow, state_ids: this.selected});});},
    run() {this.guard(async () => {const r = await api('/api/run', {serial: this.serial, flow: {...this.flow, state_ids: this.selected}}); this.runId = r.id; this.runData = {status: 'running'}; clearInterval(this.timer); this.timer = setInterval(() => this.poll(), 1000); await this.poll();});},
    poll() {return this.guard(async () => {this.runData = await api('/api/runs/' + this.runId); if (!this.running) clearInterval(this.timer);});},
    cancel() {this.guard(async () => {await api('/api/cancel', {id: this.runId});});},
  },
};
</script>

<style>
body {margin: 0; background: #f4f6f8; color: #263445; font-family: system-ui, sans-serif;}
main {max-width: 1200px; margin: auto; padding: 24px;}
h1 {font-size: 24px;} h2 {font-size: 18px;}
.el-card {margin: 16px 0;} .columns {display: grid; grid-template-columns: 1fr 1fr; gap: 20px;}
canvas {max-width: 100%; display: block; background: #eee; cursor: crosshair;}
pre {max-height: 300px; overflow: auto; font-size: 12px; white-space: pre-wrap;}
small {color: #64748b;} input[type=file] {margin-left: 12px;}
@media (max-width: 800px) {.columns {grid-template-columns: 1fr;}}
</style>
