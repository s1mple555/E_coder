import {it,expect} from 'vitest';
import {reactive,nextTick} from 'vue';
import {mount} from '@vue/test-utils';
import {groupTaskRounds} from './lib/taskRounds.js';
import TaskRounds from './components/TaskRounds.vue';
const a={id:'a',title:'检查代码',status:'pending',dependencies:[]};
const b={id:'b',title:'运行验证',status:'pending',dependencies:['a']};
const events=[
 {type:'user_message',run_id:'r1',content:'先检查代码'},{type:'run_start',run_id:'r1'},
 {type:'tool_end',run_id:'r1',name:'create_task',result:a},{type:'tasks_update',run_id:'r1',tasks:[a]},
 {type:'run_end',run_id:'r1',status:'completed'},
 {type:'user_message',run_id:'r2',content:'继续验证'},{type:'run_start',run_id:'r2'},
 {type:'tool_end',run_id:'r2',name:'update_task',result:{...a,status:'completed'}},
 {type:'tasks_update',run_id:'r2',tasks:[{...a,status:'completed'}]},
 {type:'tool_end',run_id:'r2',name:'create_task',result:b},
 {type:'tasks_update',run_id:'r2',tasks:[{...a,status:'completed'},b]},
 {type:'run_end',run_id:'r2',status:'completed'}];
it('groups by user-agent rounds and preserves each rounds task snapshot',()=>{
 const groups=groupTaskRounds(events,[{...a,status:'completed'},b]);
 expect(groups.map(group=>group.index)).toEqual([1,2]);
 expect(groups[0].tasks[0].status).toBe('pending');expect(groups[0].tasks[0].action).toBe('created');
 expect(groups[1].tasks.find(task=>task.id==='a').action).toBe('updated');
 expect(groups[1].tasks.find(task=>task.id==='b').dependencyTitles).toEqual(['检查代码']);
});
it('does not attribute unchanged full task snapshots or failed updates to later rounds',()=>{
 const groups=groupTaskRounds([...events,{type:'user_message',run_id:'r3',content:'聊一聊'},
 {type:'run_start',run_id:'r3'},{type:'tool_end',run_id:'r3',name:'update_task',result:{error:'denied'}},
 {type:'tasks_update',run_id:'r3',tasks:[{...a,status:'completed'},b]}]);
 expect(groups[2].index).toBe(3);expect(groups[2].tasks).toEqual([]);
});
it('keeps tasks with missing provenance separate rather than assigning them to a new chat',()=>{
 const groups=groupTaskRounds([],[a]);expect(groups[0].index).toBe(null);expect(groups[0].tasks[0].action).toBe('recorded');
});
it('renders the user-agent group labels and task dependencies',()=>{
 const panel=mount(TaskRounds,{props:{work:{s:{events,tasks:[{...a,status:'completed'},b],runs:[]}}}});
 expect(panel.text()).toContain('第1轮');expect(panel.text()).toContain('第2轮');expect(panel.text()).toContain('依赖：检查代码');panel.unmount();
});

it('appends new rounds below and automatically expands only the active round',async()=>{
 const work={s:reactive({events:events.slice(0,-1),tasks:[{...a,status:'completed'},b],runs:[],running:true})};
 const panel=mount(TaskRounds,{props:{work}});
 let details=panel.findAll('details');expect(details[0].element.open).toBe(false);expect(details[1].element.open).toBe(true);
 details[0].element.open=true;
 work.s.events=[...events,{type:'user_message',run_id:'r3',content:'第三轮任务'},{type:'run_start',run_id:'r3'}];work.s.runs=[];await nextTick();
 details=panel.findAll('details');expect(details.map(row=>row.find('strong').text())).toEqual(['第1轮','第2轮','第3轮']);
 expect(details.map(row=>row.element.open)).toEqual([false,false,true]);
 work.s.events=[...work.s.events,{type:'run_end',run_id:'r3',status:'completed'}];work.s.running=false;await nextTick();
 expect(panel.findAll('details').every(row=>!row.element.open)).toBe(true);panel.unmount();
});
