<script setup>
import {ref,computed,watch} from 'vue';
import {api,action} from '../lib/api.js';
const props=defineProps({work:Object});const rows=ref([]),selected=ref(''),confirmed=ref(false),busy=ref(false);
const runs=computed(()=>props.work.s.events.filter(x=>x.type==='run_end'&&x.status==='completed').map(x=>({id:x.run_id,seq:x.seq})));
async function refresh(){const id=props.work.s.session;if(!id){rows.value=[];return;}const data=await api(`/api/sessions/${id}/experiences`);if(id===props.work.s.session)rows.value=data.experiences;}
watch(()=>props.work.s.session,()=>{rows.value=[];selected.value='';confirmed.value=false;props.work.safe(refresh);},{immediate:true});
async function extract(){const id=props.work.s.session;if(!id)return;busy.value=true;try{const data=await action(`/api/sessions/${id}/experiences/extract`,{run_id:selected.value,confirmed:confirmed.value});if(id===props.work.s.session){rows.value=data.experiences;confirmed.value=false;}}finally{busy.value=false;}}
async function toggle(row){const id=props.work.s.session;await api(`/api/sessions/${id}/experiences/${row.id}`,{method:'PATCH',body:JSON.stringify({enabled:!row.enabled})});await refresh();}
</script>
<template><div class="learning-panel"><p class="section-note">从你确认成功的执行轮次中反思方法，保留工具证据。经验按当前工作区共享；相关经验会在后续任务中按需使用。</p>
<label>成功轮次<select v-model="selected" aria-label="成功轮次"><option value="">请选择</option><option v-for="(run,i) in runs" :key="run.id" :value="run.id">第 {{i+1}} 个完成轮次 · {{run.id.slice(0,8)}}</option></select></label>
<label><input v-model="confirmed" type="checkbox" aria-label="确认任务成功">我已确认这一轮实现了目标</label>
<button class="secondary" :disabled="busy||work.s.running||!selected||!confirmed" @click="work.safe(extract)">{{busy?'正在反思与整理…':'提取成功经验'}}</button><small>会调用已配置的模型；正常结束本身不代表任务成功。</small>
<button class="quiet" @click="work.safe(refresh)">刷新经验库</button>
<p v-if="!rows.length" class="empty-state">暂无经验。完成并验证任务后，在这里积累可复用的方法。</p>
<article v-for="row in rows" :key="row.id"><strong>{{row.title}}</strong><p>适用：{{row.when}}</p><p>{{row.strategy}}</p><small>确认 {{row.confirmations}} 次 · 来源 {{row.source_run.slice(0,8)}} · 证据 {{row.evidence.join(', ')}}</small><button class="quiet" @click="work.safe(()=>toggle(row))">{{row.enabled?'停用经验':'启用经验'}}</button></article></div></template>
<style scoped>.learning-panel{display:grid;gap:12px;font-size:13px}.learning-panel select{width:100%;padding:9px;border:1px solid #d8dce4;border-radius:6px;background:white;color:inherit}.learning-panel article{border-top:1px solid #dddfea;padding-top:14px;overflow-wrap:anywhere}.learning-panel p{line-height:1.65}.learning-panel small{color:#667085}</style>
