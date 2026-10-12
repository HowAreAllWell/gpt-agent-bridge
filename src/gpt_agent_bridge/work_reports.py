"""Process-local report files for every admitted Work. No provider transcript or terminal capture."""
import atexit
import errno
import hashlib
import json
import os
import secrets
import stat
import tempfile
import threading

MAX_REPORT_BYTES = 1024 * 1024


def error(code):
    return {'ok': False, 'error_type': code, 'error': 'Agent report unavailable: ' + code}


class ReportStore:
    """Lazy private directory; only allocated basenames can be opened or removed.

    A lock serializes bounded reads with expiry cleanup. Same-user Agents are not
    OS-isolated from each other; these files do not authenticate report authorship.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._root = None
        self._fd = None
        self._keys = set()
        atexit.register(self.close)

    def allocate(self):
        with self._lock:
            if self._fd is None:
                self._root = tempfile.mkdtemp(prefix='bridge-reports-', dir='/tmp')
                os.chmod(self._root, 0o700)
                self._fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            key = secrets.token_hex(24) + '.txt'
            while key in self._keys:
                key = secrets.token_hex(24) + '.txt'
            self._keys.add(key)
            return key

    def augment(self, task, key):
        with self._lock:
            if key not in self._keys:
                raise ValueError('unknown report allocation')
            path = os.path.join(self._root, key)
            return task + (
                '\n\n[Bridge final-report publication]\n'
                'Before your terminal final response, publish your COMPLETE final report as UTF-8 '
                f'(at most {MAX_REPORT_BYTES} bytes) to {json.dumps(path)}. '
                'This grants only report publication in addition to the task above: '
                f'write the complete content to the exact staging file {json.dumps(path + ".pending")}, '
                'then atomically rename it to the report path. No other file changes are authorized '
                'by this instruction. Do not summarize or truncate the report to fit terminal output. '
                'Do not print these private paths in your terminal response. If publication is '
                'unavailable, say so; never claim it succeeded.\n'
                '\n[Report authoring]\n'
                "Within the task's requested format, put your conclusion, decisive evidence, and "
                'material limitations first, followed by supporting detail. Headings are optional; '
                'keep the complete report free-form. Publication does not establish task success, '
                'truth, or authenticated authorship.\n')

    def discard(self, key):
        with self._lock:
            if key not in self._keys:
                return
            for name in (key, key + '.pending'):
                try:
                    os.unlink(name, dir_fd=self._fd)
                except OSError:
                    pass  # Best effort; never traverse an Agent-created directory.
            self._keys.remove(key)

    def close(self):
        """Idempotent best-effort teardown, safe under the RLock.

        Unlinks only allocated final/staging basenames (discarding each key as
        ownership state is consumed), then attempts directory cleanup. A late
        Agent write, unlink failure or permission error can leave residue;
        unknown names are never removed and no secure erasure is claimed.
        Safe to call repeatedly (whole-server lifespan shutdown, then atexit).
        """
        with self._lock:
            for key in list(self._keys):
                self.discard(key)
            fd, root, self._fd, self._root = self._fd, self._root, None, None
            if fd is None:
                return
            try:
                os.close(fd)
            except OSError:
                pass  # Best effort: teardown must not fail on a double close.
            try:
                os.rmdir(root)
            except OSError:
                pass  # Residue stays; never broaden deletion to unknown names.

    def read(self, key, offset, limit, expected_sha256):
        with self._lock:
            if key not in self._keys:
                return error('WorkReportMissing')
            fd = None
            try:
                # O_NONBLOCK prevents a FIFO from hanging before fstat rejects it.
                fd = os.open(key, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._fd)
                before = os.fstat(fd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    return error('WorkReportNotRegular')
                if before.st_size > MAX_REPORT_BYTES:
                    return error('WorkReportTooLarge')
                chunks, size = [], 0
                while size <= MAX_REPORT_BYTES:
                    chunk = os.read(fd, min(65536, MAX_REPORT_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                if size > MAX_REPORT_BYTES:
                    return error('WorkReportTooLarge')
                after = os.fstat(fd)
                bound = os.stat(key, dir_fd=self._fd, follow_symlinks=False)
                identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                if identity(before) != identity(after) or identity(after) != identity(bound):
                    return error('WorkReportChanged')
                raw = b''.join(chunks)
            except FileNotFoundError:
                return error('WorkReportMissing')
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    return error('WorkReportSymlinkRejected')
                return error('WorkReportUnreadable')
            finally:
                if fd is not None:
                    os.close(fd)
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError:
            return error('WorkReportInvalidUTF8')
        if not content.strip():
            return error('WorkReportEmpty')
        digest = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            return error('WorkReportVersionChanged')
        page = content[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(content) else None
        return {'ok': True, 'content': page, 'file_sha256': digest, 'file_size_bytes': len(raw),
                'content_offset': offset, 'content_end_offset': offset + len(page),
                'content_total_chars': len(content), 'content_page_chars': len(page),
                'content_next_offset': next_offset, 'content_has_more': next_offset is not None,
                'content_limit': limit, 'offset_unit': 'unicode_characters',
                'pagination': {'unit': 'unicode_characters', 'offset': offset, 'next_offset': next_offset},
                'provenance': {'source': 'agent_published_report', 'proves': 'observed_content_only',
                               'provider_transcript': False, 'task_success': 'not_established',
                               'author_identity': 'not_authenticated', 'atomic_snapshot': False}}
