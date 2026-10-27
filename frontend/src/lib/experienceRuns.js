export function completedTasks(events=[]){
  const tasks=new Map();let current=null,pending='';
  for(const event of events){
    if(event.type==='user_message')pending=event.content||'';
    const id=event.run_id||current;
    if(!id)continue;
    let task=tasks.get(id);
    if(!task){task={id,prompt:'',answer:'',time:null,tools:[],status:null};tasks.set(id,task);}
    if(event.type==='user_message')task.prompt=event.content||'';
    if(event.type==='run_start'){current=id;task.prompt=task.prompt||pending;task.time=event.time;pending='';}
    if(event.type==='step_start'&&!event.subagent_id)task.answer='';
    if(event.type==='text_delta'&&!event.subagent_id)task.answer=(task.answer+event.content).slice(-12000);
    if(event.type==='tool_end'){
      const result=event.result;
      const ok=!(result&&typeof result==='object'&&(result.error||(result.exit_code!==undefined&&result.exit_code!==0)));
      task.tools.push({seq:event.seq,name:event.name||'工具调用',ok,result});
    }
    if(event.type==='run_end'){task.status=event.status;task.time=task.time||event.time;}
  }
  return [...tasks.values()].filter(task=>task.status==='completed').map((task,index)=>({...task,
    title:task.prompt.trim().split('\n').find(line=>line.trim())?.replace(/\s+/g,' ').slice(0,70)||`任务 ${index+1}（原始需求未记录）`,
    successTools:task.tools.filter(tool=>tool.ok).length
  })).reverse();
}
export function taskTime(value){
  if(!value)return '时间未记录';
  const date=new Date(typeof value==='number'?value*1000:value);
  return Number.isNaN(date.getTime())?'时间未记录':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date);
}

export function shortPrompt(value,limit=18){
  const characters=Array.from(String(value||'').replace(/\s+/g,' ').trim());
  return characters.length>limit?characters.slice(0,limit).join('')+'…':characters.join('');
}
