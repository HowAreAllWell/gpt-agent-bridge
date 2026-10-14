#!/usr/bin/env python3
"""First-project Agent preparation using Herdr's existing workspace/start commands.

No prompts or tasks are sent. Unknown creation/start is journaled and observed,
never automatically repeated. Provider selection/login remain human decisions.
"""
import json
from pathlib import Path
import os
import shutil
import subprocess

# Herdr's canonical executable names, not a replacement provider abstraction.
KINDS = ('pi','claude','codex','gemini','cursor','devin','agy','cline','omp','mastracode',
         'opencode','copilot','kimi','kiro','droid','amp','grok','hermes','kilo','qodercli','qwen','maki','muse')


def prepare(helper, state, root, ref, herdr, call, ask=input):
    observation=call('context',{'project_ref':ref,'include_continuity':False})
    helper.require(observation.get('ok'), 'PROJECT_CONTEXT_UNAVAILABLE')
    agents=observation.get('agents',[])
    if agents:
        print('Existing project Agents discovered. Reuse the fresh handles in Web context; no launch was attempted.')
        return 'existing_agents_observed'
    choices=[kind for kind in KINDS if shutil.which(kind)]
    if not choices:
        print('No supported Agent executable is on this login PATH. Bridge is installed independently. Choose your provider and complete its official installation/login locally; see docs/GETTING-STARTED.md. Re-enter prepare project afterward; no credentials or provider choice are guessed.')
        return 'provider_install_login_required'
    print('Available local Agent executables: '+', '.join(choices))
    chosen=ask('Choose the provider/Agent to start (cost and login are yours; empty defers): ').strip()
    if not chosen:return 'agent_start_deferred'
    helper.require(chosen in choices,'SELECT_DETECTED_AGENT')
    journal=state/('agent-'+ref+'.json')
    if journal.exists():
        print('An earlier Agent preparation was attempted. Its outcome is not replaced or retried. Inspect its Herdr pane and Web context; finish login there if needed.')
        return 'previous_attempt_observation_required'
    # Verify a session responds before creating layout. Never replace a session.
    try:json.loads(helper.command([herdr,'api','snapshot']))
    except Exception:
        if helper.launch_herdr(herdr,ask):return prepare(helper,state,root,ref,herdr,call,ask)
        print('Herdr session unavailable. Start the prepared Herdr executable in a separate interactive terminal and keep it open, then re-enter. The entry cannot manufacture an interactive desktop/terminal session on a headless host.')
        return 'interactive_herdr_session_required'
    helper.require(ask('Create one workspace pane at this project and start this Agent without a task? [yes/no] ').strip()=='yes','AGENT_START_AUTHORIZATION_REQUIRED')
    record={'project_ref':ref,'root':str(root),'kind':chosen,'stage':'workspace_creation_attempted'}
    helper.publish(journal,helper.json_bytes(record))
    created=json.loads(helper.command([herdr,'workspace','create','--cwd',root,'--label','bridge-'+ref,'--no-focus']))
    pane=created.get('result',{}).get('root_pane',{}).get('pane_id')
    helper.require(isinstance(pane,str) and pane and len(pane)<256,'WORKSPACE_RESULT_UNKNOWN_NO_RETRY')
    before=helper.read(journal);record.update(pane=pane,stage='agent_start_attempted');helper.publish(journal,helper.json_bytes(record),previous=before)
    # Herdr itself enforces available idle shell and refuses running foreground work.
    result=json.loads(helper.command([herdr,'agent','start','bridge-'+ref,'--kind',chosen,'--pane',pane]))
    helper.require(isinstance(result.get('result',{}).get('agent'),dict),'AGENT_RESULT_UNKNOWN_NO_RETRY')
    after=call('context',{'project_ref':ref,'include_continuity':False})
    helper.require(after.get('ok') and after.get('agents'),'AGENT_NOT_YET_DISCOVERABLE_INSPECT_LOGIN')
    before=helper.read(journal);record['stage']='agent_observed';helper.publish(journal,helper.json_bytes(record),previous=before)
    return 'agent_observed_no_task_sent'
