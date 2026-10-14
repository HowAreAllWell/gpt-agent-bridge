#!/usr/bin/env python3
"""Prepare an explicitly chosen Agent, without sending a task.

Complete discovery, canonical registered identity and a compatible live Herdr
snapshot are required. Unknown creation/start intents are never replayed.
"""
import json
from pathlib import Path
import os
import shutil

KINDS = ('pi','claude','codex','gemini','cursor','devin','agy','cline','omp','mastracode',
         'opencode','copilot','kimi','kiro','droid','amp','grok','hermes','kilo','qodercli','qwen','maki','muse')


def session(helper,herdr):
    reply=json.loads(helper.command([herdr,'api','snapshot']))
    snapshot=reply.get('result',{}).get('snapshot')
    helper.require(isinstance(snapshot,dict) and snapshot.get('version')=='0.9.0' and
                   isinstance(snapshot.get('agents'),list) and isinstance(snapshot.get('panes'),list),
                   'HERDR_SESSION_INCOMPATIBLE_OR_UNKNOWN')
    return snapshot


def prepare(helper,state,root,ref,herdr,call,ask=input):
    observation=helper.verify_project(root,ref,call)
    helper.require(observation.get('agents_complete') is True and not observation.get('agents_error') and
                   isinstance(observation.get('agents'),list),'AGENT_DISCOVERY_INCOMPLETE_NO_LAUNCH')
    snapshot=session(helper,herdr) # running session, not only CLI version
    journal=state/('agent-'+ref+'.json')
    previous=helper.read(journal) if journal.exists() else None
    record=json.loads(previous) if previous else None
    if observation['agents']:
        print('Existing project Agents discovered. Use fresh Web context handles; no launch.')
        return 'existing_agents_observed'
    if record:
        helper.require(record.get('root')==str(root) and record.get('project_ref')==ref,'AGENT_JOURNAL_IDENTITY_CHANGED')
        if record.get('stage')!='agent_observed':
            print('Earlier create/start outcome remains unknown. Inspect its existing Herdr pane and context; no repeat.')
            return 'previous_attempt_observation_required'
        # Complete current snapshots must confirm the saved locus has gone. A
        # surviving shell/pane is not permission to create a duplicate environment.
        if any(p.get('pane_id')==record.get('pane') for p in snapshot['panes']):
            return 'previous_pane_still_present_inspect'
    choices=[kind for kind in KINDS if shutil.which(kind)]
    supported=('codex','gemini')
    print('Detected Agents: '+(', '.join(choices) or 'none')+'. Automatic local installation: codex, gemini.')
    chosen=ask('Choose provider/Agent (login and fees are yours; empty defers): ').strip()
    if not chosen:return 'agent_start_deferred'
    helper.require(chosen in set(choices)|set(supported),'SELECT_SUPPORTED_OR_DETECTED_AGENT')
    executable=shutil.which(chosen)
    if not executable:
        executable=helper.load_script('prepare-provider.py').install(helper,state,chosen,ask)
    helper.require(ask('Create one workspace pane at this project and start this Agent without a task? [yes/no] ').strip()=='yes','AGENT_START_AUTHORIZATION_REQUIRED')
    fresh=helper.verify_project(root,ref,call)
    helper.require(fresh.get('agents_complete') is True and not fresh.get('agents_error') and fresh.get('agents')==[], 'AGENT_DISCOVERY_CHANGED_NO_LAUNCH')
    session(helper,herdr)
    # Keep successful historical observations, including the old pane, in the
    # next intent. A lost acknowledgement still leaves an unknown stage intact.
    record={'project_ref':ref,'root':str(root),'kind':chosen,'stage':'workspace_creation_attempted',
            'previous_success':record}
    helper.publish(journal,helper.json_bytes(record),previous=previous)
    path=str(Path(executable).parent)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin')
    created=json.loads(helper.command([herdr,'workspace','create','--cwd',root,'--label','bridge-'+ref,'--no-focus','--env','PATH='+path]))
    pane=created.get('result',{}).get('root_pane',{}).get('pane_id')
    helper.require(isinstance(pane,str) and pane and len(pane)<256,'WORKSPACE_RESULT_UNKNOWN_NO_RETRY')
    # Verify registered root again after the workspace mutation and before start.
    helper.verify_project(root,ref,call)
    before=helper.read(journal);record.update(pane=pane,stage='agent_start_attempted');helper.publish(journal,helper.json_bytes(record),previous=before)
    result=json.loads(helper.command([herdr,'agent','start','bridge-'+ref,'--kind',chosen,'--pane',pane]))
    helper.require(isinstance(result.get('result',{}).get('agent'),dict),'AGENT_RESULT_UNKNOWN_NO_RETRY')
    after=helper.verify_project(root,ref,call)
    helper.require(after.get('agents_complete') is True and not after.get('agents_error') and after.get('agents'),'AGENT_NOT_YET_DISCOVERABLE_INSPECT_LOGIN')
    before=helper.read(journal);record['stage']='agent_observed';helper.publish(journal,helper.json_bytes(record),previous=before)
    return 'agent_observed_no_task_sent'
