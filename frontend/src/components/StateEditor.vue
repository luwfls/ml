<template>
  <el-drawer :visible="visible" @close="$emit('close')" :title="editor.original.id ? '编辑 State' : '新建 State'" size="470px" :modal="false">
    <div class="drawer-body">
      <el-form label-width="96px" size="small" :disabled="locked">
        <el-form-item label="ID"><el-input v-model="editor.id" :disabled="!!editor.original.id" placeholder="英文字母、数字、_、-" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="editor.name" /></el-form-item>
        <el-form-item label="分组"><el-select v-model="editor.group" clearable><el-option v-for="g in groups" :key="g.name" :label="g.name" :value="g.name" /></el-select></el-form-item>
        <el-form-item label="角色"><el-select v-model="editor.role"><el-option v-for="r in roles" :key="r" :label="roleLabels[r]" :value="r" /></el-select></el-form-item>
        <el-form-item label="优先级"><el-input-number v-model="editor.priority" :min="-10000" :max="10000" /></el-form-item>
        <el-form-item label="识别类型"><el-radio-group v-model="editor.kind"><el-radio label="image">图片</el-radio><el-radio label="text">文字</el-radio></el-radio-group></el-form-item>
        <template v-if="editor.kind==='image'">
          <el-form-item label="图片资源"><el-input v-model="editor.asset" placeholder="框选后裁剪或填写现有资源名" /><el-button :disabled="!canCrop" @click="$emit('crop')">裁剪识别区</el-button></el-form-item>
          <el-form-item label="匹配阈值"><el-input-number v-model="editor.threshold" :min=".01" :max="1" :step=".01" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="候选文案"><el-input v-model="editor.texts" type="textarea" :rows="3" placeholder="每行一个候选文案" /></el-form-item>
          <el-form-item label="匹配模式"><el-select v-model="editor.mode"><el-option v-for="m in ['exact','contains','fuzzy']" :key="m" :value="m" :label="m" /></el-select></el-form-item>
          <el-form-item label="最低置信度"><el-input-number v-model="editor.min_confidence" :min="0" :max="1" :step=".01" /></el-form-item>
          <el-form-item label="模糊相似度"><el-input-number v-model="editor.similarity_threshold" :min=".01" :max="1" :step=".01" /></el-form-item>
        </template>
        <el-form-item label="搜索 ROI"><div class="coordinates"><el-input-number v-for="(_,i) in editor.region" :key="i" v-model="editor.region[i]" :min="0" :max="1" :step=".01" :controls="false" /></div><el-button @click="$emit('roi')" :disabled="!canROI">采用截图 ROI</el-button><el-button @click="editor.region=[0,0,1,1]">全图</el-button></el-form-item>
        <el-form-item label="必须命中"><el-select v-model="editor.conditions.required_states" multiple filterable><el-option v-for="s in otherStates" :key="s.id" :value="s.id" :label="s.name+' · '+s.id" /></el-select></el-form-item>
        <el-form-item label="禁止命中"><el-select v-model="editor.conditions.excluded_states" multiple filterable><el-option v-for="s in otherStates" :key="s.id" :value="s.id" :label="s.name+' · '+s.id" /></el-select></el-form-item>
        <el-form-item label="输入动作"><el-select :value="inputType" @change="changeInput"><el-option label="无输入（只识别 / 等待）" value="none" /><el-option label="点击匹配位置" value="click_match" /><el-option label="安卓按键" value="key" /><el-option label="滑动" value="swipe" /></el-select></el-form-item>
        <template v-if="inputAction">
          <el-form-item v-if="inputType==='key'" label="按键"><el-select v-model="inputAction.key"><el-option v-for="key in ['back','home','enter']" :key="key" :label="key" :value="key" /></el-select></el-form-item>
          <template v-if="inputType==='swipe'"><el-form-item label="滑动坐标"><div class="coordinates"><el-input-number v-for="(_,i) in inputAction.points" :key="i" v-model="inputAction.points[i]" :min="0" :max="1" :step=".01" :controls="false" /></div><small>起点 x/y、终点 x/y（归一化坐标）</small></el-form-item><el-form-item label="时长 ms"><el-input-number v-model="inputAction.duration_ms" :min="1" :max="10000" /></el-form-item></template>
          <el-form-item v-if="inputType==='click_match'" label="点击区域"><p>{{ inputAction.target_box ? inputAction.target_box.join(', ') : '匹配框中心' }}</p><el-button :disabled="editor.kind!=='image'||!canTarget" @click="$emit('target')">裁剪并采用独立点击区</el-button><el-button @click="$delete(inputAction,'target_box')">匹配中心</el-button></el-form-item>
        </template>
        <el-form-item label="后置等待"><div v-for="(a,i) in editor.actions" :key="i" v-if="a.type==='wait'" class="button-row"><el-input-number v-model="a.ms" :min="0" :max="10000" /><span>ms</span><el-button @click="editor.actions.splice(i,1)">移除</el-button></div><el-button @click="editor.actions.push({type:'wait',ms:500})">添加等待</el-button></el-form-item>
        <small>成功 / 失败 State 为断言，保存前请保持无动作。每个 State 最多一个输入动作。</small>
      </el-form>
      <div class="button-row"><el-button type="primary" :disabled="locked" @click="$emit('save')">保存 F4</el-button><el-button :disabled="!canPreview" @click="$emit('preview')">识别预览</el-button><el-button type="warning" :disabled="locked||!editor.original.id||!serial" @click="$emit('execute')">执行动作 F5</el-button></div>
      <div v-if="editor.original.id" class="button-row"><el-button :disabled="locked" @click="$emit('copy',editor.original)">复制 State</el-button><el-button type="danger" :disabled="locked" @click="$emit('delete',editor.original)">删除 State</el-button></div>
    </div>
  </el-drawer>
</template>
<script>
export default {props:{visible:Boolean,editor:Object,states:Array,groups:Array,locked:Boolean,serial:String,canCrop:Boolean,canROI:Boolean,canTarget:Boolean,canPreview:Boolean},data:()=>({roles:['normal','success','failure','fallback'],roleLabels:{normal:'普通',success:'成功断言',failure:'失败断言',fallback:'兜底（须命中）'}}),computed:{otherStates(){return this.states.filter(s=>s.id!==this.editor.id);},inputAction(){return this.editor.actions.find(a=>a.type!=='wait');},inputType(){return this.inputAction?.type||'none';}},methods:{changeInput(type){const waits=this.editor.actions.filter(a=>a.type==='wait');const action=type==='none'?[]:[type===this.inputType?this.inputAction:{type,...(type==='key'?{key:'back'}:type==='swipe'?{points:[.5,.8,.5,.2],duration_ms:300}:{})}];this.editor.actions=[...action,...waits];}}};
</script>
