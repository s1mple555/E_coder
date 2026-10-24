import {test} from 'node:test';
import assert from 'node:assert/strict';
import {SessionUsage} from '../frontend/src/lib/usage.js';

test('streamed snapshots count once per model call',()=>{
  const usage=new SessionUsage();
  usage.accept({type:'run_start'});
  usage.accept({type:'step_start'});
  for(const total_tokens of [2421,2422,2423,2439])usage.accept({type:'usage',total_tokens});
  assert.deepEqual(usage.accept({type:'run_end'}),{calls:1,tokens:2439,reported:1});
});
test('multiple tool steps and runs aggregate without double counting',()=>{
  const usage=new SessionUsage();
  for(let run=0;run<2;run++){
    usage.accept({type:'run_start'});
    for(let step=0;step<2;step++){
      usage.accept({type:'step_start'});
      usage.accept({type:'usage',total_tokens:10});
      usage.accept({type:'usage',prompt_tokens:10,completion_tokens:5});
    }
  }
  assert.deepEqual(usage.accept({type:'run_end'}),{calls:4,tokens:60,reported:4});
});
test('missing usage does not invent tokens; switching sessions resets totals',()=>{
  const usage=new SessionUsage();
  usage.accept({type:'step_start'});
  usage.accept({type:'usage',total_tokens:null});
  assert.deepEqual(usage.accept({type:'run_end'}),{calls:1,tokens:0,reported:0});
  usage.accept({type:'step_start'});
  usage.accept({type:'usage',total_tokens:20});
  assert.deepEqual(usage.accept({type:'run_end'}),{calls:2,tokens:20,reported:1});
  usage.reset();
  assert.deepEqual(usage.accept({type:'run_end'}),{calls:0,tokens:0,reported:0});
});
test('history replay and live updates use identical accounting',()=>{
  const events=[{type:'run_start'},{type:'step_start'},{type:'usage',total_tokens:8},{type:'usage',total_tokens:12},{type:'run_end'}];
  const replay=new SessionUsage(),live=new SessionUsage();
  let result;
  for(const event of events)result=replay.accept(event);
  for(const event of events)live.accept(event);
  assert.deepEqual(live.accept({type:'run_end'}),result);
});
