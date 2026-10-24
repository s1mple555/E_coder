from pathlib import Path
import os
import platform
import shutil
import sys
import copy
import json

import yaml


class Skills:
    """Discover metadata on each request, inject the body only after load_skill."""
    def __init__(self, root: Path):
        self.root = root.resolve()

    def catalog(self):
        result = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            if not path.resolve().is_relative_to(self.root):
                continue
            try:
                text = path.read_text(encoding="utf-8")
                parts = text.split("---", 2)
                meta = yaml.safe_load(parts[1]) if text.startswith("---") and len(parts) == 3 else {}
                meta = meta if isinstance(meta, dict) else {}
                result.append({"name": path.parent.name, "description": str(meta.get("description", "")), "content": parts[2].strip() if len(parts) == 3 else text})
            except (OSError, ValueError, yaml.YAMLError):
                continue
        return result

    def load(self, name):
        for skill in self.catalog():
            if skill["name"] == name:
                return skill["content"]
        raise ValueError(f"Skill 不存在: {name}")

    def readable(self, value):
        path = Path(value).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            return False
        parts = path.relative_to(self.root).parts
        if len(parts)<2 or not (self.root/parts[0]/"SKILL.md").is_file():
            return False
        if any(part.startswith('.') or part.casefold() in {'node_modules','__pycache__'} for part in parts):
            return False
        if any(word in path.name.casefold() for word in ('secret','password','credential')):
            return False
        return path.suffix.casefold() in {'.md','.py','.js','.ps1','.sh','.json','.yaml','.yml','.txt','.toml','.conf'}

    def describe(self, name):
        instructions = self.load(name)
        directory = (self.root/name).resolve()
        resources = []
        for parent,dirs,files in os.walk(directory,followlinks=False):
            dirs[:]=[part for part in dirs if not part.startswith('.') and part not in {'node_modules','__pycache__'}
                     and not (Path(parent)/part).is_symlink() and not (Path(parent)/part).is_junction()]
            for filename in sorted(files):
                path=Path(parent)/filename
                if self.readable(path):
                    resources.append(path.relative_to(directory).as_posix())
                if len(resources)>=100:
                    break
            if len(resources)>=100:
                break
        configuration = self.configuration(directory)
        return {'skill':name,'instructions':instructions,'directory':str(directory),'resources':resources,
                'install_directory':str(self.root),
                'runtimes':{'platform':platform.system(),'python':sys.executable,'node':shutil.which('node')},
                'configured_runtime':configuration,
                'execution_mode':'host' if name == 'skill-installer' else 'sandbox',
                'execution_note':'run_command 的当前目录是用户工作区。脚本必须使用技能目录中的绝对路径，不能把 scripts/ 当作当前工作区路径。可用 read_file 只读查看列出的技能资源；默认沙箱内执行脚本，禁止联网；联网下载或安装到技能目录必须显式指定 execution_mode=host 并经用户批准。'}

    def configuration(self, directory):
        # Resolve the bundled installer at request time: neither a moved project
        # nor a stale runtime.conf should redirect installation to another app.
        installer = directory/'scripts'/'install-skill-from-github.py'
        if directory.name == 'skill-installer' and self.readable(installer):
            return {'Runtime':'Python', 'Argv':[sys.executable,str(installer),'--dest',str(self.root)]}
        configuration = None
        config=directory/'runtime.conf'
        if self.readable(config) and config.stat().st_size<=20000:
            try:
                value=yaml.safe_load(config.read_text(encoding='utf-8-sig'))
                if isinstance(value,dict):
                    configuration={key:value[key] for key in ('Runtime','Command','Argv') if key in value}
            except (OSError,ValueError,yaml.YAMLError):
                pass
        return configuration

    def refresh_context(self, messages):
        """Refresh old load_skill results for this request; preserve the stored audit trail."""
        messages=copy.deepcopy(messages)
        loads={}
        refreshed={}
        for message in messages:
            if message.get('role')=='assistant':
                for call in message.get('tool_calls',[]):
                    function=call.get('function',{})
                    if function.get('name')=='load_skill':
                        try:
                            name=json.loads(function['arguments'])['name']
                            if isinstance(name,str):loads[call['id']]=name
                        except (ValueError,KeyError,TypeError):
                            continue
            elif message.get('role')=='tool' and message.get('tool_call_id') in loads:
                name=loads[message['tool_call_id']]
                if name not in refreshed:
                    try:refreshed[name]=self.describe(name)
                    except ValueError:refreshed[name]={'error':f'当前项目中已不存在技能 {name}，不能继续使用历史加载结果'}
                message['content']=json.dumps(refreshed[name],ensure_ascii=False)
        return messages

    def summary(self):
        result=[]
        for skill in self.catalog():
            directory=(self.root/skill['name']).resolve()
            item={k:v for k,v in skill.items() if k!='content'}
            item['directory']=str(directory)
            configuration=self.configuration(directory)
            if configuration:item['configured_runtime']=configuration
            result.append(item)
        return result
