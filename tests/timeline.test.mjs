import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ExecutionSummary} from '../frontend/src/lib/timeline.js';

test('child steps and scoped tools remain distinct inside the parent round',()=>{
  const summary=new ExecutionSummary();
  for(const event of [{type:'run_start'},{type:'step_start',step:1},
    {type:'subagent_start',subagent_id:'child-123'},
    {type:'step_start',subagent_id:'child-123',step:1},
    {type:'tool_start',subagent_id:'child-123',call_id:'child-123:read',name:'read_file'},
    {type:'tool_end',subagent_id:'child-123',call_id:'child-123:read',name:'read_file',result:{text:'ok'}},
    {type:'subagent_end',subagent_id:'child-123',status:'completed',steps:1},
    {type:'step_start',step:2}])summary.accept({...event,run_id:'parent'});
  assert.equal(summary.runs.length,1);assert.equal(summary.runs[0].steps.size,3);
  assert.equal(summary.runs[0].tools.get('child-123:read').subagent,'child-123');
  assert.equal(summary.runs[0].notes.size,2);
});

test('hundreds of streamed fragments become one execution round',()=>{
  const summary=new ExecutionSummary();
  summary.accept({type:'user_message',run_id:'r1',content:'分析图片'});
  summary.accept({type:'run_start',run_id:'r1'});
  summary.accept({type:'step_start',run_id:'r1',step:1});
  for(let i=0;i<720;i++)assert.equal(summary.accept({type:i%2?'usage':'text_delta',run_id:'r1',content:'x',total_tokens:i}),null);
  summary.accept({type:'run_end',run_id:'r1',status:'completed',elapsed_ms:21200});
  assert.equal(summary.runs.length,1);assert.equal(summary.runs[0].steps.size,1);
  assert.equal(summary.runs[0].title,'分析图片');assert.equal(summary.runs[0].tools.size,0);
});
test('tool lifecycle and approval merge into one tool entry',()=>{
  const summary=new ExecutionSummary();
  for(const event of [{type:'run_start'},{type:'step_start',step:1},{type:'tool_start',call_id:'t1',name:'write_file',arguments:'{}'},
    {type:'approval_request',approval_id:'a1',call_id:'t1'},{type:'approval_result',approval_id:'a1',allowed:true},
    {type:'tool_end',call_id:'t1',name:'write_file',result:{bytes:42},elapsed_ms:3},{type:'step_start',step:2},
    {type:'run_end',status:'completed'}])summary.accept({...event,run_id:'r1'});
  const run=summary.runs[0];assert.equal(run.steps.size,2);assert.equal(run.tools.size,1);
  assert.equal(run.tools.get('t1').approval,'已批准');assert.equal(run.tools.get('t1').status,'已完成');
});
test('rounds remain separate; repeated notices merge and reset clears history',()=>{
  const summary=new ExecutionSummary();
  for(const run_id of ['r1','r2'])for(const event of [{type:'run_start'},{type:'notice',content:'请检查文件'},
    {type:'notice',content:'请检查文件'},{type:'context_compact'},{type:'context_compact'},{type:'run_end',status:'failed'}])summary.accept({...event,run_id});
  assert.equal(summary.runs.length,2);assert.equal(summary.runs[0].notes.size,1);assert.equal(summary.runs[1].compactions,2);
  summary.reset();assert.equal(summary.runs.length,0);
});
