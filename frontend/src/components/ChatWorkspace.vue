<script setup>
import {ref,watch,nextTick,onMounted,onBeforeUnmount} from 'vue';
import Icon from './Icon.vue';
import BaseDialog from './BaseDialog.vue';
import MarkdownText from './MarkdownText.vue';
import FileAttachments from './FileAttachments.vue';
import {action,imageFile,pretty} from '../lib/api.js';
const props=defineProps({work:Object});
defineEmits(['inspector']);
const messages=ref(null),prompt=ref(null),fileInput=ref(null),imageInput=ref(null),folderOpen=ref(false),folderPath=ref(''),folderError=ref(''),folderBusy=ref(false),dragging=ref(false),approvalBusy=ref(null);
let follow=true,previousSession=null;
function scroll(){const box=messages.value;if(box)follow=box.scrollHeight-box.scrollTop-box.clientHeight<100;}
watch(()=>[props.work.s.messages.length,props.work.s.messages.at(-1)?.text,props.work.s.session],async()=>{
  const changed=previousSession!==props.work.s.session;previousSession=props.work.s.session;await nextTick();if((follow||changed)&&messages.value)messages.value.scrollTop=messages.value.scrollHeight;
});
watch(()=>props.work.s.page,async page=>{if(page==='chat'){await nextTick();if(follow&&messages.value)messages.value.scrollTop=messages.value.scrollHeight;}});
function key(event){if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();props.work.send();}}
function choose(event){const files=[...event.target.files];event.target.value='';props.work.upload(files);}
function paste(event){const files=[...(event.clipboardData?.files||[])];if(files.length){event.preventDefault();props.work.upload(files);}}
function folder(){if(props.work.busy.value){props.work.notify('请等待当前任务或上传结束');return;}folderPath.value=props.work.s.localFolder||'';folderError.value='';folderOpen.value=true;}
async function pick(){folderBusy.value=true;folderError.value='请在本机窗口中选择目录…';try{const result=await action('/api/folders/pick');if(result.path)folderPath.value=result.path;folderError.value='';}catch(error){folderError.value=error.message;}finally{folderBusy.value=false;}}
async function bind(){folderBusy.value=true;folderError.value='';try{await props.work.bindFolder(folderPath.value.trim());folderOpen.value=false;}catch(error){folderError.value=error.message;}finally{folderBusy.value=false;}}
function drop(event){dragging.value=false;const entries=[...(event.dataTransfer?.items||[])].map(item=>item.webkitGetAsEntry?.()).filter(Boolean);if(entries.some(entry=>entry.isDirectory)){folder();props.work.notify('文件夹只需连接目录，请选择或粘贴本机路径。');return;}props.work.upload([...(event.dataTransfer?.files||[])]);}
async function approve(id,allow){approvalBusy.value=id;try{await props.work.approve(id,allow);}catch(error){props.work.notify(error.message);}finally{approvalBusy.value=null;}}
function focus(){prompt.value?.focus();}
onMounted(()=>window.addEventListener('ecoder-focus-prompt',focus));
onBeforeUnmount(()=>window.removeEventListener('ecoder-focus-prompt',focus));
</script>
<template>
  <section class="conversation" :class="{dragging}" @dragover.prevent="dragging=true" @dragleave.self="dragging=false" @drop.prevent="drop">
    <div class="conversation-heading"><div><span class="status-dot" :class="{'running-dot':work.s.running}"/><strong>{{work.title.value}}</strong></div><button class="quiet" @click="$emit('inspector')">执行面板<Icon name="panel"/></button></div>
    <div id="messages" ref="messages" class="messages" aria-live="polite" @scroll="scroll">
      <div v-if="!work.s.messages.length&&!work.s.loading" class="welcome"><img class="welcome-art" src="/static/assets/code-studio.svg" width="300" height="190" alt=""><h1>从一个想法，到一段好代码。</h1><p>描述你的编程需求，从当前项目开始。<br>你可以随时查看工具调用、任务进展和待确认的修改。</p><div class="welcome-footer"><span><Icon name="check"/>按需加载 Skills</span><span><Icon name="check"/>修改前预览 diff</span><span><Icon name="check"/>执行过程可回放</span></div></div>
      <div v-if="work.s.loading" class="working">正在读取会话…</div>
      <template v-for="message in work.s.messages" :key="message.key"><div v-if="message.role==='notice'" class="notice">{{message.text}}</div><article v-else class="message" :class="message.role"><div class="avatar">{{message.role==='user'?'你':'E_'}}</div><div class="message-body"><MarkdownText v-if="message.role==='assistant'" class="message-content" :text="message.text"/><div v-else class="message-content">{{message.text}}</div><FileAttachments :files="message.attachments" :session="work.s.session" :available="work.s.attachmentIds"/></div></article></template>
      <div v-if="work.s.running" class="working">正在处理，执行详情见右侧面板…</div><div v-if="work.s.streamError" class="notice">执行连接暂时断开，正在自动重连…</div>
    </div>
    <div class="composer-wrap">
      <div class="approval-area"><div v-for="approval in work.s.approvals" :key="approval.approval_id" class="approval"><div class="approval-title">{{approval.name==='run_command'?'允许执行这条命令？':'确认这次文件修改？'}}<span>仅批准本次 · 3 分钟内有效</span></div><p v-if="approval.preview.warning">{{approval.preview.warning}}</p><pre v-if="approval.preview.diff"><span v-for="(line,index) in approval.preview.diff.split('\n')" :key="index" :class="line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':''">{{line+'\n'}}</span></pre><pre v-else>{{pretty(approval.preview.command)}}</pre><div class="approval-buttons"><button class="reject" :disabled="approvalBusy===approval.approval_id" @click="approve(approval.approval_id,false)">拒绝</button><button class="approve" :disabled="approvalBusy===approval.approval_id" @click="approve(approval.approval_id,true)">批准并执行</button></div></div></div>
      <div v-if="work.s.uploading" class="upload-status" role="status">正在上传文件…</div>
      <form class="composer" @submit.prevent="work.send"><div v-if="work.s.localFolder" class="selected-folder"><button class="folder-connection" type="button" :title="work.s.localFolder" :disabled="work.busy.value" @click="folder"><Icon name="folder"/><span>{{work.s.localFolder.split(/[\\/]/).at(-1)}}</span><small>已连接</small></button></div>
      <div v-if="work.s.pending.length" class="pending-attachments"><div v-for="file in work.s.pending" :key="file.id" class="attachment-chip"><img v-if="imageFile(file)" :src="`/api/sessions/${work.s.session}/images/${file.id}`" :alt="file.path"><Icon v-else name="paperclip"/><span class="attachment-name">{{file.path}}</span><button type="button" class="remove-attachment" :disabled="work.busy.value" :aria-label="`移除附件：${file.path}`" title="从本条消息移除，文件仍保留" @click="work.s.pending=work.s.pending.filter(item=>item.id!==file.id)">×</button></div></div>
      <label for="prompt" class="sr-only">编程任务</label><textarea id="prompt" ref="prompt" v-model="work.s.prompt" rows="2" maxlength="20000" placeholder="描述你想实现的功能，或一起排查一个问题…" :disabled="work.s.loading" @keydown="key" @paste="paste"/>
      <div class="composer-bottom"><div class="attachment-actions"><button type="button" aria-label="上传图片" :disabled="work.busy.value" @click="imageInput.click()"><Icon name="image"/><span>图片</span></button><button type="button" aria-label="上传文件" :disabled="work.busy.value" @click="fileInput.click()"><Icon name="paperclip"/><span>文件</span></button><button type="button" aria-label="选择本地文件夹" :disabled="work.busy.value" @click="folder"><Icon name="folder"/><span>文件夹</span></button></div><div><button v-if="work.s.running" type="button" class="stop" @click="work.safe(work.stop)">停止运行</button><button type="submit" class="send" :disabled="work.busy.value||!work.s.status">发送<Icon name="send"/></button></div></div></form>
    </div>
    <input ref="fileInput" type="file" multiple hidden @change="choose"><input ref="imageInput" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden @change="choose">
  </section>
  <BaseDialog class="folder-dialog" :open="folderOpen" :busy="folderBusy" labelledby="folder-title" @close="folderOpen=false"><form @submit.prevent="bind"><div class="manager-heading"><h2 id="folder-title">选择本地文件夹</h2><button type="button" class="quiet" aria-label="关闭文件夹选择" :disabled="folderBusy" @click="folderOpen=false">关闭 ×</button></div><p>仅连接目录，Agent 按需读取文件。修改会保存到原文件夹。</p><label for="folder-path">文件夹路径</label><input id="folder-path" v-model="folderPath" required autocomplete="off" placeholder="粘贴本机文件夹的完整路径"><div class="folder-dialog-actions"><button type="button" class="secondary" :disabled="folderBusy" @click="pick">浏览本机目录</button><button type="submit" class="save-config" :disabled="folderBusy">使用此文件夹</button></div><p id="folder-error" role="status">{{folderError}}</p></form></BaseDialog>
</template>
