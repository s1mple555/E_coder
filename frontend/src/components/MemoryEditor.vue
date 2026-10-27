<script setup>
import {ref,computed,watch} from 'vue';
import {api} from '../lib/api.js';
const props=defineProps({work:Object});
const editing=ref(false),draft=ref(''),base=ref(''),saving=ref(false),refreshing=ref(false),error=ref('');
const changed=computed(()=>draft.value!==base.value);
watch(()=>props.work.s.session,()=>{editing.value=false;draft.value='';base.value='';error.value='';});
function applyMemory(content){if(props.work.setMemory)props.work.setMemory(content);else props.work.s.memory=content;}
function edit(){if(!props.work.s.session||props.work.s.running||props.work.s.loading)return;base.value=props.work.s.memory||'';draft.value=base.value;error.value='';editing.value=true;}
function cancel(){editing.value=false;draft.value='';error.value='';}
async function reload(){
 const id=props.work.s.session;if(!id)return;refreshing.value=true;error.value='';
 try{const result=await api(`/api/sessions/${id}/memory`);if(id===props.work.s.session){applyMemory(result.memory);base.value=result.memory;draft.value=result.memory;}}
 catch(failure){if(id===props.work.s.session)error.value=failure.message;}
 finally{refreshing.value=false;}
}
async function save(){
 const id=props.work.s.session;if(!id||saving.value||!changed.value||props.work.s.running)return;saving.value=true;error.value='';
 try{const result=await api(`/api/sessions/${id}/memory`,{method:'PUT',body:JSON.stringify({content:draft.value,expected:base.value})});
  if(id===props.work.s.session){applyMemory(result.memory);editing.value=false;props.work.notify('备忘录已保存。');}}
 catch(failure){if(id===props.work.s.session)error.value=failure.message;}
 finally{saving.value=false;}
}
</script>
<template><section class="memory-editor"><div class="memory-editor-heading"><h3 class="minor-heading">会话备忘录</h3><button v-if="!editing" class="quiet" type="button" :disabled="!work.s.session||work.s.running||work.s.loading" @click="edit">编辑备忘录</button></div><form v-if="editing" @submit.prevent="save"><textarea v-model="draft" aria-label="编辑会话备忘录" rows="6" maxlength="8000" :disabled="saving||refreshing" placeholder="填写需要 Agent 记住的约束、偏好或已验证事实；留空保存可清空备忘录。"></textarea><div class="memory-editor-meta"><small>保存后用于当前会话的后续请求</small><small>{{draft.length}} / 8000</small></div><p v-if="work.s.running" class="memory-editor-error">任务运行中，请结束后再保存。</p><div class="memory-editor-actions"><button class="secondary" type="submit" :disabled="saving||refreshing||work.s.running||!changed">{{saving?'正在保存…':'保存备忘录'}}</button><button type="button" class="quiet" :disabled="saving||refreshing" @click="cancel">取消</button><button type="button" class="quiet" :disabled="saving||refreshing" @click="reload">重新载入</button></div></form><pre v-else class="memory">{{work.s.memory||'暂无备忘录，可手动编辑，也可由 Agent 保存。'}}</pre><p v-if="error" role="alert" class="memory-editor-error">{{error}}</p></section></template>
<style scoped>.memory-editor{margin-top:18px}.memory-editor-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.memory-editor-heading h3{margin:0}.memory-editor form{display:grid;gap:10px}.memory-editor textarea{width:100%;box-sizing:border-box;min-height:140px;resize:vertical;padding:10px;border:1px solid #d3daea;border-radius:8px;color:inherit;background:#fff;font:inherit;font-size:13px;line-height:1.65}.memory-editor-meta{display:flex;justify-content:space-between;gap:10px;color:#7b879d;font-size:11px}.memory-editor-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.memory-editor-error{color:#b42318;font-size:12px;line-height:1.6;margin:8px 0}.memory-editor .memory{white-space:pre-wrap;overflow-wrap:anywhere}.memory-editor textarea:focus-visible{outline:2px solid #6571dd;outline-offset:2px}</style>
