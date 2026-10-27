<script setup>
import {ref} from 'vue';
import Icon from './Icon.vue';
import BaseDialog from './BaseDialog.vue';
const props=defineProps({work:Object});
const recent=ref(false),deleting=ref(null);
const pages=[['chat','chat','工作台'],['tools','tools','工具箱'],['skills','skills','Skills'],['experiences','skills','经验管理'],['storage','storage','存储管理'],['settings','settings','连接与配置']];
async function remove(id){if(deleting.value)return;deleting.value=id;try{await props.work.deleteSession(id);}catch(error){props.work.notify(error.message);}finally{deleting.value=null;}}
function open(id){recent.value=false;props.work.openSession(id);}
</script>
<template>
  <aside class="sidebar">
    <a href="/" class="brand" aria-label="E_coder 工作台"><img class="brand-mark" src="/static/assets/ecoder-icon.svg" alt=""><span>E_coder<small>个人编程工作台</small></span></a>
    <button id="new-session" class="new-session" :disabled="work.s.uploading || work.s.creating || work.s.submitting" @click="work.newSession"><Icon name="plus"/>新的编程任务</button>
    <nav aria-label="主导航"><button v-for="[page,icon,label] in pages" :key="page" class="nav" :class="{active:work.s.page===page}" :data-page="page" @click="work.s.page=page"><Icon :name="icon"/>{{label}}<small v-if="page==='tools'">{{work.s.status?.tools.length ?? '—'}}</small><small v-if="page==='skills'">{{work.s.status?.skills.length ?? '—'}}</small></button>
    <button class="nav mobile-recents" @click="recent=true"><Icon name="history"/>最近任务</button></nav>
    <div class="session-heading"><span>最近任务</span><div class="session-toolbar"><button aria-label="管理最近任务" @click="recent=true"><Icon name="history"/></button><button aria-label="刷新会话" @click="work.safe(work.refreshSessions)"><Icon name="refresh"/></button></div></div>
    <div id="sessions" class="sessions"><div v-for="session in work.s.sessions" :key="session.id" class="session-row" :class="{active:session.id===work.s.session}"><button class="session" :class="{active:session.id===work.s.session}" :title="session.title" @click="open(session.id)">{{session.title}}</button><button class="session-control session-delete" :disabled="!!deleting" :aria-label="`删除任务：${session.title}`" @click="remove(session.id)"><Icon name="trash"/></button></div><div v-if="!work.s.sessions.length" class="session-list-empty">暂无最近任务</div></div>
    <div class="sidebar-bottom"><span class="status-dot"/><div>本地运行<small>修改由你决定</small></div><span class="version">v0.2</span></div>
  </aside>
  <BaseDialog class="session-manager" :open="recent" labelledby="manager-title" @close="recent=false"><div class="manager-heading"><h2 id="manager-title">管理任务记录</h2><button class="quiet" aria-label="关闭任务管理" @click="recent=false">关闭 ×</button></div><p class="manager-note">删除会永久清除会话、聊天、执行日志和任务记录，无法恢复。工作区文件不受影响。</p><div class="managed-sessions"><div v-for="session in work.s.sessions" :key="session.id" class="session-row managed-row"><button class="session" @click="open(session.id)">{{session.title}}</button><button class="session-control session-delete" :disabled="!!deleting" :aria-label="`删除任务：${session.title}`" @click="remove(session.id)"><Icon name="trash"/></button></div><div v-if="!work.s.sessions.length" class="empty-state">暂无最近任务</div></div></BaseDialog>
</template>
