<template>
  <div class="capture-workbench">
    <div class="button-row"><el-radio-group v-model="mode" size="small"><el-radio-button label="recognition">识别区 F2</el-radio-button><el-radio-button label="click">点击区 F3</el-radio-button><el-radio-button label="roi">搜索 ROI</el-radio-button></el-radio-group><el-button size="small" @click="clear">清除框选</el-button></div>
    <p class="hint">拖动框选，按原始像素保存。橙色识别区 / 蓝色点击区 / 绿色 ROI。图片与文字均可限定搜索 ROI。</p>
    <div v-if="!image" class="empty-capture">设备截图或导入 PNG 开始制作</div>
    <canvas ref="canvas" v-show="image" @pointerdown="begin" @pointermove="move" @pointerup="end" @pointercancel="start=null" />
    <p v-if="image" class="hint">截图 {{ size.join(' × ') }} px · 识别区 {{ boxes.recognition.join(', ') || '未框选' }} · 点击区 {{ boxes.click.join(', ') || '默认匹配中心' }} · ROI {{ boxes.roi.join(', ') || '全图' }}</p>
  </div>
</template>
<script>
import {pixelPoint,rectangle} from '../model.js';
export default {
  props:{url:String,matches:Array},data:()=>({image:null,mode:'recognition',start:null,boxes:{recognition:[],click:[],roi:[]},size:[]}),
  watch:{url:{immediate:true,handler(url){if(!url)return;const img=new Image();img.onload=()=>{this.image=img;this.size=[img.naturalWidth,img.naturalHeight];this.clear();};img.onerror=()=>this.$emit('error','截图加载失败');img.src=url;}},matches(){this.draw();}},
  methods:{setMode(mode){this.mode=mode;},clear(){this.boxes={recognition:[],click:[],roi:[]};this.$emit('selection',{...this.boxes,size:this.size});this.$nextTick(this.draw);},
    point(e){return pixelPoint(e.clientX,e.clientY,this.$refs.canvas.getBoundingClientRect(),this.size);},
    begin(e){if(!this.image)return;this.start=this.point(e);this.$refs.canvas.setPointerCapture(e.pointerId);},
    move(e){if(!this.start)return;this.boxes[this.mode]=rectangle(this.start,this.point(e));this.draw();},
    end(e){if(!this.start)return;this.boxes[this.mode]=rectangle(this.start,this.point(e));this.start=null;this.draw();this.$emit('selection',{...this.boxes,size:this.size});},
    draw(){const canvas=this.$refs.canvas;if(!canvas||!this.image)return;canvas.width=this.size[0];canvas.height=this.size[1];const ctx=canvas.getContext('2d');ctx.drawImage(this.image,0,0);const stroke=(box,color)=>{if(!box||box.length!==4)return;ctx.strokeStyle=color;ctx.lineWidth=Math.max(2,canvas.width/400);ctx.strokeRect(box[0],box[1],box[2]-box[0],box[3]-box[1]);};Object.entries(this.boxes).forEach(([kind,box])=>stroke(box,{recognition:'#f97316',click:'#2563eb',roi:'#16a34a'}[kind]));(this.matches||[]).forEach(m=>stroke(m.bbox,m.ambiguous?'#dc2626':'#a855f7'));}}
};
</script>
