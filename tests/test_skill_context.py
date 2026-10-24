import json
import asyncio

from test_harness import harness
from test_skill_resources import add_skill


def history():
    return [{'role':'user','content':'use the skill'},
            {'role':'assistant','tool_calls':[{'id':'load-1','type':'function','function':{'name':'load_skill','arguments':'{"name":"resource-check"}'}}]},
            {'role':'tool','tool_call_id':'load-1','content':'{"skill":"resource-check","instructions":"old instructions; search .codex"}'}]


def test_skill_index_supplies_current_project_path_before_loading(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    (root/'runtime.conf').write_text('Runtime: Node.js\nArgv: [node, current-script.js]',encoding='utf-8')
    item=next(item for item in tools.skills.summary() if item['name']=='resource-check')
    assert item['directory']==str(root)
    assert item['configured_runtime']['Argv']==['node','current-script.js']
    assert 'content' not in item and 'instructions' not in item and 'resources' not in item


def test_old_skill_results_refresh_without_modifying_chat_history(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    messages=history()
    for message in messages:store.append(session,message)
    current=tools.skills.refresh_context(store.messages(session))
    loaded=json.loads(current[-1]['content'])
    assert loaded['directory']==str(root)
    assert 'scripts/check.py' in loaded['resources']
    assert '.codex' not in loaded['instructions']
    assert 'old instructions' in store.messages(session)[-1]['content']
    assert 'old instructions' in messages[-1]['content']
    # Reload changed configuration even when the conversation has already loaded the skill.
    (root/'runtime.conf').write_text('Runtime: Node.js\nArgv: [node, new-script.js]',encoding='utf-8')
    updated=tools.skills.refresh_context(current)
    assert json.loads(updated[-1]['content'])['configured_runtime']['Argv']==['node','new-script.js']


def test_removed_skill_does_not_keep_stale_success_in_context(harness):
    settings,store,tools,runtime,session=harness
    result=tools.skills.refresh_context(history())
    assert '当前项目中已不存在技能' in json.loads(result[-1]['content'])['error']


def test_refresh_preserves_other_tools_and_messages(harness):
    settings,store,tools,runtime,session=harness
    messages=[{'role':'user','content':'question'},
              {'role':'tool','tool_call_id':'read-1','content':'unchanged file result'},
              {'role':'assistant','content':'answer'}]
    assert tools.skills.refresh_context(messages)==messages


def test_runtime_uses_fresh_skill_context_on_followup(harness):
    settings,store,tools,runtime,session=harness
    root=add_skill(settings)
    for message in history():store.append(session,message)
    requests=[]
    class Capture:
        async def stream(self,messages,definitions):
            requests.extend(messages)
            yield {'type':'response','message':{'role':'assistant','content':'use current skill'}}
    runtime.provider=Capture()
    async def run():
        runtime.start(session,'重新使用技能')
        await runtime.active[session].task
    asyncio.run(run())
    current=next(message for message in requests if message.get('tool_call_id')=='load-1')
    assert json.loads(current['content'])['directory']==str(root)
    assert 'old instructions' in store.messages(session)[2]['content']
