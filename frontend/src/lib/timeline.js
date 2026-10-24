const relevant=new Set(['run_start','step_start','tool_start','tool_end','approval_request','approval_result','context_compact','notice','error','run_end','subagent_start','subagent_end']);
const statuses={completed:'已完成',failed:'失败',cancelled:'已停止',limit_reached:'达到上限',interrupted:'已中断'};

export class ExecutionSummary {
  constructor(){this.reset();}
  reset(){this.runs=[];this.byId=new Map();this.titles=new Map();this.approvals=new Map();this.current=null;}
  accept(event){
    if(event.type==='user_message'){this.titles.set(event.run_id,event.content?.split('\n')[0].slice(0,60)||'编程任务');return null;}
    if(!relevant.has(event.type))return null;
    const id=event.run_id||(event.type==='run_start'?`legacy-${this.runs.length+1}`:this.current?.id)||'legacy-1';
    let run=this.byId.get(id);
    if(!run){run={id,index:this.runs.length+1,title:this.titles.get(event.run_id)||'编程任务',time:event.time,steps:new Set(),tools:new Map(),notes:new Set(),compactions:0,status:null,elapsed:0};this.byId.set(id,run);this.runs.push(run);}
    this.current=run;
    if(event.type==='step_start')run.steps.add(event.subagent_id?`${event.subagent_id}:${event.step??event.seq}`:event.step??event.seq??run.steps.size+1);
    if(event.type==='subagent_start')run.notes.add(`子 Agent ${event.subagent_id.slice(0,8)} 开始执行`);
    if(event.type==='subagent_end')run.notes.add(`子 Agent ${event.subagent_id.slice(0,8)}：${statuses[event.status]||event.status}（${event.steps} 次模型调用）`);
    if(event.type==='tool_start'){
      const existing=run.tools.get(event.call_id);
      run.tools.set(event.call_id,{...existing,id:event.call_id,name:event.name,subagent:event.subagent_id,arguments:event.arguments,result:existing?.result,status:existing?.status||'执行中'});
    }
    if(event.type==='tool_end'){
      const call=run.tools.get(event.call_id)||{id:event.call_id,name:event.name};
      Object.assign(call,{result:event.result,status:event.result?.error?'失败 / 拒绝':'已完成',elapsed:event.elapsed_ms});run.tools.set(event.call_id,call);
    }
    if(event.type==='approval_request'){
      this.approvals.set(event.approval_id,{run,call:event.call_id});
      const call=run.tools.get(event.call_id);if(call)call.approval='等待审批';
    }
    if(event.type==='approval_result'){
      const target=this.approvals.get(event.approval_id);
      if(target){const call=target.run.tools.get(target.call);if(call)call.approval=event.allowed?'已批准':event.reason==='timeout'?'审批超时':'已拒绝';return target.run;}
    }
    if(event.type==='context_compact')run.compactions++;
    if(event.type==='notice'||event.type==='error')run.notes.add(event.content);
    if(event.type==='run_end'){run.status=event.status;run.elapsed=event.elapsed_ms||0;}
    return run;
  }
}

