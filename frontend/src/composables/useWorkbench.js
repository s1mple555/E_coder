import {computed,reactive,onBeforeUnmount} from 'vue';
import {api,action,imageFile} from '../lib/api.js';
import {SessionUsage} from '../lib/usage.js';
import {ExecutionSummary} from '../lib/timeline.js';

export function useWorkbench(){
  const s=reactive({status:null,page:'chat',tab:'timeline',sessions:[],session:null,messages:[],events:[],tasks:[],crons:[],goal:null,goalBusy:false,scheduling:false,memory:'',historyCount:0,
    running:false,loading:false,uploading:false,creating:false,submitting:false,approvals:[],runs:[],usage:{calls:0,tokens:0,reported:0},
    pending:[],files:[],attachmentIds:new Set(),localFolder:null,fileDirectory:'',filesTruncated:false,prompt:'',toast:'',runLabel:'就绪',streamError:false});
  let stream=null,cursor=0,assistantIndex=null,revision=0,fileRevision=0,timer;
  const usage=new SessionUsage(),summary=new ExecutionSummary();
  const busy=computed(()=>s.running||s.loading||s.uploading||s.creating||s.submitting||s.goalBusy);
  const title=computed(()=>s.sessions.find(row=>row.id===s.session)?.title||'新的编程任务');
  const compact=computed(()=>s.events.filter(event=>event.type==='context_compact').at(-1));
  function notify(message){s.toast=message;clearTimeout(timer);timer=setTimeout(()=>s.toast='',5500);}
  const safe=fn=>Promise.resolve().then(fn).catch(error=>notify(error.message));
  function disconnect(){stream?.close();stream=null;}
  function reset(){
    disconnect();cursor=0;assistantIndex=null;usage.reset();summary.reset();
    Object.assign(s,{messages:[],events:[],tasks:[],crons:[],goal:null,memory:'',historyCount:0,approvals:[],runs:[],usage:{calls:0,tokens:0,reported:0},
      pending:[],files:[],attachmentIds:new Set(),localFolder:null,fileDirectory:'',filesTruncated:false,running:false,runLabel:'就绪',streamError:false});
  }
  function updateSummary(event){
    if(!summary.accept(event))return;
    s.runs=summary.runs.map(run=>({...run,steps:run.steps.size,tools:[...run.tools.values()].map(tool=>({...tool})),notes:[...run.notes]}));
  }
  function receive(event,replay=false){
    if(!replay&&event.seq<=cursor)return;
    cursor=Math.max(cursor,event.seq||0);
    if(!replay)s.events.push(event);
    updateSummary(event);
    if(['run_start','step_start','usage'].includes(event.type))s.usage=usage.accept(event);
    switch(event.type){
      case 'user_message': assistantIndex=null;s.messages.push({key:`user-${event.seq}`,role:'user',text:event.content,attachments:event.attachments||[]});break;
      case 'run_start': if(!replay){s.running=true;s.runLabel='运行中';}break;
      case 'step_start': if(!event.subagent_id)assistantIndex=null;break;
      case 'text_delta':
        if(assistantIndex===null){assistantIndex=s.messages.length;s.messages.push({key:`assistant-${event.seq}`,role:'assistant',text:'',attachments:[]});}
        s.messages[assistantIndex].text+=event.content;break;
      case 'approval_request': if(!replay&&!s.approvals.some(a=>a.approval_id===event.approval_id))s.approvals.push(event);break;
      case 'approval_result': s.approvals=s.approvals.filter(a=>a.approval_id!==event.approval_id);break;
      case 'tasks_update': if(!replay)s.tasks=event.tasks;break;
      case 'crons_update': if(!replay)s.crons=event.crons;break;
      case 'goal_status': if(!replay)s.goal=event.goal;break;
      case 'notice':case 'error':s.messages.push({key:`notice-${event.seq}`,role:'notice',text:event.content});break;
      case 'run_end':
        if(!replay){
          s.running=false;s.approvals=[];s.runLabel=({completed:'已结束',failed:'运行失败',cancelled:'已停止',limit_reached:'达到上限',interrupted:'服务已重启'})[event.status]||event.status;
          const id=s.session;safe(refreshSessions);safe(()=>refreshFiles(s.fileDirectory));
          safe(async()=>{const data=await api(`/api/sessions/${id}`);if(s.session===id){s.tasks=data.tasks;s.crons=data.crons||[];s.goal=data.goal||null;s.memory=data.memory;s.historyCount=data.messages.length;}});
        }break;
    }
  }
  function connect(){
    disconnect();const id=s.session;s.streamError=false;
    const current=new EventSource(`/api/sessions/${id}/stream?after=${cursor}`);stream=current;
    current.onmessage=message=>{if(s.session!==id||stream!==current)return;try{receive(JSON.parse(message.data));}catch{notify('执行事件解析失败，请重新连接。');}};
    current.addEventListener('idle',()=>{current.close();if(stream===current)stream=null;});
    current.addEventListener('waiting',()=>{if(stream===current&&!s.running)s.runLabel='等待定时任务';});
    current.onerror=()=>{if(stream===current&&(s.running||s.crons.length))s.streamError=true;};
    current.onopen=()=>{if(stream===current)s.streamError=false;};
  }
  async function loadStatus(){s.status=await api('/api/status');}
  async function refreshSessions(){s.sessions=await api('/api/sessions');}
  async function refreshFiles(directory=''){
    const id=s.session,request=++fileRevision;if(!id){s.files=[];return;}
    const data=await api(`/api/sessions/${id}/files?path=${encodeURIComponent(directory)}`);
    if(id!==s.session||request!==fileRevision)return;
    Object.assign(s,{files:data.files,fileDirectory:data.directory||'',localFolder:data.local_folder||s.localFolder,filesTruncated:!!data.truncated});
  }
  async function openSession(id){
    if(s.uploading||s.creating||s.submitting){notify('请等待当前提交或上传完成');return;}
    const current=++revision;reset();s.session=id;s.loading=true;s.page='chat';s.prompt='';localStorage.setItem('ecoder-session',id);
    try{
      const data=await api(`/api/sessions/${id}`);if(current!==revision)return;
      s.events=data.events;s.attachmentIds=new Set((data.attachments||[]).map(file=>file.id));s.localFolder=data.local_folder;
      for(const event of data.events)receive(event,true);
      s.approvals=data.approvals;s.tasks=data.tasks;s.crons=data.crons||[];s.goal=data.goal||null;s.memory=data.memory;s.historyCount=data.messages.length;
      await refreshFiles();if(current!==revision)return;s.running=data.running;s.runLabel=data.running?'运行中':s.crons.length?'等待定时任务':'就绪';if(data.running||s.crons.length)connect();
    }catch(error){if(current===revision)notify(error.message);}finally{if(current===revision)s.loading=false;}
  }
  async function ensureSession(){
    if(s.session)return s.session;
    const created=await action('/api/sessions');s.session=created.id;localStorage.setItem('ecoder-session',created.id);await refreshSessions();return created.id;
  }
  async function newSession(){
    if(s.uploading||s.creating||s.submitting)return;s.creating=true;
    try{const created=await action('/api/sessions');await refreshSessions();s.creating=false;await openSession(created.id);}
    catch(error){notify(error.message);}finally{s.creating=false;}
  }
  async function deleteSession(id){
    if(s.uploading||s.submitting||s.loading){notify('请等待当前操作完成');return;}
    await api(`/api/sessions/${id}`,{method:'DELETE'});await refreshSessions();
    if(s.session===id){if(s.sessions.length)await openSession(s.sessions[0].id);else{revision++;reset();s.session=null;s.prompt='';localStorage.removeItem('ecoder-session');}}
    notify('任务及相关记录已永久删除。');
  }
  async function send(){
    if(busy.value||(!s.prompt.trim()&&!s.pending.length))return;
    s.submitting=true;const message=s.prompt.trim();let id=s.session;
    try{id=await ensureSession();const result=await action(`/api/sessions/${id}/runs`,{message,attachments:s.pending.map(file=>file.id)});
      if(s.session===id){s.prompt='';s.pending=[];if('goal' in result){s.goal=result.goal;s.tab='goal';}
        if(result.run_id!==null){s.running=true;s.runLabel='运行中';connect();}else{notify(result.message||'目标状态已更新');}}}
    catch(error){notify(error.message);}finally{s.submitting=false;}
  }
  async function stop(){if(s.session)await action(`/api/sessions/${s.session}/stop`);}
  async function refreshGoal(id=s.session){
    if(!id)return;const data=await api(`/api/sessions/${id}/goal`);if(s.session===id)s.goal=data.goal;
  }
  async function startGoal(condition){
    if(busy.value)return;s.goalBusy=true;
    try{const id=await ensureSession();const result=await action(`/api/sessions/${id}/goal`,{condition});
      if(s.session===id){s.goal=result.goal;s.tab='goal';s.running=true;s.runLabel='运行中';connect();}}
    finally{s.goalBusy=false;}
  }
  async function controlGoal(actionName){
    const id=s.session;if(!id||s.goalBusy)return;s.goalBusy=true;
    try{const result=await action(`/api/sessions/${id}/goal/control`,{action:actionName});
      if(s.session===id){s.goal=result.goal;if(result.run_id){s.running=true;s.runLabel='运行中';connect();}}}
    finally{s.goalBusy=false;}
  }
  async function refreshCrons(id=s.session){
    if(!id)return;const data=await api(`/api/sessions/${id}/crons`);if(s.session===id)s.crons=data.crons;
  }
  async function createCron(job){
    if(s.scheduling)return;s.scheduling=true;
    try{const id=await ensureSession();await action(`/api/sessions/${id}/crons`,job);
      if(s.session===id){await refreshCrons(id);if(s.session===id&&!stream)connect();notify('定时任务已创建。');}}
    finally{s.scheduling=false;}
  }
  async function cancelCron(jobId){
    const id=s.session;if(!id)return;await api(`/api/sessions/${id}/crons/${jobId}`,{method:'DELETE'});
    if(s.session===id){await refreshCrons(id);notify('定时任务已取消。');}
  }
  async function approve(id,allow){await action(`/api/sessions/${s.session}/approvals/${id}`,{allow});}
  function addFile(file){
    if(busy.value)return;
    if(!file.id){s.prompt+=`${s.prompt?'\n':''}请查看 ${file.path}`;return;}
    if(s.pending.some(item=>item.id===file.id))return;
    if(s.pending.length>=30){notify('每条消息最多选择 30 个附件。');return;}
    if(imageFile(file)&&(file.size>5*1048576||s.pending.filter(imageFile).length>=4)){notify('视觉输入每条最多 4 张图片，每张不超过 5 MB。');return;}
    s.pending.push(file);
  }
  async function upload(files){
    if(busy.value||!s.status){notify('请等待当前运行或上传完成。');return;}
    const kept=files.filter(file=>!file.name.split(/[\\/]/).some(part=>['.git','node_modules','.venv','__pycache__','.ecoder','.tools'].includes(part.toLowerCase())||/^\.env(?:\.|$)/i.test(part)));
    if(!kept.length){notify('没有可上传的文件，已跳过环境文件。');return;}
    if(kept.length>1000||kept.some(file=>file.size>20*1048576)||kept.reduce((sum,file)=>sum+file.size,0)>100*1048576){notify('每批最多 1000 个文件、100 MB；单文件最多 20 MB。');return;}
    s.uploading=true;
    try{const id=await ensureSession();const body=new FormData();for(const file of kept){body.append('files',file,file.name);body.append('paths',file.name);}
      const data=await api(`/api/sessions/${id}/uploads`,{method:'POST',body});
      if(s.session===id){for(const file of data.files){s.attachmentIds.add(file.id);if(s.pending.length<30&&(!imageFile(file)||(file.size<=5*1048576&&s.pending.filter(imageFile).length<4)))s.pending.push(file);}await refreshFiles();s.tab='files';}
      notify(`已上传 ${data.files.length} 个文件。`);
    }catch(error){notify(error.message);}finally{s.uploading=false;}
  }
  async function bindFolder(path){
    if(busy.value)throw new Error('请等待当前任务或上传结束');
    s.submitting=true;
    try{const id=await ensureSession();const folder=await action(`/api/sessions/${id}/folder`,{path});s.localFolder=folder.path;await refreshFiles();notify('已连接文件夹，Agent 将按需读取内容。');}
    finally{s.submitting=false;}
  }
  async function afterClean(){
    if(!s.session)return;const id=s.session;const data=await api(`/api/sessions/${id}`);if(id!==s.session)return;
    s.attachmentIds=new Set(data.attachments.map(file=>file.id));s.pending=s.pending.filter(file=>s.attachmentIds.has(file.id));await refreshFiles(s.fileDirectory);
  }
  async function initialize(){
    s.loading=true;
    try{await loadStatus();await refreshSessions();const saved=localStorage.getItem('ecoder-session');const chosen=s.sessions.find(row=>row.id===saved)||s.sessions[0];if(chosen)await openSession(chosen.id);}
    catch(error){notify(`启动失败：${error.message}`);}finally{s.loading=false;}
  }
  function dispose(){revision++;disconnect();clearTimeout(timer);}
  onBeforeUnmount(dispose);
  return {s,busy,title,compact,notify,safe,loadStatus,refreshSessions,refreshFiles,refreshCrons,createCron,cancelCron,refreshGoal,startGoal,controlGoal,openSession,newSession,deleteSession,send,stop,approve,addFile,upload,bindFolder,afterClean,initialize,receive,dispose};
}
