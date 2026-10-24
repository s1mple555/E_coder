import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import uuid

import pytest

from ecoder.config import ROOT
from ecoder.skills import Skills
from test_harness import harness


def load_script(directory, filename, monkeypatch):
    monkeypatch.syspath_prepend(str(directory))
    monkeypatch.delitem(sys.modules, 'github_utils', raising=False)
    name = 'installer_test_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, directory / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def installer_project(tmp_path, monkeypatch):
    # Exercise direct invocation after a move, without runtime.conf or --dest.
    project = tmp_path / '移动后的 E_coder'
    skills = project / 'skills'
    installer = skills / 'skill-installer'
    shutil.copytree(ROOT / 'skills' / 'skill-installer', installer)
    (installer / 'runtime.conf').unlink(missing_ok=True)
    scripts = installer / 'scripts'
    install = load_script(scripts, 'install-skill-from-github.py', monkeypatch)
    listing = load_script(scripts, 'list-skills.py', monkeypatch)
    monkeypatch.delenv('ECODER_SKILLS_DIR', raising=False)
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'unrelated-codex'))
    unrelated = tmp_path / 'connected-user-project'
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    repo = tmp_path / 'downloaded-repo'
    skill = repo / 'skills' / 'sample'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('---\nname: sample\ndescription: sample skill\n---\nSample.', encoding='utf-8')
    monkeypatch.setattr(install, '_prepare_repo', lambda *args: str(repo))
    return install, listing, skills


def test_no_dest_installs_into_own_project_and_updates_listing(installer_project, monkeypatch, capsys):
    install, listing, skills = installer_project
    assert Path(install._default_dest()) == skills
    assert install.main(['--repo', 'example/repo', '--path', 'skills/sample']) == 0
    assert (skills / 'sample' / 'SKILL.md').is_file()
    assert 'sample' in listing._installed_skills()
    capsys.readouterr()
    monkeypatch.setattr(listing, '_list_skills', lambda *args: ['sample', 'not-installed'])
    assert listing.main(['--format', 'json']) == 0
    assert json.loads(capsys.readouterr().out) == [
        {'name': 'sample', 'installed': True}, {'name': 'not-installed', 'installed': False}]
    assert not (Path.cwd() / 'skills').exists()
    assert not (skills.parents[1] / 'unrelated-codex').exists()


def test_host_skills_directory_overrides_inherited_codex_home(installer_project, monkeypatch, tmp_path):
    install, listing, original = installer_project
    host = tmp_path / 'another-ecoder' / 'skills'
    monkeypatch.setenv('ECODER_SKILLS_DIR', str(host))
    assert install.main(['--repo', 'example/repo', '--path', 'skills/sample']) == 0
    assert (host / 'sample' / 'SKILL.md').exists()
    assert not (original / 'sample').exists()
    assert 'sample' in listing._installed_skills()


def test_explicit_destination_still_overrides_default(installer_project, tmp_path):
    install, _, default = installer_project
    selected = tmp_path / 'explicit destination'
    assert install.main(['--repo', 'example/repo', '--path', 'skills/sample', '--dest', str(selected)]) == 0
    assert (selected / 'sample' / 'SKILL.md').is_file()
    assert not (default / 'sample').exists()


def test_ecoder_command_injects_actual_registry_directory(harness, monkeypatch):
    settings, _, tools, _, _ = harness
    monkeypatch.setenv('ECODER_SKILLS_DIR', str(settings.root / 'wrong-directory'))
    monkeypatch.setenv('TEST_API_KEY', 'must-not-inherit')
    result = asyncio.run(tools.command({'execution_mode':'host','argv': [sys.executable, '-c',
        "import os,json;print(json.dumps([os.getenv('ECODER_SKILLS_DIR'),os.getenv('TEST_API_KEY')]))"], 'timeout': 5}))
    assert result['exit_code'] == 0
    assert json.loads(result['output']) == [str(tools.skills.root), None]


def test_skill_loading_regenerates_installer_paths_and_old_context(harness):
    settings, _, tools, runtime, session = harness
    registry = tools.skills.root
    directory = registry / 'skill-installer'
    # Even if an old config points at Codex, the runtime computes local paths.
    (directory / 'runtime.conf').write_text('Runtime: Python\nArgv: [old-python, old-installer, --dest, ~/.codex/skills]', encoding='utf-8')
    loaded = tools.skills.describe('skill-installer')
    assert loaded['install_directory'] == str(registry)
    assert loaded['configured_runtime']['Argv'] == [sys.executable, str(directory / 'scripts' / 'install-skill-from-github.py'), '--dest', str(registry)]
    history = [{'role': 'assistant', 'tool_calls': [{'id': 'load', 'function': {'name': 'load_skill', 'arguments': '{"name":"skill-installer"}'}}]},
               {'role': 'tool', 'tool_call_id': 'load', 'content': '{"instructions":"install into ~/.codex/skills"}'}]
    refreshed = json.loads(tools.skills.refresh_context(history)[-1]['content'])
    assert refreshed['install_directory'] == str(registry)
    assert refreshed['configured_runtime']['Argv'][-1] == str(registry)
    assert 'old-python' not in json.dumps(refreshed)
    assert str(registry) in runtime.system(session)['content']
    assert str(registry) in runtime.system(session, subagent=True)['content']


def test_existing_skill_is_not_overwritten(installer_project):
    install, _, skills = installer_project
    args = ['--repo', 'example/repo', '--path', 'skills/sample']
    assert install.main(args) == 0
    target = skills / 'sample' / 'SKILL.md'
    target.write_text('preserve local changes', encoding='utf-8')
    assert install.main(args) == 1
    assert target.read_text(encoding='utf-8') == 'preserve local changes'
