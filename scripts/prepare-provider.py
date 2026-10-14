#!/usr/bin/env python3
"""Two official npm installation paths in an owner-private prefix; no account actions."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import tarfile
import urllib.request


def fetch(helper,url,path,algorithm,expected):
    if path.exists():data=helper.read(path)
    else:
        with urllib.request.urlopen(url,timeout=60) as response:
            helper.require(response.url.startswith('https://'),'INSECURE_PROVIDER_REDIRECT')
            data=response.read(helper.MAX_FILE+1)
        helper.require(len(data)<=helper.MAX_FILE,'PROVIDER_ASSET_TOO_LARGE')
    actual=hashlib.new(algorithm,data).digest()
    helper.require(actual==expected,'PROVIDER_ASSET_DIGEST_MISMATCH')
    helper.publish(path,data);return path


def install(helper,state,kind,ask=input):
    pins=json.loads(helper.read(helper.SOURCE/'scripts/provider-assets.json',False))
    helper.require(kind in ('codex','gemini'),'PROVIDER_AUTOINSTALL_UNSUPPORTED')
    spec=pins[kind];base=helper.directory(state/('provider-'+kind),True)
    print('Official npm package '+spec['package']+'@'+spec['version']+'; owner-private software only. Login/terms/fees stay in its interactive CLI.')
    helper.require(ask('Trust this selected provider package and install it locally? [yes/no] ').strip()=='yes','PROVIDER_INSTALL_NOT_AUTHORIZED')
    # npm supplies dependency integrity checks; pin and independently verify the
    # selected top-level archive. No arbitrary package string enters the command.
    archive=fetch(helper,spec['url'],base/'provider.tgz','sha512',base64.b64decode(spec['integrity'].removeprefix('sha512-')))
    node=shutil.which('node');npm=shutil.which('npm')
    if not node or not npm or int(helper.command([node,'--version']).lstrip('v').split('.')[0])<20:
        asset=pins.get(platform.machine());helper.require(asset,'PROVIDER_NODE_ARCH_UNSUPPORTED')
        packed=fetch(helper,asset['url'],base/'node.tar.xz','sha256',bytes.fromhex(asset['sha256']))
        destination=base/asset['directory']
        if not destination.exists():
            # Extract into a new disposable staging directory; interrupted
            # staging is retained and never mistaken for a complete Node tree.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='node-stage-',dir=base) as tmp:
                stage=Path(tmp)
                with tarfile.open(packed) as tar:
                    for item in tar.getmembers():
                        target=stage/item.name
                        helper.require(target.resolve().is_relative_to(stage) and not item.isdev(),'UNSAFE_NODE_ARCHIVE')
                        if item.issym() or item.islnk():
                            linked=(target.parent/item.linkname) if item.issym() else stage/item.linkname
                            helper.require(linked.resolve().is_relative_to(stage),'UNSAFE_NODE_LINK')
                    tar.extractall(stage)
                os.rename(stage/asset['directory'],destination)
        # A directory name alone is not a verified extraction receipt.
        with tarfile.open(packed) as tar:
            for item in tar.getmembers():
                target=base/item.name
                if item.isfile():helper.require(target.is_file() and not target.is_symlink() and target.read_bytes()==tar.extractfile(item).read(),'CHANGED_NODE_EXTRACTION')
                elif item.issym():helper.require(target.is_symlink() and os.readlink(target)==item.linkname,'CHANGED_NODE_EXTRACTION')
                elif item.isdir():helper.require(target.is_dir() and not target.is_symlink(),'CHANGED_NODE_EXTRACTION')
        node=str(destination/'bin/node');npm=str(destination/'bin/npm')
    env={**os.environ,'PATH':str(Path(node).parent)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin')}
    prefix=helper.directory(base/'npm',True);binary=prefix/'bin'/kind
    # An interrupted npm install is repairable in this explicitly owned prefix.
    installed=False
    if binary.exists():
        metadata=prefix/'lib/node_modules'/spec['package']/'package.json'
        installed=metadata.is_file() and json.loads(metadata.read_text()).get('version')==spec['version']
    if not installed:helper.command([npm,'install','--global','--prefix',prefix,'--registry=https://registry.npmjs.org',archive],interactive=True,env=env)
    helper.require(binary.is_file(),'PROVIDER_INSTALL_INCOMPLETE')
    helper.command([node,binary,'--version'],env=env)
    wrapper=base/'bin'/kind
    helper.publish(wrapper,('#!/bin/sh\nexec '+shlex.quote(node)+' '+shlex.quote(str(binary))+' "$@"\n').encode(),mode=0o700)
    return str(wrapper)
