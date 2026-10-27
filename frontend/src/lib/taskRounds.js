export function groupTaskRounds(events=[],currentTasks=[]){
 const rounds=new Map(),known=new Map();let current=null;
 const snapshot=task=>({...task,dependencies:[...(task.dependencies||[])]});
 function round(id){if(!rounds.has(id))rounds.set(id,{id,index:rounds.size+1,prompt:'',time:null,status:null,tasks:new Map(),started:false});return rounds.get(id);}
 function touch(group,task,action){
  if(!task?.id)return;
  const previous=group.tasks.get(task.id);
  group.tasks.set(task.id,{...snapshot(task),action:previous?.action==='created'?'created':action});
  known.set(task.id,snapshot(task));
 }
 for(const event of events){
  if(event.subagent_id)continue;
  if(event.type==='user_message'){
   current=event.run_id||`legacy-${rounds.size+1}`;const group=round(current);group.prompt=event.content||'';group.time=event.time;continue;
  }
  if(event.type==='run_start'){
   current=event.run_id||((current&&!round(current).started)?current:`legacy-${rounds.size+1}`);
   const group=round(current);group.started=true;group.status='running';group.time=group.time||event.time;continue;
  }
  if(!['tool_end','tasks_update','run_end'].includes(event.type))continue;
  const id=event.run_id||current;if(!id)continue;
  const group=round(id);
  if(event.type==='run_end'){group.status=event.status;continue;}
  if(event.type==='tool_end'){
   if(event.result?.error)continue;
   if(['create_task','update_task'].includes(event.name))touch(group,event.result,event.name==='create_task'?'created':'updated');
   if(event.name==='list_tasks'&&Array.isArray(event.result))for(const task of event.result){if(!group.tasks.has(task.id))touch(group,task,'viewed');}
  }
  if(event.type==='tasks_update')for(const task of event.tasks||[]){
   const previous=known.get(task.id);
   if(!previous||previous.title!==task.title||previous.status!==task.status||JSON.stringify(previous.dependencies)!==JSON.stringify(task.dependencies||[]))touch(group,task,'updated');
   else known.set(task.id,snapshot(task));
  }
 }
 const recorded=new Set([...rounds.values()].flatMap(group=>[...group.tasks.keys()]));
 const unassigned=currentTasks.filter(task=>!recorded.has(task.id));
 const groups=[...rounds.values()].map(group=>({...group,tasks:[...group.tasks.values()]}));
 if(unassigned.length)groups.unshift({id:'unassigned',index:null,prompt:'这些历史任务没有可追溯的交互记录',status:null,tasks:unassigned.map(task=>({...snapshot(task),action:'recorded'}))});
 for(const task of currentTasks)known.set(task.id,snapshot(task));
 for(const group of groups)for(const task of group.tasks)task.dependencyTitles=task.dependencies.map(id=>known.get(id)?.title||'其他轮次的任务');
 return groups.filter(group=>group.index!==null).concat(groups.filter(group=>group.index===null));
}
