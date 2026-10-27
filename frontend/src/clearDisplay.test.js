import {afterEach,it,expect,vi} from 'vitest';
import {defineComponent} from 'vue';
import {mount} from '@vue/test-utils';
import {useWorkbench} from './composables/useWorkbench.js';
let panel;
afterEach(()=>{panel?.unmount();vi.unstubAllGlobals();});
function createWork(){let work;panel=mount(defineComponent({setup(){work=useWorkbench();return()=>null;}}));return work;}
it('clears only the projection and restores the same messages without network requests',()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);const work=createWork();
 work.receive({seq:1,type:'user_message',content:'first'});
 work.receive({seq:2,type:'text_delta',content:'answer'});
 const messages=work.s.messages,events=work.s.events;work.s.historyCount=9;work.s.tasks=[{id:'keep'}];work.s.approvals=[{approval_id:'keep'}];
 work.clearMessageDisplay();expect(work.visibleMessages.value).toEqual([]);
 expect(work.s.messages).toBe(messages);expect(work.s.messages).toHaveLength(2);expect(work.s.events).toBe(events);
 expect(work.s.historyCount).toBe(9);expect(work.s.tasks).toHaveLength(1);expect(work.s.approvals).toHaveLength(1);
 work.receive({seq:3,type:'user_message',content:'new'});work.receive({seq:4,type:'text_delta',content:'new answer'});
 expect(work.visibleMessages.value.map(m=>m.text)).toEqual(['new','new answer']);
 work.restoreMessageDisplay();expect(work.visibleMessages.value).toHaveLength(4);expect(fetch).not.toHaveBeenCalled();
});
it('keeps streaming updates attached to hidden messages and shows the next step',()=>{
 const work=createWork();work.receive({seq:1,type:'text_delta',content:'start'});work.clearMessageDisplay();
 work.receive({seq:2,type:'text_delta',content:' continued'});
 expect(work.s.messages[0].text).toBe('start continued');expect(work.visibleMessages.value).toEqual([]);
 work.receive({seq:3,type:'step_start'});work.receive({seq:4,type:'text_delta',content:'next'});
 expect(work.visibleMessages.value.map(m=>m.text)).toEqual(['next']);
});
it('restores the full event history when reopening a session',async()=>{
 const events=[{seq:1,type:'user_message',content:'saved'},{seq:2,type:'text_delta',content:'saved answer'}];
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>String(url).includes('/files')?{files:[]}:{events,messages:[{},{}],attachments:[],approvals:[],tasks:[],crons:[],running:false}})));
 const work=createWork();await work.openSession('session');work.clearMessageDisplay();expect(work.visibleMessages.value).toHaveLength(0);
 await work.openSession('session');expect(work.s.messageDisplayOffset).toBe(0);expect(work.visibleMessages.value.map(m=>m.text)).toEqual(['saved','saved answer']);
});
