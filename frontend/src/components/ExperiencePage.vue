<script setup>
import {computed,ref,watch} from 'vue';
import ExperiencePanel from './ExperiencePanel.vue';
import {api} from '../lib/api.js';
import {shortPrompt} from '../lib/experienceRuns.js';
const props=defineProps({work:Object});
const source=ref(props.work.s.session||props.work.s.sessions[0]?.id||'__all__'),snapshot=ref(null),loading=ref(false),error=ref('');
let revision=0;
watch(source,async id=>{
  const request=++revision;snapshot.value=null;error.value='';loading.value=false;if(!id)return;
  if(id==='__all__'){snapshot.value={events:[],local_folder:null};return;}
  if(id===props.work.s.session){snapshot.value={events:props.work.s.events,local_folder:props.work.s.localFolder};return;}
  loading.value=true;
  try{const data=await api(`/api/sessions/${id}`);if(request===revision)snapshot.value=data;}
  catch(failure){if(request===revision)error.value=failure.message;}
  finally{if(request===revision)loading.value=false;}
},{immediate:true});
watch(()=>props.work.s.sessions.map(item=>item.id),ids=>{if(source.value!=='__all__'&&!ids.includes(source.value))source.value=ids.includes(props.work.s.session)?props.work.s.session:ids[0]||'__all__';});
const libraryWork=computed(()=>({...props.work,s:{...props.work.s,session:source.value,events:snapshot.value?.events||[],localFolder:snapshot.value?.local_folder||null}}));
</script>
<template><main id="page-experiences" class="page library-page experience-page"><header class="experience-page-heading"><div><h1>经验管理</h1><p v-if="source" class="experience-workspace" :title="snapshot?.local_folder||'默认或上传工作区'">{{source==='__all__'?'范围：全部会话（包含不同工作区）':`工作区：${snapshot?.local_folder||'默认或上传工作区'}`}}</p></div><button class="secondary" @click="work.s.page='chat';work.s.tab='experiences'">返回工作台总结</button></header><div class="experience-source"><label for="experience-session">来源会话</label><select id="experience-session" v-model="source" aria-label="经验来源会话"><option value="__all__">全部会话</option><option v-for="session in work.s.sessions" :key="session.id" :value="session.id" :title="session.title">{{shortPrompt(session.title,24)}}</option></select><span>{{source==='__all__'?'汇总所有已保存经验，共享经验只显示一次':'展示所选会话工作区共享的经验'}}</span></div><p v-if="loading" class="empty-state">正在读取经验…</p><p v-else-if="error" role="alert">{{error}}</p><ExperiencePanel v-else-if="source&&snapshot" :key="source" :work="libraryWork" view="library" :all-sessions="source==='__all__'"/><p v-else class="empty-state">先创建一个会话，再到工作台总结经验。</p></main></template>
<style scoped>.experience-page{padding:32px 40px;overflow:auto}.experience-page-heading,.experience-source,.experience-page>.learning-panel{max-width:1280px;margin-left:auto;margin-right:auto}.experience-page-heading{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:24px}.experience-page h1{margin:0;color:#344054;font-size:26px}.experience-workspace{color:#667085;font-size:12px;overflow-wrap:anywhere;margin:8px 0 0;max-width:780px}.experience-source{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding-bottom:22px;margin-bottom:22px;border-bottom:1px solid #dce2ef;font-size:13px}.experience-source select{min-width:0;max-width:100%;padding:10px 12px;border:1px solid #d3dbeb;border-radius:8px;background:#fff;font:inherit;color:inherit}.experience-source span{font-size:12px;color:#667085}@media(max-width:700px){.experience-page{padding:20px 16px}.experience-page-heading{align-items:flex-start;flex-direction:column}.experience-source{gap:8px}.experience-source select{width:100%}}</style>
