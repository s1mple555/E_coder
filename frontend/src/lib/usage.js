// Each streamed usage event is a cumulative snapshot for one model request.
export class SessionUsage {
  constructor() { this.reset(); }
  reset() { this.calls=0;this.completed=0;this.current=null;this.open=false;this.reported=0; }
  finish() {
    if(this.current!==null){this.completed+=this.current;this.reported++;}
    this.current=null;this.open=false;
  }
  accept(event) {
    if(event.type==='run_start'){this.finish();}
    if(event.type==='step_start') { this.finish();this.calls++;this.open=true; }
    if(event.type==='usage') {
      if(!this.open){this.calls++;this.open=true;}
      const valid=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0;
      const total=valid(event.total_tokens)?event.total_tokens:
        valid(event.prompt_tokens)&&valid(event.completion_tokens)?event.prompt_tokens+event.completion_tokens:null;
      if(total!==null)this.current=Math.max(this.current??0,total);
    }
    return {calls:this.calls,tokens:this.completed+(this.current??0),
      reported:this.reported+(this.current===null?0:1)};
  }
}
