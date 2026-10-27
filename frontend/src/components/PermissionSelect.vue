<script setup>
import {ref} from 'vue';
import {action} from '../lib/api.js';
const props=defineProps({work:Object});
const saving=ref(false);
async function change(event){
  const select=event.target,mode=select.value;
  if(saving.value||props.work.s.running||!props.work.s.status){select.value=props.work.s.status?.permission_mode||'approval';return;}
  saving.value=true;
  try{
    const result=await action('/api/permissions',{permission_mode:mode});
    props.work.s.status={...props.work.s.status,permission_mode:result.permission_mode||mode};
    await props.work.loadStatus();
    props.work.notify('权限模式已保存，对所有会话、子 Agent 和定时任务生效。');
  }catch(error){props.work.notify(error.message);}
  finally{saving.value=false;select.value=props.work.s.status?.permission_mode||'approval';}
}
</script>
<template><select class="composer-permissions" :class="{'is-full':work.s.status?.permission_mode==='full'}" aria-label="操作权限" :title="work.s.running?'请先结束或停止任务再切换权限':'选择后立即保存，对所有会话生效；重启后保留'" :value="work.s.status?.permission_mode||'approval'" :disabled="saving||work.s.running||!work.s.status" :aria-busy="saving" @change="change"><option value="approval">权限：逐次审批</option><option value="full">权限：放开权限</option></select></template>
