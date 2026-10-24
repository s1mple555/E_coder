---
name: skill-installer
description: Install skills into the current E_coder project's skills directory from a curated list or a GitHub repo path. Use when a user asks to list available skills or download and install a skill.
metadata:
  short-description: Install curated skills from openai/skills or other repos
---

# Skill Installer

Helps install skills. By default these are from https://github.com/openai/skills/tree/main/skills/.curated, but users can also provide other locations.

This is the OpenAI installer adapted for E_coder. The destination is the
`install_directory` returned by `load_skill`, not the connected user workspace.
Prefer `configured_runtime.Argv` and append the repo/URL arguments; it already
includes `--dest` for the current E_coder instance. Direct script calls without
`--dest` use `ECODER_SKILLS_DIR`, or the `skills/` directory containing this skill.
An explicit user-specified `--dest` overrides this default. `CODEX_HOME` is not used.

Use the helper scripts based on the task:
- List skills when the user asks what is available, or if the user uses this skill without specifying what to do. Default listing is `.curated`, but you can pass `--path skills/.experimental` when they ask about experimental skills.
- Install from the curated list when the user provides a skill name.
- Install from another repo when the user provides a GitHub repo/path (including private repos).

Install skills with the helper scripts.

## Communication

When listing skills, output approximately as follows, depending on the context of the user's request. If they ask about experimental skills, list from `.experimental` instead of `.curated` and label the source accordingly:
"""
Skills from {repo}:
1. skill-1
2. skill-2 (already installed)
3. ...
Which ones would you like installed?
"""

After installing a skill, report its actual destination. E_coder discovers it on
the next model request; use “刷新技能” in the Skills page to refresh the displayed list.

## Scripts

Run these scripts by absolute path through E_coder's `run_command`; execution
uses the existing approval flow. Use the Python runtime returned by `load_skill`.

- `scripts/list-skills.py` (prints skills list with installed annotations)
- `scripts/list-skills.py --format json`
- Example (experimental list): `scripts/list-skills.py --path skills/.experimental`
- `scripts/install-skill-from-github.py --repo <owner>/<repo> --path <path/to/skill> [<path/to/skill> ...]`
- `scripts/install-skill-from-github.py --url https://github.com/<owner>/<repo>/tree/<ref>/<path>`
- Example (experimental skill): `scripts/install-skill-from-github.py --repo openai/skills --path skills/.experimental/<skill-name>`

## Behavior and Options

- Defaults to direct download for public GitHub repos.
- If download fails with auth/permission errors, falls back to git sparse checkout.
- Aborts if the destination skill directory already exists.
- Installs into the current E_coder project's `skills/<skill-name>` by default.
- Multiple `--path` values install multiple skills in one run, each named from the path basename unless `--name` is supplied.
- Options: `--ref <ref>` (default `main`), `--dest <path>`, `--method auto|download|git`.

## Notes

- Curated listing is fetched from `https://github.com/openai/skills/tree/main/skills/.curated` via the GitHub API. If it is unavailable, explain the error and exit.
- Private GitHub repos can be accessed via existing git credentials or optional `GITHUB_TOKEN`/`GH_TOKEN` for download.
- Git fallback tries HTTPS first, then SSH.
- Installed annotations come from the same E_coder skills directory used by the installer. Skills installed in another application are not automatically available in E_coder.
