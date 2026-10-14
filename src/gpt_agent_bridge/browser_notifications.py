"""Opt-in loopback completion feed. No report retention, dispatch or send authority."""
from pathlib import Path
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import time
from starlette.responses import JSONResponse
from starlette.routing import Route

CONFIG = Path.home() / '.config/gpt-agent-bridge/browser-notifications.json'
WORK = re.compile(r'work-[0-9a-f]{16}\Z')
BATCH = re.compile(r'batch-[0-9a-f]{16}\Z')


class BrowserNotifications:
    def __init__(self, config=None, registered_projects=None):
        self.config = config
        self.registered_projects = registered_projects
        self.epoch = secrets.token_hex(16)
        self.sequence = 0
        self.status = None
        self.statuses = {}

    @staticmethod
    def validate_config(value):
        if not isinstance(value, dict):
            raise ValueError('Invalid browser notification configuration')
        legacy = 'project_ref' in value
        registry = value.get('version') == 3
        expected = {'version', 'discovery', 'extension_id', 'token', 'port'} if registry else {'project_ref', 'root', 'extension_id', 'token', 'port'} if legacy else {'version', 'projects', 'extension_id', 'token', 'port'}
        if (set(value) != expected or (not legacy and not registry and value['version'] != 2)
                or (registry and value.get('discovery') != 'registered')
                or not isinstance(value['extension_id'], str) or not re.fullmatch(r'[a-p]{32}', value['extension_id'])
                or not isinstance(value['token'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{43,128}', value['token'])
                or type(value['port']) is not int or not 1024 <= value['port'] <= 65535):
            raise ValueError('Invalid browser notification configuration')
        projects = [dict(project_ref=value['project_ref'], root=value['root'])] if legacy else [] if registry else value['projects']
        if not isinstance(projects, list) or len(projects) > 32:
            raise ValueError('Invalid notification projects')
        refs = set()
        for project in projects:
            if (not isinstance(project, dict) or set(project) != {'project_ref', 'root'}
                    or not isinstance(project['project_ref'], str)
                    or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', project['project_ref'])
                    or project['project_ref'] in refs or not isinstance(project['root'], str)
                    or not Path(project['root']).is_absolute() or '..' in Path(project['root']).parts):
                raise ValueError('Invalid notification project')
            refs.add(project['project_ref'])
        return value

    @classmethod
    def read_config(cls, path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 65536):
                raise ValueError('Browser notification configuration must be a private regular file')
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Notification configuration too large')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result: raise ValueError('Duplicate notification configuration key')
                result[key] = value
            return result
        return cls.validate_config(json.loads(raw, object_pairs_hook=unique))

    @classmethod
    def configured(cls):
        instance = cls(cls.read_config(CONFIG))
        instance.config_path = CONFIG
        return instance

    def refresh(self):
        if hasattr(self, 'config_path'):
            try:
                self.config = self.read_config(self.config_path)
            except (OSError, ValueError, TypeError):
                self.config = None  # No mutation authority on malformed/unknown local configuration.
        return self.config

    def projects(self):
        c = self.config
        if not c: return []
        if c.get('version') == 3:
            # The live authorized registry is the only catalog; never scan disk.
            return self.registered_projects() if self.registered_projects else []
        return [dict(project_ref=c['project_ref'], root=c['root'])] if 'project_ref' in c else c['projects']

    def accepts(self, project_ref, root):
        return any((p['project_ref'], p['root']) == (project_ref, root) for p in self.projects())

    @staticmethod
    def scope_id(project):
        return hashlib.sha256((project['project_ref'] + '\0' + project['root']).encode()).hexdigest()

    def publish(self, work):
        batch = work.get('browser_notification_batch')
        if batch is not None:
            member = batch['members'][work['work_ref']]
            member.update(state=work['state'], result_class=work['result_class'],
                          classification_report_status=work['report_status'], settled_at=work['settled_at'])
            self._publish_batch(batch)
            return
        c = self.refresh()
        if (c and work.get('result_class') == 'result_ready' and work.get('report_status') == 'readable'
                and self.accepts(work['project_ref'], work['workspace_root'])
                and 'browser_notification_sequence' not in work):
            self.sequence += 1
            work['browser_notification_sequence'] = self.sequence

    def begin_batch(self, project_ref, root, requested):
        # Attached to retained Works, never a report pin or an independent durable queue.
        self.refresh()
        if not self.accepts(project_ref, root):
            return None
        return {'batch_ref': 'batch-' + secrets.token_hex(8), 'requested': requested,
                'members': {}, 'sealed': False, 'project_ref': project_ref, 'root': root}

    def reserve(self, batch, work):
        if batch is not None:
            work['browser_notification_batch'] = batch
            batch['members'][work['work_ref']] = {'work_ref': work['work_ref'], 'state': 'running',
                'result_class': None, 'classification_report_status': None, 'settled_at': None}

    def discard(self, work):
        batch = work.get('browser_notification_batch')
        if batch is not None:
            batch['members'].pop(work['work_ref'], None)

    def expire(self, work):
        batch = work.get('browser_notification_batch')
        if batch is not None:
            # Expiry is authoritative identity loss, not a successful final classification.
            batch['members'][work['work_ref']].update(state='expired', result_class='unavailable',
                classification_report_status='unavailable', settled_at=work['settled_at'])
            self._publish_batch(batch)

    def seal(self, batch):
        if batch is not None:
            batch['sealed'] = True
            self._publish_batch(batch)

    def _publish_batch(self, batch):
        if (batch['sealed'] and batch['members'] and 'sequence' not in batch
                and all(m['result_class'] is not None for m in batch['members'].values())):
            self.sequence += 1
            batch['sequence'] = self.sequence

    async def _batch_event(self, batch, retained, read_report):
        members = []
        for original in batch['members'].values():
            m = {k: original[k] for k in ('work_ref', 'state', 'result_class', 'classification_report_status')}
            work = retained.get(m['work_ref'])
            if work is None or work.get('browser_notification_batch') is not batch:
                result = {'ok': False, 'error_type': 'WorkNotificationIdentityLost'}
            else:
                result = await read_report(work)
            if result.get('ok'):
                m.update(report_status='readable', report_sha256=result['file_sha256'])
            else:
                error = result.get('error_type')
                if error == 'WorkNotificationIdentityLost':
                    m.update(state='expired', result_class='unavailable', report_status='unavailable')
                elif error == 'WorkReportMissing' and m['classification_report_status'] != 'readable':
                    m['report_status'] = 'missing'
                elif error in ('WorkReportNotRegular', 'WorkReportTooLarge', 'WorkReportSymlinkRejected',
                               'WorkReportInvalidUTF8', 'WorkReportEmpty') and m['classification_report_status'] != 'readable':
                    m['report_status'] = 'invalid'
                else:
                    return None  # Transient/unknown read failure holds this sequence and all later ones.
            members.append(m)
        return {'batch_ref': batch['batch_ref'], 'project_ref': batch['project_ref'],
                'sequence': batch['sequence'], 'requested': batch['requested'],
                'not_submitted': batch['requested'] - len(members), 'members': members,
                'ready_at': max(m['settled_at'] for m in batch['members'].values())}

    def routes(self, snapshot, read_report, resolve_project=None):
        async def endpoint(request):
            c = self.refresh()
            if not c:
                return JSONResponse({'error': 'disabled'}, status_code=404)
            origin = 'chrome-extension://' + c['extension_id']
            headers = request.headers
            # This endpoint must not become reachable through a public tunnel or web page.
            # Host-permitted extension GETs can omit Origin. The independent bearer
            # capability is mandatory; foreign web Origins remain refused, and no CORS
            # preflight or allow-origin response grants a web page access.
            allowed = (request.client and request.client.host in ('127.0.0.1', '::1')
                       and headers.get('host') == f"127.0.0.1:{c['port']}"
                       and headers.get('origin') in (None, origin)
                       and len(headers.getlist('authorization')) == 1
                       and hmac.compare_digest(headers.get('authorization', ''), 'Bearer ' + c['token']))
            if not allowed:
                return JSONResponse({'error': 'unauthorized'}, status_code=403)
            projects = []
            for project in self.projects():
                try:
                    if resolve_project and resolve_project(project['project_ref']) != project['root']:
                        continue
                    projects.append({**project, 'scope_id': self.scope_id(project)})
                except Exception:
                    continue  # Invalid registration cannot disable a different project.
            if request.url.path.endswith('/projects'):
                return JSONResponse({'projects': projects}, headers={'Cache-Control': 'no-store'})
            ref = request.query_params.get('project_ref', c.get('project_ref'))
            selected = next((p for p in projects if p['project_ref'] == ref), None)
            if not selected or request.query_params.get('scope_id', selected['scope_id']) != selected['scope_id']:
                return JSONResponse({'error': 'project_unavailable'}, status_code=410)
            c = {**c, **selected}
            if request.method == 'POST':
                raw = await request.body()
                if len(raw) > 32768:
                    return JSONResponse({'error': 'too_large'}, status_code=413)
                try:
                    value = json.loads(raw)
                    if not isinstance(value, dict) or set(value) - {'enabled','route','error','epoch','cursor','worker','observedAt','binding','deliveries','legacy'}:
                        raise ValueError()
                    # Diagnostics only, never used to authorize dispatch, receipt or Work state.
                    self.status = {'received_at': time.time(), 'extension_observation': value}
                    self.statuses[c['scope_id']] = self.status
                except (ValueError, TypeError):
                    return JSONResponse({'error': 'invalid'}, status_code=400)
                return JSONResponse({'ok': True}, headers={'Cache-Control': 'no-store'})
            try:
                if set(request.query_params) - {'after','epoch','check','status','project_ref','scope_id'}:
                    raise ValueError()
                after = int(request.query_params.get('after', '0'))
                if after < 0 or after > 2**53-1:
                    raise ValueError()
                check = request.query_params.get('check')
                if check is not None and not (WORK.fullmatch(check) or BATCH.fullmatch(check)):
                    raise ValueError()
            except (ValueError, TypeError):
                return JSONResponse({'error': 'invalid_query'}, status_code=400)
            if 'status' in request.query_params:
                return JSONResponse({'epoch': self.epoch, 'status': self.statuses.get(c['scope_id'])}, headers={'Cache-Control': 'no-store'})
            if request.query_params.get('epoch', self.epoch) != self.epoch:
                return JSONResponse({'epoch': self.epoch, 'reset': True, 'events': [], 'cursor': 0}, headers={'Cache-Control': 'no-store'})
            # Snapshot only this explicit project/root. Work identity is rechecked by read_report.
            items = snapshot(c['project_ref'], c['root'])
            retained = {w['work_ref']: w for w in items}
            batches = {w['browser_notification_batch']['batch_ref']: w['browser_notification_batch']
                       for w in items if w.get('browser_notification_batch')}
            records = [(w['browser_notification_sequence'], w['work_ref'], w, False)
                       for w in items if w.get('browser_notification_sequence')]
            records += [(b['sequence'], b['batch_ref'], b, True) for b in batches.values() if b.get('sequence')]
            events = []
            cursor = after
            blocked = None
            availability = {'work_ref': check, 'state': 'unavailable', 'code': 'WORK_IDENTITY_LOST'} if check else None
            for seq, ref, w, is_batch in sorted(records, key=lambda row: row[0]):
                if (check is None and seq <= after) or (check is not None and ref != check):
                    continue
                if is_batch:
                    event = await self._batch_event(w, retained, read_report)
                    if event is None:
                        blocked = {'batch_ref': ref, 'sequence': seq, 'code': 'REPORT_READ_TEMPORARY'}
                        if check:
                            availability = {'work_ref': check, 'state': 'retry', 'code': 'REPORT_READ_TEMPORARY'}
                        break
                    events.append(event)
                    cursor = max(cursor, seq)
                    if check:
                        availability = {'work_ref': check, 'state': 'readable', 'code': 'BATCH_METADATA_READY'}
                    if len(events) >= 16:
                        break
                    continue
                result = await read_report(w)
                if not result.get('ok'):
                    if result.get('error_type') == 'WorkNotificationIdentityLost':
                        # The registry identity was explicitly lost, not just an I/O failure.
                        cursor = max(cursor, seq)
                        continue
                    # A retained report can recover (including missing/changed/unreadable).
                    # Do not advance past it or expose later sequences out of order.
                    blocked = {'work_ref': w['work_ref'], 'sequence': seq, 'code': 'REPORT_READ_TEMPORARY'}
                    if check:
                        availability = {'work_ref': check, 'state': 'retry', 'code': 'REPORT_READ_TEMPORARY'}
                    break
                cursor = max(cursor, seq)
                events.append({'work_ref': w['work_ref'], 'project_ref': c['project_ref'], 'sequence': seq,
                               'report_sha256': result['file_sha256'], 'ready_at': w['settled_at'],
                               'result_class': 'result_ready', 'report_status': 'readable'})
                if check:
                    availability = {'work_ref': check, 'state': 'readable', 'code': 'REPORT_READABLE'}
                if len(events) >= 16:
                    break
            return JSONResponse({'epoch': self.epoch, 'events': events, 'cursor': cursor,
                                 'latest': self.sequence, **({'blocked': blocked} if blocked else {}),
                                 **({'check': availability} if check else {})}, headers={'Cache-Control': 'no-store'})
        return [Route('/browser-notifications/v1/events', endpoint, methods=['GET', 'POST']),
                Route('/browser-notifications/v1/projects', endpoint, methods=['GET'])]
