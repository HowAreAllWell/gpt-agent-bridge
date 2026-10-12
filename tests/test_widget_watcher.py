"""Batch render wire and one-shot JS protocol against a synthetic host."""
import json
import re
import shutil
import subprocess
import unittest
from unittest.mock import AsyncMock, patch
from mcp.types import CallToolResult
from tests import test_read_contract as fixtures
from tests.test_file_attachment import memory_client
from tests.test_run_retirement import TOOLS
from gpt_agent_bridge import server
from gpt_agent_bridge import widget_watcher as watcher

WORK = 'work-0123456789abcdef'
OTHER = 'work-fedcba9876543210'
WATCH = 'watch-0123456789abcdef'
RETIRED = ('watch_works', 'await', 'watch_work', 'claim_work_followup', 'begin_decision',
           'add_work_to_decision', 'watch_decision', 'await_decision', 'claim_decision_followup',
           'wait_project_notice', 'claim_project_notice')


class WidgetWireTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ReadContractTests.setUp

    async def test_catalog_audience_argument_guards_and_retired_names(self):
        listed = {tool.name: tool for tool in await server.mcp.list_tools()}
        self.assertEqual(set(listed), TOOLS)
        self.assertEqual(len(listed), 21)
        app = {name for name, tool in listed.items() if (tool.meta or {}).get('ui', {}).get('visibility') == ['app']}
        self.assertEqual(app, {'wait_work_watch', 'claim_work_watch', 'record_work_watch_send_outcome'})
        bound = {name for name, tool in listed.items() if (tool.meta or {}).get('ui', {}).get('resourceUri')}
        self.assertEqual(bound, {'delegate'})
        self.assertEqual(listed['delegate'].meta, watcher.DELEGATE_TOOL_META)
        self.assertEqual(set(listed['delegate'].input_schema['properties']), {'project_ref', 'assignments'})
        for name in app:
            self.assertEqual(listed[name].meta, {'ui': {'visibility': ['app']}})
            self.assertEqual(set(listed[name].input_schema['properties']), {'project_ref', 'watch_ref', 'attempt_token', 'outcome'} if name == 'record_work_watch_send_outcome' else {'project_ref', 'watch_ref'})
        for name in RETIRED:
            self.assertNotIn(name, listed)
            self.assertFalse(hasattr(server, name))
            with self.assertRaises(Exception): await server.mcp.call_tool(name, {})
        for name in ('delegate', 'wait_work_watch', 'claim_work_watch'):
            args = ({'project_ref': 'p', 'assignments': [{'agent_ref': 'a', 'task': 't'}]}
                    if name == 'delegate' else {'project_ref': 'p', 'watch_ref': WATCH})
            with self.assertRaises(Exception):
                await server.mcp.call_tool(name, {**args, 'extra': None})
        for key in ('question','decision_ref','request_report','capture_report'):
            with self.assertRaises(Exception): await server.mcp.call_tool('delegate', {'project_ref': 'p', key: None, 'assignments': [{'agent_ref': 'a', 'task': 't'}]})
        wait = server.mcp._tool_manager.get_tool('wait_work_watch')
        claim = server.mcp._tool_manager.get_tool('claim_work_watch')
        self.assertIsNot(wait.meta['ui'], claim.meta['ui'])
        self.assertIn('further delegation', ' '.join(listed['delegate'].description.split()))
        self.assertNotIn('watch_works', listed['delegate'].description)

    async def test_actual_arming_hidden_identity_ready_and_ui_free_context(self):
        async def dispatch(project, workspace, agent, task):
            work = server._reserve_work(project, workspace, agent, {'resource_key': agent})
            if task == 'ready':
                work.update(state='needs_attention', result_class='attention_required', report_status='unknown')
            return {'ok': True, 'work_ref': work['work_ref']}
        with patch.object(server, '_delegate_work', dispatch):
            result = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [{'agent_ref': 'a', 'task': 'armed'}]})
            continuation = result.structured_content['continuation']
            self.assertEqual(continuation['status'], 'armed')
            self.assertNotIn('watch_ref', continuation)
            self.assertIn('end this turn if none remains', result.content[0].text)
            self.assertEqual(result.meta[watcher.WORK_WATCH_META_KEY]['work_refs'], continuation['work_refs'])
            ready = await server.mcp.call_tool('delegate', {'project_ref': 'p', 'assignments': [{'agent_ref': 'b', 'task': 'ready'}]})
            self.assertEqual(ready.structured_content['continuation']['status'], 'ready')
            self.assertIn(ready.structured_content['continuation']['notice'], ready.content[0].text)
            self.assertIsNone(ready.meta)
        payload = {'ok': True, 'project_ref': 'p'}
        value = CallToolResult(content=[], structured_content=payload, meta={'unrelated': 'kept'})
        with patch.object(server.MCPServer, 'call_tool', AsyncMock(return_value=value)):
            actual = await server.mcp.call_tool('context', {'project_ref': 'p'})
        self.assertEqual(actual.meta, {'unrelated': 'kept'})
        self.assertEqual(actual.structured_content, payload)

    async def test_resource_and_delegate_over_memory_wire(self):
        async def dispatch(project, workspace, agent, task):
            work = server._reserve_work(project, workspace, agent, {'resource_key': agent})
            return {'ok': True, 'work_ref': work['work_ref']}
        async with memory_client([]) as client:
            listed = await client.list_resources()
            self.assertEqual([str(r.uri) for r in listed.resources], [watcher.WIDGET_RESOURCE_URI])
            read = await client.read_resource(watcher.WIDGET_RESOURCE_URI)
            self.assertEqual(read.contents[0].mime_type, 'text/html;profile=mcp-app')
            self.assertEqual(read.contents[0].text, watcher.widget_html())
            with patch.object(server, '_delegate_work', dispatch):
                armed = await client.call_tool('delegate', {'project_ref': 'p', 'assignments': [{'agent_ref': 'a', 'task': 'task'}]})
            self.assertEqual(armed.structured_content['continuation']['status'], 'armed')
            refs = [item['work_ref'] for item in armed.structured_content['items']]
            self.assertEqual(armed.meta[watcher.WORK_WATCH_META_KEY]['work_refs'], refs)


HARNESS = r'''
const vm = require('vm');
const fs = require('fs');
const arg = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [], sends = [], instances = [];
function make(metadata) {
  const listeners = {}, elements = {phase: {}, detail: {}};
  const host = {
    toolResponseMetadata: metadata,
    toolOutput: arg.mode === 'delegate_ready' ? {ok:true,items:[],continuation:{ok:true,status:'ready',notice:'Batch classified.'}} : undefined,
    callTool(name, args) {
      if (arg.mode === 'call_throw') throw Error('uncertain');
      if (arg.mode === 'call_nonpromise') return {};
      let resolve, reject;
      const promise = new Promise((a, b) => {resolve=a; reject=b;});
      calls.push({name, args, resolve, reject});
      if (name === 'record_work_watch_send_outcome') {
        if (arg.mode === 'feedback_throw') throw Error('lost telemetry');
        if (arg.mode === 'feedback_nonpromise') return {};
        if (arg.mode === 'feedback_reject') return Promise.reject(Error('lost telemetry'));
      }
      return promise;
    },
    sendFollowUpMessage(value) {
      sends.push(value.prompt);
      if (arg.mode === 'send_throw') throw Error('uncertain');
      if (arg.mode === 'send_nonpromise') return {};
      if (arg.mode === 'send_reject') return Promise.reject(Error('uncertain'));
      return Promise.resolve();
    }
  };
  if (arg.mode === 'send_missing') delete host.sendFollowUpMessage;
  const window = {openai: host, addEventListener: (name, fn) => {listeners[name] = fn;}};
  const document = {readyState: 'complete', getElementById: id => elements[id]};
  vm.runInNewContext(arg.script, {window, document});
  const env = {host, elements, update(metadata, eventOnly=false) {
    if (!eventOnly) host.toolResponseMetadata = metadata;
    listeners['openai:set_globals']({detail: {globals: {toolResponseMetadata: metadata}}});
  }};
  instances.push(env);
  return env;
}
const meta = value => ({'bridge/workWatch': value});
const envelope = value => ({structuredContent: value});
const tick = async () => {for (let i=0;i<16;i++) await Promise.resolve();};
(async () => {
 const metadata = arg.metadata === undefined ? meta(arg.hydration) : arg.metadata;
 const env = make(arg.mode === 'delayed' || arg.event_only ? {} : metadata);
 await tick();
 if (arg.mode === 'delayed' || arg.event_only) {env.update(metadata, arg.event_only); await tick();}
 if (arg.mode === 'freeze') {
   env.update(meta({project_ref: 'other', watch_ref:'watch-0123456789abcdef', work_refs:arg.hydration.work_refs})); env.update(meta(arg.hydration)); await tick();
 }
 if (arg.mode === 'duplicate') {make(meta(arg.hydration)); await tick();}
 if (arg.mode === 'neutral') {
   calls[0].resolve(envelope({ready: false})); await tick();
 } else if (arg.mode === 'wait_bad') {
   calls[0].resolve(arg.response); await tick();
 } else if (arg.mode === 'wait_reject') {
   calls[0].reject(Error('uncertain')); await tick();
 } else if (calls.length && arg.mode !== 'freeze') {
   const waits = calls.filter(c => c.name === 'wait_work_watch');
   waits.forEach(c => c.resolve(envelope({ready:true, project_ref:'p',watch_ref:'watch-0123456789abcdef',...arg.notice})));
   await tick();
   const claims = calls.filter(c => c.name === 'claim_work_watch');
   if (arg.mode === 'claim_reject') {claims[0].reject(Error('uncertain'));}
   else if (arg.mode === 'claim_bad') {claims[0].resolve(arg.response);}
   else if (arg.mode === 'claim_denied') {claims[0].resolve(envelope({ok:true,granted:false,project_ref:'p',watch_ref:'watch-0123456789abcdef',reason:'already_consumed'}));}
   else {
     claims.forEach((c,i) => c.resolve(envelope(i ? {ok:true,granted:false,project_ref:'p',watch_ref:'watch-0123456789abcdef',reason:'already_consumed'} :
       {ok:true,granted:true,project_ref:'p',watch_ref:'watch-0123456789abcdef',attempt_token:'attempt-0123456789abcdef0123456789abcdef',...arg.notice})));
   }
   await tick();

 }
 env.update(meta({project_ref:'other'})); await tick();
 process.stdout.write(JSON.stringify({calls:calls.map(c => ({name:c.name,args:c.args})), sends,
   states:instances.map(e => ({phase:e.elements.phase.textContent,detail:e.elements.detail.textContent}))}));
})().catch(e => {console.error(e);process.exit(1)});
'''


@unittest.skipUnless(shutil.which('node'), 'Node unavailable')
class WidgetExecutionTests(unittest.TestCase):
    def run_widget(self, mode='success', notice=None, **kwargs):
        notice = notice or {'result_ready':[WORK], 'attention_required':[]}
        attention = [{**item, 'report_status':item.get('report_status','unknown'), 'reason':item.get('reason','fixture')} for item in notice['attention_required']]
        refs = notice['result_ready'] + [item['work_ref'] for item in attention]
        notice = {**notice, 'attention_required':attention, 'work_refs':refs,
                  'proves':'final_classification_only',
                  'notice':watcher.format_classification_notice(notice['result_ready'], attention)}
        script = re.search(r'<script>(.*?)</script>', watcher.widget_html(), re.S).group(1)
        data = {'script':script, 'mode':mode, 'hydration':{'project_ref':'p','watch_ref':WATCH,'work_refs':refs},
                'notice':notice, **kwargs}
        result = subprocess.run(['node','-e',HARNESS], input=json.dumps(data),text=True,capture_output=True,timeout=10,check=True)
        return json.loads(result.stdout)

    def test_delegate_nested_ready_and_send_outcome_after_stop(self):
        ready = self.run_widget('delegate_ready')
        self.assertEqual(ready['calls'], [])
        self.assertEqual(ready['sends'], [])
        for mode, expected in (('normal', 'host_accepted'), ('send_missing', 'unavailable'),
                               ('send_throw', 'host_rejected_or_unknown'),
                               ('send_reject', 'host_rejected_or_unknown'),
                               ('send_nonpromise', 'host_rejected_or_unknown'),
                               ('feedback_throw', 'host_accepted'), ('feedback_reject', 'host_accepted'),
                               ('feedback_nonpromise', 'host_accepted')):
            with self.subTest(mode=mode):
                out = self.run_widget(mode)
                self.assertEqual(len(out['sends']), 0 if mode == 'send_missing' else 1)
                feedback = [c for c in out['calls'] if c['name'] == 'record_work_watch_send_outcome']
                self.assertEqual(len(feedback), 1)
                self.assertEqual(feedback[0]['args'], {'project_ref': 'p', 'watch_ref': WATCH,
                    'attempt_token': 'attempt-0123456789abcdef0123456789abcdef', 'outcome': expected})

    def test_metadata_bag_forms_hydrate_from_applied_and_event_globals(self):
        hydration = {'project_ref':'p', 'watch_ref':WATCH, 'work_refs':[WORK]}
        keyed = {watcher.WORK_WATCH_META_KEY:hydration}
        bags = [keyed, {'_meta':keyed}, {'meta':keyed}]
        for wrapper in ('mcp_tool_result', 'call_tool_result'):
            bags.extend([{wrapper:bag} for bag in (keyed, {'_meta':keyed}, {'meta':keyed})])
        for metadata in bags:
            for event_only in (False, True):
                with self.subTest(metadata=metadata, event_only=event_only):
                    out = self.run_widget(metadata=metadata, event_only=event_only)
                    self.assertEqual([call['name'] for call in out['calls']], ['wait_work_watch','claim_work_watch','record_work_watch_send_outcome'])
                    self.assertTrue(all(call['args'] == {'project_ref':'p','watch_ref':WATCH} for call in out['calls'][:2]))
                    self.assertEqual(len(out['sends']), 1)

    def test_tolerant_bag_discovery_preserves_fail_closed_batch_validation(self):
        valid = {'project_ref':'p', 'watch_ref':WATCH, 'work_refs':[WORK]}
        invalid = [None, {'project_ref':'p'}, {**valid,'project_ref':'p\n'},
                   {**valid,'watch_ref':'bad'}, {**valid,'work_refs':[]},
                   {**valid,'work_refs':[WORK,WORK]}, {**valid,'work_refs':[OTHER+'\n']}]
        for wrapper in ('mcp_tool_result', 'call_tool_result'):
            for nesting in (None, '_meta', 'meta'):
                for hydration in invalid:
                    keyed = {watcher.WORK_WATCH_META_KEY:hydration}
                    result = {nesting:keyed} if nesting else keyed
                    metadata = {wrapper:result}
                    for event_only in (False, True):
                        with self.subTest(metadata=metadata, event_only=event_only):
                            out = self.run_widget(metadata=metadata, event_only=event_only)
                            self.assertEqual(out['calls'], [])
                            self.assertEqual(out['sends'], [])
        # A malformed discovered identity must not fall through to a later valid
        # wrapper and send under a different interpretation of the same metadata.
        conflicting = {watcher.WORK_WATCH_META_KEY:{'project_ref':'p'},
                       'mcp_tool_result':{'_meta':{watcher.WORK_WATCH_META_KEY:valid}}}
        out = self.run_widget(metadata=conflicting)
        self.assertEqual(out['calls'], [])
        self.assertEqual(out['sends'], [])

    def test_delayed_hydration_freezes_batch_one_shot(self):
        out = self.run_widget('delayed')
        self.assertEqual([c['name'] for c in out['calls']], ['wait_work_watch','claim_work_watch','record_work_watch_send_outcome'])
        self.assertTrue(all(c['args'] == {'project_ref':'p','watch_ref':WATCH} for c in out['calls'][:2]))
        frozen = self.run_widget('freeze')
        self.assertEqual(len(frozen['calls']), 1)
        self.assertEqual(frozen['sends'], [])
        for hydration in ({'project_ref':'bad/','watch_ref':WATCH,'work_refs':[WORK]},
                          {'project_ref':'p','watch_ref':'bad','work_refs':[WORK]},
                          {'project_ref':'p','watch_ref':WATCH,'work_refs':[WORK,WORK]}):
            invalid = self.run_widget(hydration=hydration)
            self.assertEqual(invalid['calls'], [])
            self.assertEqual(invalid['sends'], [])

    def test_neutral_segment_reattaches_without_timer(self):
        out = self.run_widget('neutral')
        self.assertEqual([c['name'] for c in out['calls']], ['wait_work_watch']*2)
        self.assertEqual(out['sends'], [])
        self.assertNotIn('setTimeout', watcher.widget_html())
        self.assertNotIn('setInterval', watcher.widget_html())

    def test_normal_attention_mixed_use_server_formatter_and_stop(self):
        attention = [{'work_ref':OTHER,'agent_ref':'a','signal':'needs_attention','report_status':'unknown','reason':'blocked'}]
        for notice in ({'result_ready':[WORK],'attention_required':[]},
                       {'result_ready':[],'attention_required':attention},
                       {'result_ready':[WORK],'attention_required':attention}):
            out = self.run_widget(notice=notice)
            self.assertEqual(out['sends'], [watcher.format_classification_notice(notice['result_ready'], notice['attention_required'])])
            self.assertIn('Batch classified. Classification is not task success', out['sends'][0])
            self.assertIn('Reassess the pending judgment before continuing', out['sends'][0])
            self.assertIn('continue relevant authorized work in light of current user input', out['sends'][0])
            self.assertEqual(len(out['calls']), 3)
        self.assertNotIn('missing', out['sends'][0])

    def test_duplicate_instances_and_consumed_denial_stop(self):
        out = self.run_widget('duplicate')
        self.assertEqual(len(out['sends']), 1)
        self.assertEqual(len(out['calls']), 5)
        out = self.run_widget('claim_denied')
        self.assertEqual(out['sends'], [])
        self.assertEqual(len(out['calls']), 2)

    def test_ambiguous_send_never_resends_or_resumes(self):
        for mode in ('send_throw','send_nonpromise','send_reject','send_missing'):
            out = self.run_widget(mode)
            self.assertEqual(len(out['sends']), 0 if mode == 'send_missing' else 1)
            self.assertEqual([c['name'] for c in out['calls']], ['wait_work_watch','claim_work_watch','record_work_watch_send_outcome'])
            self.assertIn('consumed', out['states'][0]['detail'])

    def test_wait_errors_consumed_transport_and_incomplete_batch(self):
        for response in ({}, {'structuredContent':{}}, {'structuredContent':{'ready':False,'extra':True}},
                         {'isError':True,'structuredContent':{'ready':True}},
                         {'structuredContent':{'ok':False}},
                         {'structuredContent':{'ready':True,'project_ref':'p','watch_ref':WATCH,'work_refs':[WORK,OTHER],
                             'result_ready':[WORK], 'attention_required':[], 'proves':'final_classification_only','notice':'Incomplete'}}):
            out = self.run_widget('wait_bad',response=response)
            self.assertEqual(len(out['calls']), 1)
            self.assertEqual(out['sends'], [])
        consumed = self.run_widget('wait_bad',response={'structuredContent':{'ok':True,'status':'consumed','project_ref':'p','watch_ref':WATCH}})
        self.assertEqual(consumed['states'][0]['phase'], 'consumed')
        for mode in ('wait_reject','call_throw','call_nonpromise'):
            self.assertEqual(self.run_widget(mode)['sends'], [])

    def test_claim_malformed_identity_coverage_and_contradiction_stop(self):
        good = {'ok':True,'granted':True,'project_ref':'p','watch_ref':WATCH,'work_refs':[WORK],
                'attempt_token':'attempt-0123456789abcdef0123456789abcdef',
                'result_ready':[WORK],'attention_required':[],'proves':'final_classification_only','notice':'Classified'}
        bad = [{}, {'ok':False}, {**good,'granted':'true'}, {**good,'watch_ref':'watch-ffffffffffffffff'},
               {**good,'attempt_token':None}, {**good,'attempt_token':'bad'},
               {**good,'result_ready':[]}, {**good,'result_ready':[WORK,WORK]}, {**good,'work_refs':[OTHER]},
               {**good,'notice':None}, {**good,'result_ready':[], 'attention_required':[{'work_ref':WORK,
                   'agent_ref':'a','signal':'agent_turn_settled','report_status':'readable','reason':'contradictory'}]}]
        for value in bad:
            out = self.run_widget('claim_bad',response={'structuredContent':value})
            self.assertEqual(out['sends'], [])
            self.assertEqual(len(out['calls']), 2)
        self.assertEqual(self.run_widget('claim_reject')['sends'], [])

    def test_malformed_consumed_grant_without_token_fails_closed(self):
        malformed = {'ok':True, 'granted':True, 'project_ref':'p', 'watch_ref':WATCH,
                  'work_refs':[WORK], 'result_ready':[WORK], 'attention_required':[],
                  'proves':'final_classification_only', 'notice':'classified notice'}
        out = self.run_widget('claim_bad', response={'structuredContent':malformed})
        self.assertEqual([c['name'] for c in out['calls']], ['wait_work_watch', 'claim_work_watch'])
        self.assertEqual(out['sends'], [])
        self.assertEqual(out['states'][0]['phase'], 'error-claim')
