"""Opt-in, fixed-argument Git grep for tracked + nonignored untracked text.

The existing tracked-only branch is unchanged. This branch does not call the
legacy full-capture helper, dirty fingerprint or whole-worktree result wrapper.
Bridge pipe storage is capped; this is not a bound on Git's internal memory or
filesystem syscall latency. No shell, hooks, textconv or network is requested.
"""
from __future__ import annotations

import os
import hashlib
import stat
import fixed_git
import time

from file_observation import (
    FileObservation, ObservationError, _Walk, _signature, path_parts, error,
    json_size, MAX_JSON_BYTES,
)

MAX_STDOUT = 1024 * 1024
MAX_STDERR = 4096
GREP_SECONDS = 5.0
MAX_MATCH_OFFSET = 100000
MAX_MATCHES = 50
MAX_LINE_CHARS = 300


def grep_argv(query: str, prefix: str | None, *, untracked: bool = True) -> list[str]:
    argv = ['git', '--no-pager', '--no-optional-locks', '-c', 'core.fsmonitor=false',
            '-c', 'grep.threads=1', 'grep',
            '--no-textconv', '--no-recurse-submodules', '--no-color', '--no-column',
            '-z', '-F',
            '-n', '-I', '-e', query, '--']
    if untracked:
        argv[argv.index('grep') + 1:argv.index('grep') + 1] = ['--untracked', '--exclude-standard']
    if prefix:
        argv.append(':(literal)' + prefix)
    return argv


def _capture(fd: int, query: str, prefix: str | None, *, untracked: bool = True, deadline: float | None = None, stdout_budget: int | None = None) -> tuple[int, bytes]:
    # Descriptor-bound cwd is preserved for both the config probe and Git query.
    end = deadline if deadline is not None else time.monotonic() + GREP_SECONDS
    argv = grep_argv(query, prefix, untracked=untracked)
    args = argv[argv.index('grep'):]
    rc, raw, _err = fixed_git.observe(
        f'/proc/self/fd/{fd}', args, timeout=max(0, end-time.monotonic()),
        stdout_limit=MAX_STDOUT if stdout_budget is None else stdout_budget,
        stderr_limit=MAX_STDERR, pass_fds=(fd,))
    if rc == fixed_git.TOO_LARGE:
        raise ObservationError('SearchObservationTooLarge', 'Git grep pipe budget exceeded; no complete search is claimed.')
    if rc == fixed_git.UNSUPPORTED:
        raise ObservationError('GitObservationUnsupported', 'Filter-dependent Git search is unsupported; coverage is unknown.')
    if rc < 0:
        raise ObservationError('SearchTimedOut' if b'Timeout' in _err else 'SearchFailed',
                               'Git search observation failed; coverage is unknown.')
    return rc, raw


def _parse(raw: bytes, query: str, path_prefix: str | None, offset: int, limit: int) -> dict:
    result = {'ok': True, 'query': query, 'path_prefix': path_prefix, 'matches': [],
              'match_offset': offset, 'match_next_offset': None,
              'coverage': {'tracked_files': 'included', 'untracked_files': 'included_nonignored',
                           'ignored_files': 'excluded_unless_tracked', 'binary_files': 'excluded',
                           'symlinks': 'not_followed_by_git_grep', 'search_mode': 'fixed_string_literal',
                           'pagination': 'fresh_observation', 'scan_complete': True}}
    cursor = count = 0
    seen = {}
    page_full = False
    while cursor < len(raw):
        p_end = raw.find(b'\0', cursor)
        n_end = raw.find(b'\0', p_end + 1) if p_end >= 0 else -1
        l_end = raw.find(b'\n', n_end + 1) if n_end >= 0 else -1
        if min(p_end, n_end, l_end) < 0:
            raise ObservationError('SearchOutputMalformed', 'Incomplete grep record; no complete search is claimed.')
        number = raw[p_end + 1:n_end]
        if not number.isdigit() or len(number) > 12 or int(number) < 1:
            raise ObservationError('SearchOutputMalformed', 'Invalid grep line number.')
        try:
            path = raw[cursor:p_end].decode('utf-8')
        except UnicodeError:
            raise ObservationError('PathEncodingUnsupported', 'Grep path is not valid UTF-8; no replacement locator is returned.') from None
        path_parts(path)
        # Existing read refuses strings containing only whitespace. './' keeps
        # the exact file address without stripping or altering the filename.
        if not path.strip():
            path = './' + path
        key = (path, int(number))
        digest = hashlib.sha256(raw[n_end + 1:l_end]).digest()
        if key in seen:
            if seen[key] != digest:
                raise ObservationError('SearchChanged', 'Two bounded grep passes disagree on a matching line.')
            cursor = l_end + 1
            continue
        seen[key] = digest
        if count >= offset and not page_full:
            # Raw observation is capped; snippets alone reach the model.
            line = raw[n_end + 1:l_end].decode('utf-8', errors='replace')
            item = {'path': path, 'line_number': int(number),
                    'line_text': line[:MAX_LINE_CHARS], 'line_text_truncated': len(line) > MAX_LINE_CHARS,
                    'read_locator': {'path': path, 'start_line': int(number)}}
            result['matches'].append(item)
            if len(result['matches']) > limit or json_size(result) > MAX_JSON_BYTES - 8192:
                result['matches'].pop()
                page_full = True
                if not result['matches']:
                    raise ObservationError('ResponseTooLarge', 'A complete match locator does not fit the JSON budget.')
        count += 1
        cursor = l_end + 1
    if offset + len(result['matches']) < count:
        result['match_next_offset'] = offset + len(result['matches'])
    result['total_matches'] = count
    result['match_count'] = len(result['matches'])
    result['matches_truncated'] = result['match_next_offset'] is not None
    result['pagination'] = {'unit': 'matches', 'offset': offset, 'next_offset': result['match_next_offset']}
    return result


def _both_passes(fd, query, prefix):
    end = time.monotonic() + GREP_SECONDS
    parts = []
    size = 0
    # --untracked --exclude-standard omits even tracked paths matching ignore.
    # Retain the default tracked set via a separate fixed-argument bounded pass.
    for untracked in (False, True):
        rc, raw = _capture(fd, query, prefix, untracked=untracked, deadline=end, stdout_budget=MAX_STDOUT - size)
        if rc not in (0, 1):
            raise ObservationError('SearchFailed', 'Git grep failed; no complete search is claimed.')
        if rc == 1 and raw:
            raise ObservationError('SearchOutputMalformed', 'No-match status contradicts grep output.')
        size += len(raw)
        if size > MAX_STDOUT:
            raise ObservationError('SearchObservationTooLarge', 'Combined grep output exceeds the search budget.')
        parts.append(raw)
    return b''.join(parts)


def _search(target, query, path_prefix, max_matches, match_offset):
    parts = path_parts(path_prefix, directory=True) if path_prefix is not None else []
    prefix = '/'.join(parts) or None
    with _Walk(target, []) as root:
        if parts:
            with _Walk(target, parts[:-1]) as parent:
                before = os.stat(parts[-1], dir_fd=parent.fd, follow_symlinks=False)
                if not (stat.S_ISREG(before.st_mode) or stat.S_ISDIR(before.st_mode)):
                    raise ObservationError('SearchPrefixRejected', 'Search prefix must be a regular file or directory, not a link or special file.')
                raw = _both_passes(root.fd, query, prefix)
                after = os.stat(parts[-1], dir_fd=parent.fd, follow_symlinks=False)
                if _signature(before) != _signature(after):
                    raise ObservationError('SearchTargetChanged', 'Search prefix changed during observation.')
                parent.verify()
        else:
            raw = _both_passes(root.fd, query, prefix)
        root.verify()
    return _parse(raw, query, path_prefix, match_offset, max_matches)


class UntrackedSearch(FileObservation):
    async def search(self, project_ref: str, query: str, path_prefix: str | None = None,
                     max_matches: int = 20, work_ref: str | None = None, match_offset: int = 0) -> dict:
        """Explicit tracked + nonignored untracked search branch; no new MCP tool."""
        if not isinstance(query, str) or not query or len(query) > 500 or '\0' in query or '\n' in query:
            return error('InvalidQuery', 'Use 1..500 characters without NUL or LF (one literal pattern).')
        try:
            query.encode('utf-8')
            if path_prefix is not None:
                path_parts(path_prefix, directory=True)
        except (UnicodeError, ObservationError):
            return error('InvalidPathOrQuery', 'Use valid UTF-8 query and a confined relative prefix.')
        if type(max_matches) is not int or not 1 <= max_matches <= MAX_MATCHES:
            return error('InvalidLimit', 'max_matches must be an integer from 1 through 50.')
        if type(match_offset) is not int or not 0 <= match_offset <= MAX_MATCH_OFFSET:
            return error('InvalidMatchOffset', 'match_offset must be an integer from 0 through 100000.')
        return await self._observe(project_ref, work_ref, _search, query, path_prefix, max_matches, match_offset)
