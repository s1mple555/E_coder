<script setup>
import {ref,computed,watch,onBeforeUnmount} from 'vue';
import {api,action} from '../lib/api.js';
const props=defineProps({work:Object});
const entry=ref(''),entries=ref([]),entriesBusy=ref(false),truncated=ref(false),opening=ref(false),saving=ref(false),preview=ref(null),frame=ref(null),open=ref(false),target=ref(null),note=ref(''),rows=ref([]),busy=ref(false);
const visibleRows=computed(()=>rows.value.filter(row=>row.entry===preview.value?.entry));
const base=id=>`/api/sessions/${id}`;
let contextRevision=0,previewRequest=0,entryRequest=0,annotationRequest=0,selectionRevision=0,disposed=false;
const current=(id,revision)=>!disposed&&id===props.work.s.session&&revision===contextRevision;
function label(path){return path.length>46?path.slice(0,18)+'…'+path.slice(-24):path;}
function closePreview(){previewRequest++;selectionRevision++;open.value=false;opening.value=false;target.value=null;note.value='';}
async function refresh(){
 const id=props.work.s.session,revision=contextRevision,request=++annotationRequest;if(!id)return;
 const data=await api(base(id)+'/annotations');if(current(id,revision)&&request===annotationRequest)rows.value=data.annotations;
}
async function refreshEntries(){
 const id=props.work.s.session,revision=contextRevision,request=++entryRequest;if(!id){entries.value=[];entriesBusy.value=false;return;}
 entriesBusy.value=true;
 try{const data=await api(base(id)+'/preview/entries');if(current(id,revision)&&request===entryRequest){entries.value=data.entries||[];truncated.value=!!data.truncated;if(!entries.value.some(page=>page.path===entry.value))entry.value=entries.value[0]?.path||'';}}
 finally{if(current(id,revision)&&request===entryRequest)entriesBusy.value=false;}
}
watch(()=>[props.work.s.session,props.work.s.localFolder],()=>{contextRevision++;closePreview();preview.value=null;rows.value=[];entries.value=[];entry.value='';truncated.value=false;props.work.safe(()=>Promise.all([refresh(),refreshEntries()]));},{immediate:true});
watch(()=>props.work.s.running,(running,previous)=>{if(previous&&!running)props.work.safe(refreshEntries);});
async function load(){
 const id=props.work.s.session,path=entry.value,revision=contextRevision,request=++previewRequest;
 if(!id||!path)throw new Error('请先选择已生成的 HTML 页面');opening.value=true;
 try{const data=await action(base(id)+'/preview',{entry:path});if(current(id,revision)&&request===previewRequest){preview.value=data;open.value=true;selectionRevision++;target.value=null;note.value='';}}
 finally{if(current(id,revision)&&request===previewRequest)opening.value=false;}
}
function receive(event){
 const data=event.data;if(!open.value||event.source!==frame.value?.contentWindow||event.origin!=='null'||data?.token!==preview.value?.token||data.type!=='ecoder:annotation'||data.entry!==preview.value.entry)return;
 if(typeof data.selector!=='string'||typeof data.text!=='string')return;
 selectionRevision++;target.value={selector:data.selector.slice(0,2000),text:data.text.slice(0,500),component:String(data.component||'').slice(0,200),source:String(data.source||'').slice(0,500),rect:data.rect,viewport:data.viewport};note.value='';
}
window.addEventListener('message',receive);
onBeforeUnmount(()=>{disposed=true;contextRevision++;previewRequest++;window.removeEventListener('message',receive);});
async function save(){
 if(saving.value||!target.value||!preview.value||!note.value.trim())return;
 const id=props.work.s.session,revision=contextRevision,selection=selectionRevision,document=preview.value,draft=note.value,selected=target.value;saving.value=true;
 try{await action(base(id)+'/annotations',{...selected,entry:document.entry,revision:document.revision,note:draft});
  if(current(id,revision)){if(preview.value?.token===document.token&&selection===selectionRevision&&note.value===draft){target.value=null;note.value='';}await refresh();}}
 finally{saving.value=false;}
}
async function submit(){
 if(busy.value)return;const id=props.work.s.session,revision=contextRevision;busy.value=true;
 try{await action(base(id)+'/annotations/submit',{ids:visibleRows.value.filter(row=>row.status==='pending').map(row=>row.id)});
  if(current(id,revision)){await props.work.openSession(id);if(id===props.work.s.session){closePreview();props.work.s.tab='timeline';}}}
 finally{busy.value=false;}
}
async function state(row,status){const id=props.work.s.session,revision=contextRevision;await api(base(id)+`/annotations/${row.id}`,{method:'PATCH',body:JSON.stringify({status})});if(current(id,revision))await refresh();}
function generate(){props.work.s.prompt+=(props.work.s.prompt?'\n':'')+'请根据我的需求生成可预览的前端界面。先检查工作区：独立页面生成 index.html；已有 Vue/React 项目沿用结构并构建 dist/index.html。尽可能给关键元素添加 data-component 和 data-source（源码相对路径）以便视觉标注定位。修改和命令遵循当前权限模式。';}
</script>
<template><div class="preview-launch"><label>选择前端页面<select v-model="entry" aria-label="预览入口" :disabled="entriesBusy||opening"><option v-if="!entries.length" value="">{{entriesBusy?'正在查找页面…':'暂无可预览页面'}}</option><option v-for="page in entries" :key="page.path" :value="page.path" :title="page.path">{{label(page.path)}}{{page.generated?' · 本会话生成/修改':page.related?' · 本会话涉及':''}}</option></select></label><div class="preview-entry-actions"><button class="secondary" :disabled="!entry||opening||entriesBusy" @click="work.safe(load)">{{opening?'正在打开…':'预览所选页面'}}</button><button class="quiet" :disabled="entriesBusy" @click="work.safe(refreshEntries)">刷新页面列表</button></div><p v-if="!entries.length&&!entriesBusy" class="section-note">当前工作区还没有 HTML 页面。先生成页面；Vue / React 项目请先构建静态产物。</p><small v-if="truncated">目录较大，当前列表为部分结果。</small><button class="quiet" @click="generate">将生成界面的要求加入输入框</button><small>列表包含当前会话工作区内的 HTML 页面；预览以 100% 比例铺满可用区域，点击元素即可标注。</small>
<div v-if="open" class="preview-studio" role="dialog" aria-modal="true" aria-label="前端预览与组件标注"><header><div><strong>界面预览</strong><small>{{preview.entry}}</small></div><select v-model="entry" aria-label="切换预览页面" :disabled="opening"><option v-for="page in entries" :key="page.path" :value="page.path" :title="page.path">{{label(page.path)}}</option></select><button class="quiet" :disabled="opening" @click="work.safe(load)">{{entry===preview.entry?'刷新产物':'预览所选页面'}}</button><button class="quiet" @click="closePreview">关闭预览</button></header>
<div class="preview-body"><div class="preview-canvas"><iframe ref="frame" :key="preview.token" :src="preview.url" sandbox="allow-scripts" referrerpolicy="no-referrer" title="隔离的前端预览"></iframe></div><aside><h3>组件修改意见</h3><p class="hint">点击页面元素添加修改意见，所有预览均可直接标注。</p>
<form v-if="target" @submit.prevent="work.safe(save)"><code>{{target.selector}}</code><p>{{target.text}}</p><small v-if="target.source">源码提示：{{target.source}}</small><label>修改要求<textarea v-model="note" :disabled="saving" aria-label="组件修改要求" rows="4" required maxlength="4000" placeholder="例如：按钮改为深蓝色，增加左右间距"></textarea></label><button class="secondary" :disabled="saving||!note.trim()">{{saving?'正在保存…':'保存标注'}}</button></form>
<p v-else class="hint">点击要调整的按钮、标题或布局区域。</p>
<article v-for="row in visibleRows" :key="row.id"><code>{{row.selector}}</code><p>{{row.note}}</p><small>{{({pending:'待提交',submitted:'已提交',resolved:'已验收',dismissed:'已忽略'})[row.status]}}</small><div v-if="['pending','submitted'].includes(row.status)"><button class="quiet" @click="work.safe(()=>state(row,'resolved'))">标记已验收</button><button class="quiet" @click="work.safe(()=>state(row,'dismissed'))">忽略</button></div></article>
<button class="secondary submit-feedback" :disabled="busy||work.s.running||!visibleRows.some(x=>x.status==='pending')" @click="work.safe(submit)">{{busy?'正在提交…':'提交待处理标注给 Agent'}}</button><p class="hint">将开启本会话新一轮修改，文件和命令遵循当前权限模式。完成后刷新产物并验收。</p></aside></div></div></div></template>
<style scoped>.preview-launch{display:grid;gap:12px;font-size:13px}.preview-entry-actions{display:flex;gap:10px;align-items:center}.preview-launch select,.preview-launch textarea{display:block;width:100%;box-sizing:border-box;padding:9px;border:1px solid #d8dce4;border-radius:6px;font:inherit}.preview-launch small,.hint{color:#667085;line-height:1.6}.preview-studio{position:fixed;inset:0;z-index:900;background:#fff;border:1px solid #cbd0df;box-shadow:0 20px 90px #202b4855;display:flex;flex-direction:column;border-radius:0;overflow:hidden}.preview-studio header{display:flex;align-items:center;gap:16px;padding:14px 20px;border-bottom:1px solid #dddfea}.preview-studio header select{max-width:280px;min-width:0;padding:8px;border:1px solid #d8dce4;border-radius:6px;font:inherit}.preview-studio header>div{margin-right:auto;display:grid;gap:3px}.preview-body{display:flex;flex:1;min-height:0}.preview-canvas{flex:1;min-width:0;min-height:0;background:#fff;padding:0;overflow:hidden;display:flex}.preview-canvas iframe{display:block;flex:1;width:100%;min-width:0;border:0;background:#fff;height:100%;max-width:100%}.preview-body aside{flex-shrink:0;width:310px;max-width:40%;overflow:auto;padding:18px;border-left:1px solid #dddfea}.preview-body h3{margin:0}.preview-body code{display:block;font-size:11px;overflow-wrap:anywhere;color:#4f46a5}.preview-body article{padding:14px 0;border-top:1px solid #dddfea}.preview-body form{display:grid;gap:10px;margin-bottom:18px}.submit-feedback{width:100%}@media(max-width:700px){.preview-studio header{flex-wrap:wrap;gap:8px}.preview-body{flex-direction:column}.preview-canvas{min-height:280px}.preview-body aside{width:auto;max-width:none;max-height:40%}}</style>
