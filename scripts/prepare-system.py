#!/usr/bin/env python3
"""Small privileged adapter for the existing strict installers; no replacement policy.

Invoked by prepare-bridge.py after the operator approves sudo. Values are public
paths/digests, never keys. Each action re-observes owned records before continuing.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile


def module(path):
    spec = importlib.util.spec_from_file_location('installer_' + path.stem.replace('-', '_'), path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def reconcile(observe, install, enable, start):
    """Observation, not a remembered successful subprocess, authorizes each step."""
    state = observe()
    if state is None:
        install()
        state = observe()
    if not state or state['active'] not in ('active', 'inactive') or state['enabled'] not in ('enabled', 'disabled'):
        raise ValueError('SERVICE_STATE_UNKNOWN_INSPECT')
    if state['enabled'] == 'disabled':
        enable()
        state = observe()
    if not state or state['enabled'] != 'enabled':
        raise ValueError('ENABLE_OUTCOME_UNKNOWN_INSPECT')
    if state['active'] == 'inactive':
        start()
        state = observe()
    if not state or state['active'] != 'active':
        raise ValueError('START_OUTCOME_UNKNOWN_INSPECT')
    return state


def snapshot(source, target, mode):
    target.write_bytes(source.read_bytes())
    target.chmod(mode)


def bridge(source, scratch, args):
    script = scratch / 'install-bridge-autostart.py'
    snapshot(source / 'scripts' / script.name, script, 0o700)
    m = module(script)
    plan = m.make_plan(argparse.Namespace(user=args.user, repo=str(source), workspace=str(source),
                                         herdr_bin=args.herdr, port=8765))
    def observe():
        if not m.MANIFEST.exists():
            # install itself proves ALL protected objects absent, never overwrites a partial installation.
            return None
        if m.owned_installation() != plan:
            raise ValueError('DIFFERENT_BRIDGE_INSTALLATION_NO_ADOPTION')
        return {'active': m.command([m.SYSTEMCTL, 'show', m.UNIT_NAME, '-p', 'ActiveState', '--value']),
                'enabled': m.command([m.SYSTEMCTL, 'is-enabled', m.UNIT_NAME], allowed=(0, 1, 3, 4))}
    return reconcile(observe, lambda: m.install(plan), lambda: m.control('enable'), lambda: m.control('start'))


def tunnel(source, scratch, args):
    # The installer requires a root-owned pinned executable. Publish the small
    # verified upstream bundle, including its license, outside the service tree.
    pins = json.loads((source / 'scripts' / 'release-assets.json').read_text())
    asset = pins[args.arch]['tunnel']
    raw = Path(args.bundle).read_bytes()
    if hashlib.sha256(raw).hexdigest() != asset['sha256']:
        raise ValueError('TUNNEL_DOWNLOAD_DIGEST_MISMATCH')
    destination = Path('/usr/local/lib/gpt-agent-bridge-tunnel-client-v0.0.16')
    if destination.is_symlink():
        raise ValueError('UNSAFE_CLIENT_DESTINATION')
    if not destination.exists():
        destination.mkdir(mode=0o755)
    st = destination.lstat()
    if st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o755:
        raise ValueError('UNSAFE_CLIENT_DESTINATION')
    with zipfile.ZipFile(args.bundle) as archive:
        names = set()
        for item in archive.infolist():
            if '/' in item.filename or item.filename in ('.', '..') or item.file_size > 80_000_000:
                raise ValueError('UNEXPECTED_BUNDLE_LAYOUT')
            names.add(item.filename)
            path = destination / item.filename
            data = archive.read(item)
            mode = 0o755 if item.filename == 'tunnel-client-runtime' else 0o644
            if path.exists() or path.is_symlink():
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != mode or path.read_bytes() != data:
                    raise ValueError('CHANGED_CLIENT_NO_OVERWRITE')
            else:
                with path.open('xb') as f:
                    os.fchmod(f.fileno(), mode); f.write(data); f.flush(); os.fsync(f.fileno())
        if set(x.name for x in destination.iterdir()) != names:
            raise ValueError('UNKNOWN_CLIENT_FILES')
    script = scratch / 'install-bridge-tunnel-autostart.py'
    snapshot(source / 'scripts' / script.name, script, 0o600)
    snapshot(source / 'systemd/gpt-agent-bridge-tunnel.service.template', scratch / 'service.template', 0o600)
    m = module(script)
    client = destination / 'tunnel-client-runtime'
    plan = m.make_plan(argparse.Namespace(user=args.user, client=str(client),
        client_sha256=hashlib.sha256(client.read_bytes()).hexdigest(), health_socket='health.sock', ttl='10m', bridge_wait_seconds=60))
    def observe():
        if not m.MANIFEST.exists(): return None
        if m.record()['plan'] != plan: raise ValueError('DIFFERENT_TUNNEL_INSTALLATION_NO_ADOPTION')
        p = m.managed_properties()
        return {'active': p.get('ActiveState'), 'enabled': p.get('UnitFileState')}
    # First create the protected installation. Credentials are configured later
    # as its owner through the original hidden-input path, never under sudo.
    if args.action == 'tunnel-install':
        if observe() is None: m.install(plan)
        return observe()
    return reconcile(observe, lambda: m.install(plan), lambda: m.lifecycle('enable'), lambda: m.lifecycle('start'))


def activate_credentials(source,scratch):
    script=scratch/'install-bridge-tunnel-autostart.py'
    snapshot(source/'scripts'/script.name,script,0o600)
    snapshot(source/'systemd/gpt-agent-bridge-tunnel.service.template',scratch/'service.template',0o600)
    m=module(script)
    m.record() # existing owned installation; this path never installs
    active=m.managed_properties().get('ActiveState')
    if active not in ('active','inactive','failed'):raise ValueError('TUNNEL_STATE_UNKNOWN_NO_RESTART')
    if active in ('active','failed'):
        m.lifecycle('stop')
        if m.managed_properties().get('ActiveState')!='inactive':raise ValueError('TUNNEL_STOP_UNKNOWN_NO_START')
    m.lifecycle('start')
    return {'active':m.managed_properties().get('ActiveState'),'remote_access':'not_inferred'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['bridge', 'tunnel-install', 'tunnel-start', 'credentials-activate'])
    p.add_argument('--source', required=True); p.add_argument('--user', required=True)
    p.add_argument('--herdr'); p.add_argument('--bundle'); p.add_argument('--arch')
    a = p.parse_args()
    if os.geteuid() != 0: raise ValueError('SUDO_REQUIRED')
    source = Path(a.source)
    with tempfile.TemporaryDirectory(prefix='bridge-reviewed-', dir='/root') as tmp:
        result = (activate_credentials(source,Path(tmp)) if a.action=='credentials-activate' else
                  bridge(source, Path(tmp), a) if a.action == 'bridge' else tunnel(source, Path(tmp), a))
    print(json.dumps(result))


if __name__ == '__main__':
    try: main()
    except Exception:
        print('Protected setup refused or outcome uncertain; inspect owned installer status. No automatic retry.')
        raise SystemExit(1)
