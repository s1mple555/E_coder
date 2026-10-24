<script setup>
import {computed,ref} from 'vue';
import Icon from './Icon.vue';
defineEmits(['detail']);
const props=defineProps({kind:String,work:Object});
const query=ref('');
const tools=computed(()=>(props.work.s.status?.tools||[]).filter(tool=>(tool.name+tool.description).toLowerCase().includes(query.value.toLowerCase())));
const permissions={read:'直接读取',state:'会话状态',approval:'需要审批',delegate:'子 Agent 委派'};
async function reload(){try{await props.work.loadStatus();props.work.notify('技能库已刷新');}catch(error){props.work.notify(error.message);}}
</script>
<template><main :id="`page-${kind}`" class="page library-page">
<div class="library-intro"><div><span class="page-kicker">{{kind==='tools'?'能力中心':'渐进式加载'}}</span><h1>{{kind==='tools'?'每一步，都有迹可循。':'把经验，变成可复用的能力。'}}</h1><p>{{kind==='tools'?'模型通过这些工具读代码、管理任务和提出修改。权限策略由运行时执行。':'先提供技能索引，需要时再加载完整指南。添加 skills/名称/SKILL.md 即可发现。'}}</p></div></div>
<div class="library-toolbar"><h2>{{kind==='tools'?'内置工具':'技能库'}}</h2><label v-if="kind==='tools'">搜索工具<input v-model="query" type="search" placeholder="名称或用途"></label><button v-else class="secondary" @click="reload">刷新技能</button></div>
<div v-if="kind==='tools'" class="tools-grid"><article v-for="tool in tools" :key="tool.name" class="tool-card"><div class="tool-card-head"><span class="tool-symbol"><Icon :name="tool.permission==='approval'?'shield':tool.permission==='state'?'chat':'tools'"/></span><span class="badge" :class="`permission-${tool.permission}`">{{permissions[tool.permission]}}</span></div><h3>{{tool.name}}</h3><p>{{tool.description}}</p><button class="library-detail-button" @click="$emit('detail',{kind:'tool',item:tool})">参数定义<Icon name="panel"/></button></article><div v-if="!tools.length" class="empty-state">没有匹配的工具。</div></div>
<div v-else class="skills-grid"><article v-for="skill in work.s.status?.skills||[]" :key="skill.name" class="skill-card"><div class="skill-icon"><Icon name="skills"/></div><h3>{{skill.name}}</h3><p>{{skill.description}}</p><footer><span>按需加载</span><button class="library-detail-button" @click="$emit('detail',{kind:'skill',item:skill})">查看详情<Icon name="panel"/></button></footer></article><div v-if="!work.s.status?.skills.length" class="empty-state">技能库为空，请在项目 skills 目录中添加 SKILL.md。</div></div>
</main></template>
