<script setup>
import {computed,ref,watch,onBeforeUnmount} from 'vue';
import BaseDialog from './BaseDialog.vue';
import MarkdownText from './MarkdownText.vue';
import Icon from './Icon.vue';
import {api} from '../lib/api.js';
const props=defineProps({detail:Object});
defineEmits(['close']);
const tab=ref(0),data=ref(null),loading=ref(false),error=ref(''),panel=ref(null);
let request=0;
const isTool=computed(()=>props.detail?.kind==='tool');
const tabs=computed(()=>isTool.value?['参数说明','原始 JSON']:['指南','运行环境','资源文件']);
const parameters=computed(()=>Object.entries(props.detail?.item.schema?.properties||{}));
const required=computed(()=>new Set(props.detail?.item.schema?.required||[]));
const environment=computed(()=>[['技能目录',data.value?.directory],['操作系统',data.value?.runtimes?.platform],['Python',data.value?.runtimes?.python],['Node.js',data.value?.runtimes?.node],['配置的运行时',data.value?.configured_runtime?.Runtime]]);
const note=computed(()=>isTool.value?({read:'读取工具，可直接调用',state:'更新当前会话状态',approval:'执行前需用户审批',delegate:'独立上下文委派 · 子 Agent 写入和命令仍需审批'})[props.detail.item.permission]:'按需加载 · 配套命令执行前需审批');
async function load(){
  const current=++request;tab.value=0;data.value=null;error.value='';loading.value=false;
  if(!props.detail||isTool.value)return;loading.value=true;
  try{const value=await api(`/api/skills/${encodeURIComponent(props.detail.item.name)}`);if(current===request)data.value=value;}
  catch(reason){if(current===request)error.value=reason.message;}finally{if(current===request)loading.value=false;}
}
watch(()=>props.detail,load,{immediate:true});
watch(tab,()=>{if(panel.value)panel.value.scrollTop=0;});
onBeforeUnmount(()=>request++);
function typeOf(schema){if(schema.anyOf)return schema.anyOf.map(typeOf).join(' / ');if(schema.type==='array')return `array<${typeOf(schema.items||{})}>`;return schema.type||schema.$ref?.split('/').at(-1)||'object';}
function constraints(schema){const values=[];if(Object.hasOwn(schema,'default'))values.push(`默认：${JSON.stringify(schema.default)}`);if(schema.enum)values.push(`可选值：${schema.enum.join(' / ')}`);for(const [key,label] of [['minimum','最小值'],['maximum','最大值'],['minLength','最短字符'],['maxLength','最长字符'],['minItems','最少项'],['maxItems','最多项']])if(schema[key]!==undefined)values.push(`${label} ${schema[key]}`);return values.join(' · ');}
function key(event){if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();tab.value=event.key==='Home'?0:event.key==='End'?tabs.value.length-1:(tab.value+(event.key==='ArrowRight'?1:-1)+tabs.value.length)%tabs.value.length;event.currentTarget.querySelectorAll('button')[tab.value].focus();}
</script>
<template><BaseDialog id="library-detail" class="library-detail" :open="!!detail" labelledby="library-detail-title" aria-describedby="library-detail-description" @close="$emit('close')"><template v-if="detail"><header class="library-detail-heading"><div><span class="detail-kind">{{isTool?'工具参数':'Skill 详情'}}</span><h2 id="library-detail-title">{{detail.item.name}}</h2></div><button type="button" class="detail-close" aria-label="关闭详情" @click="$emit('close')">×</button></header><p id="library-detail-description" class="library-detail-description">{{detail.item.description}}</p><div class="library-detail-tabs" role="tablist" aria-label="详情内容" @keydown="key"><button v-for="(label,index) in tabs" :id="`library-detail-tab-${index}`" :key="label" class="detail-tab" :class="{active:tab===index}" role="tab" :aria-selected="tab===index" :tabindex="tab===index?0:-1" aria-controls="library-detail-content" @click="tab=index">{{label}}</button></div><div id="library-detail-content" ref="panel" class="library-detail-content" role="tabpanel" tabindex="0" :aria-labelledby="`library-detail-tab-${tab}`">
<template v-if="isTool"><template v-if="tab===0"><p class="detail-section-note">{{parameters.length}} 个参数 · {{required.size}} 个必填</p><div v-if="!parameters.length" class="detail-empty">此工具无需传入参数。</div><div class="parameter-list"><section v-for="[name,schema] in parameters" :key="name" class="parameter-item"><div class="parameter-heading"><code class="parameter-name">{{name}}</code><span class="parameter-type">{{typeOf(schema)}}</span><span :class="required.has(name)?'parameter-required':'parameter-optional'">{{required.has(name)?'必填':'选填'}}</span></div><p v-if="schema.description" class="parameter-description">{{schema.description}}</p><p v-if="constraints(schema)" class="parameter-limits">{{constraints(schema)}}</p><p v-if="schema.items?.properties" class="parameter-limits">子字段：{{Object.keys(schema.items.properties).join('、')}}</p></section></div></template><pre v-else class="detail-code"><code>{{JSON.stringify(detail.item.schema,null,2)}}</code></pre></template>
<div v-else-if="loading" class="detail-loading">正在读取技能内容…</div><div v-else-if="error"><p class="detail-error">{{error}}</p><button class="secondary" @click="load">重新加载</button></div><template v-else-if="data"><MarkdownText v-if="tab===0" class="detail-guide" :text="data.content||'暂无指南内容。'"/><template v-else-if="tab===1"><dl class="detail-environment"><div v-for="[label,value] in environment" :key="label"><dt>{{label}}</dt><dd>{{value||'未配置'}}</dd></div></dl><template v-if="data.configured_runtime?.Argv"><h3 class="detail-subheading">配置的启动参数</h3><pre class="detail-code"><code>{{JSON.stringify(data.configured_runtime.Argv,null,2)}}</code></pre></template><p v-if="data.execution_note" class="detail-section-note">{{data.execution_note}}</p></template><template v-else><p class="detail-section-note">{{data.resources?.length||0}} 个只读资源文件</p><ul class="detail-resources"><li v-for="path in data.resources" :key="path"><Icon name="paperclip"/><code>{{path}}</code></li></ul><div v-if="!data.resources?.length" class="detail-empty">此技能没有附带资源文件。</div></template></template>
</div><footer class="library-detail-footer">{{note}}</footer></template></BaseDialog></template>
