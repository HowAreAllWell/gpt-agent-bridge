#!/usr/bin/env python3
"""Build a complete, allowlisted directory from the Git candidate, never private state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import zipfile

ROOTS = {'src', 'scripts', 'systemd', 'skills', 'templates', 'docs', 'tests', 'browser-extension', 'examples'}
FILES = {'LICENSE', 'README.md', 'README.zh-CN.md', 'AGENTS.md', 'pyproject.toml', 'requirements.txt', 'plugin.json', '.gitignore', 'prepare', 'Start-Bridge.ps1', '.app.example.json'}
PLACEHOLDER = b'{"apps": {"bridge": {"id": "asdk_app_REPLACE_WITH_OWN_APP_ID", "required": true}}}\n'
CONNECTION = b'export const connection = null;\n'
SKILL_FILES = tuple('skills/' + name + '/SKILL.md' for name in
                    ('project-onboarding', 'project-resume', 'handoff-preparation', 'team-deliberation')) + ('LICENSE',)
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, 'O_NONBLOCK', 0)


def source_identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def open_source_root(source):
    # Mirror prepare-bridge.py's release-input pinning without importing its
    # interactive installer: no source component may be a symlink.
    fd = os.open(os.sep, DIRECTORY_FLAGS)
    try:
        for name in Path(os.path.abspath(os.fspath(source))).parts[1:]:
            try: child = os.open(name, DIRECTORY_FLAGS, dir_fd=fd)
            except OSError as error: raise ValueError('SOURCE_NOT_REGULAR') from error
            try:
                is_directory = stat.S_ISDIR(os.fstat(child).st_mode)
            except BaseException:
                os.close(child); raise
            if not is_directory:
                os.close(child); raise ValueError('SOURCE_NOT_REGULAR')
            os.close(fd); fd = child
        return fd
    except BaseException:
        os.close(fd); raise


def open_source_directory(name, parent):
    try: fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
    except OSError as error: raise ValueError('SOURCE_NOT_REGULAR') from error
    try:
        is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
    except BaseException:
        os.close(fd); raise
    if not is_directory:
        os.close(fd); raise ValueError('SOURCE_NOT_REGULAR')
    return fd


def read_source_file(root, name):
    parts = name.split('/')
    if not name or name.startswith('/') or any(part in ('', '.', '..') for part in parts):
        raise ValueError('SOURCE_NOT_REGULAR')
    directory = os.dup(root)
    try:
        for part in parts[:-1]:
            child = open_source_directory(part, directory)
            os.close(directory); directory = child
        try: fd = os.open(parts[-1], FILE_FLAGS, dir_fd=directory)
        except OSError as error: raise ValueError('SOURCE_NOT_REGULAR') from error
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError('SOURCE_NOT_REGULAR')
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk: break
                chunks.append(chunk)
            after = os.fstat(fd)
            data = b''.join(chunks)
            if len(data) != before.st_size or source_identity(before) != source_identity(after):
                raise ValueError('SOURCE_CHANGED')
            try: reopened = os.open(parts[-1], FILE_FLAGS, dir_fd=directory)
            except OSError as error: raise ValueError('SOURCE_CHANGED') from error
            try: current = os.fstat(reopened)
            finally: os.close(reopened)
            if source_identity(current) != source_identity(after):
                raise ValueError('SOURCE_CHANGED')
            return data, 0o700 if before.st_mode & 0o111 else 0o600
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def build(source, destination):
    previous = os.umask(0o077)
    try:
        return build_private(source, destination)
    finally:
        os.umask(previous)


def build_private(source, destination):
    if destination.exists() or destination.is_symlink(): raise ValueError('OUTPUT_EXISTS')
    names = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z', '--', '.', ':(exclude).principal', ':(exclude).principal/**', ':(exclude).app.json']).decode().split('\0')
    chosen = sorted(n for n in names if n and (n in FILES or n.split('/')[0] in ROOTS))
    if len(chosen) != len(set(chosen)) or any(
            n.startswith('/') or any(part in ('', '.', '..') for part in n.split('/')) for n in chosen):
        raise ValueError('UNSAFE_CANDIDATE_PATH')
    if any('/node_modules/' in n or '/__pycache__/' in n or n.endswith('.pyc') or n.startswith('docs/evidence/') for n in chosen):
        raise ValueError('NON_PRODUCT_CANDIDATE')
    required = {'prepare', 'scripts/prepare-bridge.py', 'scripts/prepare-system.py', 'scripts/release-assets.json',
                'src/gpt_agent_bridge/browser_notifications.py', 'browser-extension/extension/manifest.json',
                'browser-extension/extension/projects.js', 'templates/WEB-PRINCIPAL-CORE.md'}
    required.update(SKILL_FILES)
    if not required <= set(chosen): raise ValueError('INCOMPLETE_CANDIDATE_STAGE_PRODUCT_FILES_FIRST')
    source_fd = open_source_root(source)
    try:
        destination.mkdir(mode=0o700)
        manifest = {}; executables=[]
        for name in chosen:
            if name == 'browser-extension/extension/connection.js':
                # Never inspect the source pairing file, even for type or mode.
                data = CONNECTION; mode = 0o600
            else:
                data, mode = read_source_file(source_fd, name)
            target = destination / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data); target.chmod(mode)
            if mode & 0o111:executables.append(name)
            manifest[name] = hashlib.sha256(data).hexdigest()
    finally:
        os.close(source_fd)
    (destination / '.app.json').write_bytes(PLACEHOLDER)
    manifest['.app.json'] = hashlib.sha256(PLACEHOLDER).hexdigest()
    # Use the frozen FULL payload, not a second read of possibly changing source.
    # Fixed names, timestamp, mode and uncompressed bytes make this deterministic.
    archive = destination / 'Bridge-Skills.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED) as package:
        for name in SKILL_FILES:
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            package.writestr(entry, (destination / name).read_bytes())
    archive.chmod(0o600)
    manifest['Bridge-Skills.zip'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / 'release-manifest.json').write_text(json.dumps({'version':1,'files':manifest,'executables':executables},sort_keys=True,indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path)
    a=p.parse_args();build(Path(__file__).resolve().parents[1],a.destination.absolute())
