import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {defineComponent,nextTick} from 'vue';
import {flushPromises,mount} from '@vue/test-utils';
import {useWorkbench} from './composables/useWorkbench.js';
import MarkdownText from './components/MarkdownText.vue';
import BaseDialog from './components/BaseDialog.vue';
import LibraryDetails from './components/LibraryDetails.vue';
import SettingsPage from './components/SettingsPage.vue';
import StoragePage from './components/StoragePage.vue';
import CronPanel from './components/CronPanel.vue';
import GoalPanel from './components/GoalPanel.vue';

let wrappers=[];
function render(component,options={}){const wrapper=mount(component,options);wrappers.push(wrapper);return wrapper;}
function createWork(){let work;render(defineComponent({setup(){work=useWorkbench();return()=>null;}}));return work;}
const respond=value=>({ok:true,json:async()=>value});
const status={configured:true,model:'model-id',base_url:'https://provider.test/v1',context_chars:60000,max_steps:30,skills:[],tools:[]};
const emptySession={events:[],messages:[],attachments:[],approvals:[],tasks:[],memory:'',local_folder:null,running:false};
const snapshot={bytes:10,files:[{id:'signed-snapshot-token',name:'a.txt',path:'session/a.txt',kind:'uploads',size:10,session_title:'会话'}],totals:{uploads:{bytes:10,files:1},default:{bytes:0,files:0}},folders:[],locations:{uploads:'uploads',default:'default_workspace'},orphan_files:0,orphan_bytes:0};
beforeEach(()=>{
  localStorage.clear();
  vi.stubGlobal('fetch',vi.fn(async url=>respond(url==='/api/status'?status:url==='/api/sessions'?[]:url==='/api/storage'?snapshot:String(url).includes('/files')?{files:[]}:emptySession)));
  vi.stubGlobal('EventSource',class{static instances=[];static CLOSED=2;constructor(url){this.url=url;this.close=vi.fn();this.addEventListener=vi.fn();EventSource.instances.push(this);}});
  HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new Event('close'));};
});
afterEach(()=>{for(const wrapper of wrappers)wrapper.unmount();wrappers=[];document.body.innerHTML='';vi.unstubAllGlobals();});

describe('stream/session migration',()=>{
  it('handles /goal status without inventing an active model run',async()=>{
    const work=createWork();work.s.session='s';work.s.prompt='/goal';
    fetch.mockResolvedValue(respond({run_id:null,goal:{id:'g',status:'paused',condition:'verify'}}));
    await work.send();expect(work.s.running).toBe(false);expect(work.s.goal.status).toBe('paused');
    expect(work.s.tab).toBe('goal');expect(EventSource.instances).toHaveLength(0);
  });
  it('starts and controls goals using explicit session endpoints',async()=>{
    const work=createWork();work.s.session='s';
    fetch.mockImplementation(async(url,options)=>respond({run_id:options?.body?.includes('pause')?null:'run',goal:{id:'g',condition:'verify',status:options?.body?.includes('pause')?'paused':'active'}}));
    await work.startGoal('verify');expect(work.s.goal.status).toBe('active');expect(work.s.running).toBe(true);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({condition:'verify'});
    await work.controlGoal('pause');expect(work.s.goal.status).toBe('paused');expect(work.s.goalBusy).toBe(false);
    work.receive({seq:1,type:'goal_status',goal:{id:'g',status:'achieved'}});expect(work.s.goal.status).toBe('achieved');
  });
  it('keeps an event stream for idle sessions with cron jobs and receives scheduled starts',async()=>{
    const job={id:'cron_1',cron:'0 9 * * *',prompt:'scheduled task'};
    fetch.mockImplementation(async url=>respond(String(url).includes('/files')?{files:[]}:{...emptySession,events:[],crons:[job]}));
    const work=createWork();await work.openSession('scheduled');
    expect(work.s.running).toBe(false);expect(work.s.crons).toEqual([job]);expect(EventSource.instances).toHaveLength(1);
    const waiting=EventSource.instances[0].addEventListener.mock.calls.find(([name])=>name==='waiting')[1];waiting();
    expect(work.s.runLabel).toBe('等待定时任务');
    work.receive({seq:1,type:'run_start',schedule_id:job.id});expect(work.s.running).toBe(true);
    work.receive({seq:2,type:'crons_update',crons:[]});expect(work.s.crons).toEqual([]);
  });
  it('creates and cancels cron jobs through session endpoints',async()=>{
    const work=createWork();work.s.session='s';let jobs=[];
    fetch.mockImplementation(async(url,options)=>{if(options?.method==='POST'){jobs=[{id:'cron_1',...JSON.parse(options.body)}];return respond(jobs[0]);}
      if(options?.method==='DELETE'){jobs=[];return respond({cancelled:true});}return respond({crons:jobs});});
    const job={cron:'0 9 * * *',prompt:'inspect tests',recurring:true,durable:true};
    await work.createCron(job);expect(work.s.crons[0].prompt).toBe(job.prompt);expect(work.s.scheduling).toBe(false);
    expect(fetch.mock.calls[0][0]).toBe('/api/sessions/s/crons');expect(EventSource.instances).toHaveLength(1);
    await work.cancelCron('cron_1');expect(work.s.crons).toEqual([]);
    expect(fetch.mock.calls.some(([url,options])=>url==='/api/sessions/s/crons/cron_1'&&options?.method==='DELETE')).toBe(true);
  });
  it('does not apply stale cron refreshes after switching sessions',async()=>{
    const work=createWork();work.s.session='old';let release;
    fetch.mockImplementation(()=>new Promise(resolve=>release=resolve));const pending=work.refreshCrons();
    work.s.session='new';work.s.crons=[{id:'new'}];release(respond({crons:[{id:'old'}]}));await pending;
    expect(work.s.crons).toEqual([{id:'new'}]);
  });
  it('counts child model calls without mixing child text into parent chat, including replay',()=>{
    const events=[{type:'run_start',run_id:'r'},{type:'step_start',run_id:'r',step:1},{type:'text_delta',content:'parent '},
      {type:'usage',total_tokens:10},{type:'subagent_start',run_id:'r',subagent_id:'child-id'},
      {type:'step_start',run_id:'r',subagent_id:'child-id',step:1},{type:'subagent_text_delta',content:'private child text'},
      {type:'usage',total_tokens:20},{type:'subagent_end',run_id:'r',subagent_id:'child-id',status:'completed',steps:1},
      {type:'text_delta',content:'continued'},{type:'step_start',run_id:'r',step:2},{type:'text_delta',content:'final'}];
    const live=createWork(),replay=createWork();
    events.forEach((event,index)=>{const item={...event,seq:index+1};live.receive(item);replay.receive(item,true);});
    expect(live.s.messages.map(row=>row.text)).toEqual(['parent continued','final']);
    expect(replay.s.messages).toEqual(live.s.messages);
    expect(live.s.usage).toMatchObject({calls:3,tokens:30});
    expect(live.s.runs[0].steps).toBe(3);
    expect(live.s.runs[0].notes.join(' ')).toContain('子 Agent');
  });
  it('deduplicates SSE replay and assembles one assistant bubble per step',()=>{
    const work=createWork();
    for(const event of [{seq:1,type:'user_message',content:'hello'},{seq:2,type:'step_start',step:1},{seq:3,type:'text_delta',content:'A'},{seq:3,type:'text_delta',content:'A'},{seq:4,type:'text_delta',content:'B'},{seq:5,type:'step_start',step:2},{seq:6,type:'text_delta',content:'C'}])work.receive(event);
    expect(work.s.messages.map(row=>row.text)).toEqual(['hello','AB','C']);expect(work.s.usage.calls).toBe(2);
  });
  it('uses cumulative usage snapshots instead of adding every delta',()=>{
    const work=createWork();let seq=0;for(const event of [{type:'step_start',step:1},{type:'usage',total_tokens:10},{type:'usage',total_tokens:12},{type:'usage',total_tokens:11},{type:'step_start',step:2},{type:'usage',total_tokens:5}])work.receive({...event,seq:++seq});
    expect(work.s.usage).toMatchObject({calls:2,tokens:17});
  });
  it('keeps old-session responses from overwriting the newly selected session',async()=>{
    let resolveOld;fetch.mockImplementation(async url=>String(url).endsWith('/old')?new Promise(resolve=>resolveOld=resolve):respond(String(url).includes('/files')?{files:[]}: {...emptySession,memory:'new'}));
    const work=createWork(),first=work.openSession('old');await flushPromises();await work.openSession('new');resolveOld(respond({...emptySession,memory:'stale'}));await first;
    expect(work.s.session).toBe('new');expect(work.s.memory).toBe('new');
  });
  it('closes the previous EventSource when changing sessions and unmounting',async()=>{
    fetch.mockImplementation(async url=>respond(String(url).includes('/files')?{files:[]}:{...emptySession,running:true}));const work=createWork();await work.openSession('one');const first=EventSource.instances[0];await work.openSession('two');expect(first.close).toHaveBeenCalled();work.dispose();expect(EventSource.instances[1].close).toHaveBeenCalled();
  });
  it('does not send duplicate runs while the initial POST is pending',async()=>{
    const work=createWork();work.s.session='s';work.s.prompt='task';let release;fetch.mockImplementation(()=>new Promise(resolve=>release=resolve));const first=work.send();await work.send();expect(fetch).toHaveBeenCalledTimes(1);release(respond({run_id:'r'}));await first;expect(EventSource.instances).toHaveLength(1);expect(work.s.prompt).toBe('');
  });
  it('retains the draft if the run request fails',async()=>{
    const work=createWork();work.s.session='s';work.s.prompt='keep draft';fetch.mockResolvedValue({ok:false,json:async()=>({detail:'failed'})});await work.send();expect(work.s.prompt).toBe('keep draft');expect(work.s.running).toBe(false);expect(work.s.toast).toBe('failed');
  });
  it('restores pending approvals and updates task state from live events',async()=>{
    fetch.mockImplementation(async url=>respond(String(url).includes('/files')?{files:[]}:{...emptySession,approvals:[{approval_id:'a'}]}));const work=createWork();await work.openSession('s');expect(work.s.approvals).toHaveLength(1);work.receive({seq:1,type:'approval_result',approval_id:'a'});work.receive({seq:2,type:'tasks_update',tasks:[{id:'t'}]});expect(work.s.approvals).toHaveLength(0);expect(work.s.tasks[0].id).toBe('t');
  });
  it('binds a folder by path without uploading its files or adding attachments',async()=>{
    const work=createWork();work.s.session='s';fetch.mockImplementation(async url=>respond(String(url).endsWith('/folder')?{path:'D:/project'}:{files:[],local_folder:'D:/project'}));await work.bindFolder('D:/project');expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({path:'D:/project'});expect(fetch.mock.calls.every(([url])=>!url.includes('/uploads'))).toBe(true);expect(work.s.pending).toHaveLength(0);
  });
  it('refreshes removed attachment ids after storage cleanup',async()=>{
    const work=createWork();work.s.session='s';work.s.pending=[{id:'removed'},{id:'kept'}];fetch.mockImplementation(async url=>respond(String(url).includes('/files')?{files:[]}:{...emptySession,attachments:[{id:'kept'}]}));await work.afterClean();expect([...work.s.attachmentIds]).toEqual(['kept']);expect(work.s.pending).toEqual([{id:'kept'}]);
  });
});

describe('Vue components',()=>{
  it('exposes independent goal progress and resume controls',async()=>{
    const work=createWork();work.controlGoal=vi.fn(async()=>{});work.startGoal=vi.fn(async()=>{});
    work.s.goal={id:'g',status:'paused',condition:'verify tests',evaluations:2,agent_calls:3,judge_calls:2,reported_calls:0,reason:'waiting'};
    const wrapper=render(GoalPanel,{props:{work}});expect(wrapper.text()).toContain('已暂停');expect(wrapper.text()).toContain('尚未提供');
    await wrapper.find('textarea').setValue('new condition');await wrapper.find('form').trigger('submit');await flushPromises();
    expect(work.startGoal).toHaveBeenCalledWith('new condition');
    const resume=wrapper.findAll('button').find(button=>button.text()==='恢复执行');await resume.trigger('click');await flushPromises();
    expect(work.controlGoal).toHaveBeenCalledWith('resume');
  });
  it('creates a scheduled prompt and exposes cancellation in the cron panel',async()=>{
    const work=createWork();work.createCron=vi.fn(async()=>{});work.cancelCron=vi.fn(async()=>{});
    work.s.crons=[{id:'cron_1',prompt:'existing task',cron:'0 9 * * *',recurring:true,durable:true,pending_delivery:true}];
    const wrapper=render(CronPanel,{props:{work}});
    await wrapper.find('textarea').setValue('check files');await wrapper.find('form').trigger('submit');await flushPromises();
    expect(work.createCron).toHaveBeenCalledWith({cron:'0 9 * * *',prompt:'check files',recurring:true,durable:true});
    expect(wrapper.text()).toContain('等待交付');
    await wrapper.find('button[aria-label="取消定时任务 cron_1"]').trigger('click');await flushPromises();
    expect(work.cancelCron).toHaveBeenCalledWith('cron_1');
  });
  it('renders Markdown while removing executable HTML and unsafe links',()=>{
    const wrapper=render(MarkdownText,{props:{text:'## Title\n\n<script>alert(1)</script>\n[bad](javascript:alert(1)) [safe](https://example.com)\n<img src=x onerror=alert(1)>'}});
    expect(wrapper.find('h2').text()).toBe('Title');expect(wrapper.find('script').exists()).toBe(false);expect(wrapper.find('img').exists()).toBe(false);expect(wrapper.findAll('a').some(link=>link.attributes('href')?.startsWith('javascript:'))).toBe(false);expect(wrapper.find('a[href="https://example.com"]').attributes('rel')).toBe('noopener noreferrer');
  });
  it('renders streamed Markdown updates without duplicating content',async()=>{const wrapper=render(MarkdownText,{props:{text:'**hel'}});await wrapper.setProps({text:'**hello**'});expect(wrapper.find('strong').text()).toBe('hello');expect(wrapper.text()).toBe('hello');});
  it('keeps native dialog classes and uses cancel to request closing',async()=>{const wrapper=render(BaseDialog,{props:{open:true,labelledby:'title'},attrs:{class:'library-detail'},slots:{default:'detail'}});await nextTick();const dialog=document.querySelector('dialog');expect(dialog.open).toBe(true);expect(dialog.classList.contains('library-detail')).toBe(true);dialog.dispatchEvent(new Event('cancel',{cancelable:true}));expect(wrapper.emitted('close')).toHaveLength(1);});
  it('does not apply a slow skill response to a newly opened tool',async()=>{
    let release;fetch.mockImplementation(()=>new Promise(resolve=>release=resolve));const wrapper=render(LibraryDetails,{props:{detail:{kind:'skill',item:{name:'old'}}}});await flushPromises();await wrapper.setProps({detail:{kind:'tool',item:{name:'read_file',permission:'read',schema:{properties:{path:{type:'string'}},required:['path']}}}});release(respond({content:'# stale'}));await flushPromises();expect(document.querySelector('dialog').textContent).toContain('read_file');expect(document.querySelector('dialog').textContent).not.toContain('stale');
  });
  it('keeps the saved API key on an empty edit without storing credentials in the browser',async()=>{
    const work=createWork();work.s.status=status;const wrapper=render(SettingsPage,{props:{work}});await wrapper.find('form').trigger('submit');await flushPromises();const post=fetch.mock.calls.find(([url,options])=>url==='/api/config'&&options?.method==='POST');expect(JSON.parse(post[1].body)).not.toHaveProperty('api_key');expect(localStorage.length).toBe(0);
  });
  it('clears a newly entered key after saving',async()=>{
    const work=createWork();work.s.status=status;const wrapper=render(SettingsPage,{props:{work}});await wrapper.find('#config-api_key').setValue('test-only-key');await wrapper.find('form').trigger('submit');await flushPromises();expect(wrapper.find('#config-api_key').element.value).toBe('');expect(localStorage.length).toBe(0);
  });
  it('requires explicit confirmation and preserves signed cleanup tokens',async()=>{
    const work=createWork();work.s.status=status;const wrapper=render(StoragePage,{props:{work}});await flushPromises();await wrapper.find('tbody input').setValue(true);await wrapper.find('.storage-selection .storage-danger').trigger('click');await nextTick();expect(fetch.mock.calls.some(([url])=>url==='/api/storage/delete')).toBe(false);const dialog=document.querySelector('dialog');expect(dialog.open).toBe(true);fetch.mockImplementation(async url=>respond(url==='/api/storage/delete'?{deleted:1,released_bytes:10,failed:[]}:snapshot));dialog.querySelector('.storage-confirm-actions .storage-danger').click();await flushPromises();const call=fetch.mock.calls.find(([url])=>url==='/api/storage/delete');expect(JSON.parse(call[1].body)).toEqual({files:['signed-snapshot-token']});
  });
});
