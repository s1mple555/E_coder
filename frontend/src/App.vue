<script setup>
import {ref,onMounted,onBeforeUnmount,defineAsyncComponent} from 'vue';
import {useWorkbench} from './composables/useWorkbench.js';
import Icon from './components/Icon.vue';
import Sidebar from './components/Sidebar.vue';
import ChatWorkspace from './components/ChatWorkspace.vue';
import ExecutionPanel from './components/ExecutionPanel.vue';
import LibraryPage from './components/LibraryPage.vue';
import LibraryDetails from './components/LibraryDetails.vue';
import SettingsPage from './components/SettingsPage.vue';
const StoragePage=defineAsyncComponent(()=>import('./components/StoragePage.vue'));
const work=useWorkbench(),detail=ref(null),collapsed=ref(false),mobile=ref(false);
const labels={chat:'工作台',tools:'工具箱',skills:'Skills',storage:'存储管理',settings:'连接与配置'};
function toggle(){if(window.innerWidth<=980)mobile.value=!mobile.value;else collapsed.value=!collapsed.value;}
function escape(event){if(event.key==='Escape')mobile.value=false;}
onMounted(()=>{work.initialize();window.addEventListener('keydown',escape);});
onBeforeUnmount(()=>window.removeEventListener('keydown',escape));
</script>
<template><div class="app"><Sidebar :work="work"/><div class="main-shell"><header class="topbar"><div class="breadcrumb"><Icon name="folder"/>E_coder<span>/</span><strong>{{labels[work.s.page]}}</strong></div><div class="header-right"><span class="badge">{{!work.s.status?'连接中':work.s.status.configured?'模型已配置':'待配置模型'}}</span><button class="model-button" @click="work.s.page='settings'">{{work.s.status?.model||'配置模型'}}</button></div></header>
<main id="page-chat" v-show="work.s.page==='chat'" class="page chat-page"><ChatWorkspace :work="work" @inspector="toggle"/><ExecutionPanel :work="work" :collapsed="collapsed" :mobile="mobile" @close="mobile=false"/></main>
<LibraryPage v-if="['tools','skills'].includes(work.s.page)" :key="work.s.page" :kind="work.s.page" :work="work" @detail="detail=$event"/>
<SettingsPage v-if="work.s.page==='settings'" :work="work"/><StoragePage v-if="work.s.page==='storage'" :work="work"/>
</div></div><LibraryDetails :detail="detail" @close="detail=null"/><div v-if="work.s.toast" class="toast" role="status">{{work.s.toast}}</div></template>
