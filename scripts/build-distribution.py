#!/usr/bin/env python3
"""Build a complete, allowlisted directory from the Git candidate, never private state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOTS = {'src', 'scripts', 'systemd', 'skills', 'templates', 'docs', 'tests', 'browser-extension', 'examples'}
FILES = {'LICENSE', 'README.md', 'README.zh-CN.md', 'AGENTS.md', 'pyproject.toml', 'requirements.txt', 'plugin.json', '.gitignore', 'prepare', 'Start-Bridge.ps1', '.app.example.json'}
PLACEHOLDER = b'{"apps": {"bridge": {"id": "asdk_app_REPLACE_WITH_OWN_APP_ID", "required": true}}}\n'


def build(source, destination):
    if destination.exists() or destination.is_symlink(): raise ValueError('OUTPUT_EXISTS')
    names = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z', '--', '.', ':(exclude).principal', ':(exclude).principal/**', ':(exclude).app.json']).decode().split('\0')
    chosen = sorted(n for n in names if n and (n in FILES or n.split('/')[0] in ROOTS))
    if any('/node_modules/' in n or '/__pycache__/' in n or n.endswith('.pyc') or n.startswith('docs/evidence/') for n in chosen):
        raise ValueError('NON_PRODUCT_CANDIDATE')
    required = {'prepare', 'scripts/prepare-bridge.py', 'scripts/prepare-system.py', 'scripts/release-assets.json',
                'src/gpt_agent_bridge/browser_notifications.py', 'browser-extension/extension/manifest.json',
                'browser-extension/extension/projects.js', 'templates/WEB-PRINCIPAL-CORE.md'}
    required.update('skills/'+s+'/SKILL.md' for s in ['project-resume','project-onboarding','handoff-preparation','team-deliberation'])
    if not required <= set(chosen): raise ValueError('INCOMPLETE_CANDIDATE_STAGE_PRODUCT_FILES_FIRST')
    destination.mkdir(mode=0o700)
    manifest = {}; executables=[]
    for name in chosen:
        p = source / name
        if p.is_symlink() or not p.is_file(): raise ValueError('SOURCE_NOT_REGULAR')
        data = p.read_bytes()
        if name == 'browser-extension/extension/connection.js':
            content='\n'.join(line for line in data.decode().splitlines() if not line.strip().startswith('//')).strip()
            if content not in ('export const connection=null;', 'export const connection = null;'):
                raise ValueError('SECRET_CONNECTION_REFUSED')
        target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data); target.chmod(0o700 if p.stat().st_mode & 0o111 else 0o600)
        if p.stat().st_mode & 0o111:executables.append(name)
        manifest[name] = hashlib.sha256(data).hexdigest()
    (destination / '.app.json').write_bytes(PLACEHOLDER)
    manifest['.app.json'] = hashlib.sha256(PLACEHOLDER).hexdigest()
    (destination / 'release-manifest.json').write_text(json.dumps({'version':1,'files':manifest,'executables':executables},sort_keys=True,indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path)
    a=p.parse_args();build(Path(__file__).resolve().parents[1],a.destination.absolute())
