<template>
  <div class="capture-workbench">
    <div class="button-row"><el-radio-group v-model="mode" size="small"><el-radio-button label="recognition">识别区 F2</el-radio-button><el-radio-button label="click">点击区 F3</el-radio-button></el-radio-group><el-button size="small" @click="clear">清除当前区域</el-button></div>
    <p class="hint">拖动框选，按原始像素保存。蓝色识别区 / 橙色点击区。开启范围限制时，图片与文字均在识别区内搜索。</p>
    <div v-if="!image" class="empty-capture">设备截图或导入 PNG 开始制作</div>
    <canvas ref="canvas" v-show="image" @pointerdown="begin" @pointermove="move" @pointerup="end" @pointercancel="start=null" />
    <p v-if="image" class="hint">截图 {{ size.join(' × ') }} px · 识别区 {{ boxes.recognition.join(', ') || '未框选' }} · 点击区 {{ boxes.click.join(', ') || '默认匹配中心' }}</p>
  </div>
</template>
<script>
import {pixelPoint,rectangle} from '../model.js';
export default {
  props:{url:String,matches:Array,recognitionBox:Array,targetBox:Array,locked:Boolean},data:()=>({image:null,mode:'recognition',start:null,boxes:{recognition:[],click:[]},size:[]}),
  watch:{url:{immediate:true,handler(url){this.image=null;this.size=[];this.restore();if(!url)return;const img=new Image();img.onload=()=>{if(url!==this.url)return;this.image=img;this.size=[img.naturalWidth,img.naturalHeight];this.boxes={recognition:[],click:[]};this.restore();};img.onerror=()=>{if(url!==this.url)return;this.$emit('error','完整截图不存在或加载失败，请重新导入截图后保存。');};img.src=url;}},matches(){this.draw();},recognitionBox(){this.restore();},targetBox(){this.restore();}},
  methods:{setMode(mode){this.mode=mode;},restore(){this.boxes={recognition:this.size.length===2?(this.recognitionBox||[]).map((v,i)=>Math.round(v*this.size[i%2])):[],click:[]};const box=this.boxes.recognition;if(box.length===4&&this.targetBox?.length===4)this.boxes.click=this.targetBox.map((v,i)=>Math.round(box[i%2]+v*(box[i%2+2]-box[i%2])));this.start=null;this.$emit('selection',{...this.boxes,size:this.size,restored:true});this.$nextTick(this.draw);},clear(){if(this.locked)return;this.$set(this.boxes,this.mode,[]);this.$emit('selection',{...this.boxes,size:this.size,mode:this.mode});this.$nextTick(this.draw);},
    point(e){return pixelPoint(e.clientX,e.clientY,this.$refs.canvas.getBoundingClientRect(),this.size);},
    begin(e){if(!this.image||this.locked)return;this.start=this.point(e);this.$refs.canvas.setPointerCapture(e.pointerId);},
    move(e){if(!this.start)return;this.boxes[this.mode]=rectangle(this.start,this.point(e));this.draw();},
    end(e){if(!this.start)return;this.boxes[this.mode]=rectangle(this.start,this.point(e));this.start=null;this.draw();this.$emit('selection',{...this.boxes,size:this.size,mode:this.mode});},
    draw(){const canvas=this.$refs.canvas;if(!canvas||!this.image)return;canvas.width=this.size[0];canvas.height=this.size[1];const ctx=canvas.getContext('2d');ctx.drawImage(this.image,0,0);const stroke=(box,color)=>{if(!box||box.length!==4)return;ctx.strokeStyle=color;ctx.lineWidth=Math.max(2,canvas.width/400);ctx.strokeRect(box[0],box[1],box[2]-box[0],box[3]-box[1]);};Object.entries(this.boxes).forEach(([kind,box])=>stroke(box,{recognition:'#2563eb',click:'#f97316'}[kind]));(this.matches||[]).forEach(m=>stroke(m.bbox,m.ambiguous?'#dc2626':'#a855f7'));}}
};
</script>
