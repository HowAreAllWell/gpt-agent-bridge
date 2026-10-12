"""Selected literal regular-file staging into a private index, never Git add.

Raw blob staging avoids worktree rereads and helper execution. Conversion-requiring
attributes/config are explicitly unsupported in this first slice. The caller owns
candidate validation, index lock, installation, and unknown-outcome handling.
"""
import hashlib
import os
from pathlib import Path
import secrets
import stat
import tempfile
import time

from .file_observation import _Walk, _FILE_FLAGS, _signature, path_parts
from .commit_candidate import _need, _hash, _json_hash, _file, _directory, MAX_BYTES

# Bound temporary inodes, captured records and repeated filesystem validation,
# independently of Git command count. Byte/deadline/cache limits also apply.
MAX_SELECTED_PATHS = 2048
MAX_SELECTION_PATH_BYTES = 16 * 1024


def selection_paths(paths):
    _need(isinstance(paths, list) and bool(paths), 'nonempty-literal-selection-required')
    _need(len(paths) <= MAX_SELECTED_PATHS, 'selection-path-count-limit')
    result, seen, path_bytes = [], set(), 0
    for path in paths:
        parts = path_parts(path)
        _need(not any(p in ('', '.', '..', '.git') for p in path.split('/')) and '\\' not in path,
              'literal-relative-path-required')
        _need(parts and path not in seen, 'duplicate-selection')
        seen.add(path)
        path_bytes += len(path.encode('utf-8'))
        _need(path_bytes <= MAX_SELECTION_PATH_BYTES, 'selection-path-byte-limit')
        result.append(path)
    return result


def _write_selected_blobs(binding, captured, effects):
    """One raw-object write over captured bytes, never selected worktree paths.

    A private /tmp directory and generated ASCII filenames keep Git's line-based
    --stdin-paths unambiguous. Names travel on stdin, not argv (no count-dependent
    ARG_MAX pressure). All returned OIDs must match the captured-byte hashes in
    order before the caller updates even its private index.
    """
    blobs = [(item[0], selected[1]) for item, selected in captured.values()
             if selected is not None]
    if not blobs:
        return
    with tempfile.TemporaryDirectory(prefix='bridge-selected-blobs-', dir='/tmp') as temp:
        names = []
        for number, (content, _) in enumerate(blobs):
            _need(time.monotonic() < binding.deadline, 'operation-deadline')
            name = Path(temp) / str(number)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            names.append(str(name).encode('ascii') + b'\n')
        effects['objects_may_remain'] = True  # Set before the non-idempotent call.
        actual = binding.git(['hash-object', '-w', '--no-filters', '--stdin-paths'],
                             input_bytes=b''.join(names))
        _need(actual == b''.join(oid + b'\n' for _, oid in blobs), 'selected-blob-mismatch')


def selected_bytes(target, path):
    parts = path_parts(path)
    try:
        with _Walk(target, parts[:-1]) as walk:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=walk.fd)
            try:
                before = os.fstat(fd)
                _need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, 'selected-regular-bounded-file-required')
                data = bytearray()
                while len(data) <= MAX_BYTES:
                    chunk = os.read(fd, min(65536, MAX_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                _need(len(data) <= MAX_BYTES, 'selected-file-byte-limit')
                _need(_signature(before) == _signature(os.fstat(fd)) ==
                      _signature(os.stat(parts[-1], dir_fd=walk.fd, follow_symlinks=False)), 'selected-file-changed')
                walk.verify()
                return bytes(data), _signature(before)
            finally:
                os.close(fd)
    except FileNotFoundError:
        return None


def helper_policy(binding, paths):
    # Parse effective config; snapshot separately binds original config bytes.
    raw = binding.git(['config', '--null', '--list', '--includes'])
    config = {}
    for record in raw.rstrip(b'\0').split(b'\0'):
        key, _, value = record.partition(b'\n')
        config[key.decode().lower()] = value.decode()
    _need(not any(k.startswith('filter.') and k.endswith(('.clean', '.process')) and v
                  for k, v in config.items()), 'preparation-filters-unsupported')
    _need(config.get('core.autocrlf', 'false').lower() in ('false', 'no', 'off', '0'),
          'preparation-autocrlf-unsupported')
    hooks = Path(config.get('core.hookspath', str(binding.common / 'hooks')))
    if not hooks.is_absolute():
        hooks = binding.root / hooks
    state = []
    if str(hooks) != '/dev/null' and os.path.lexists(hooks):
        state.append(_directory(hooks))
        hook = hooks / 'post-index-change'
        if os.path.lexists(hook):
            st = hook.lstat()
            _need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, 'indirect-index-hook-location')
            _need(not os.access(hook, os.X_OK), 'active-index-hook-unsupported')
            state.append((st.st_mode, _hash(_file(hook))))
    attrs = binding.git(['check-attr', '-z', '--stdin', 'filter', 'text', 'eol', 'working-tree-encoding', 'ident'],
                        input_bytes=b''.join(p.encode() + b'\0' for p in paths))
    fields = attrs.split(b'\0')
    _need(fields[-1] == b'' and len(fields[:-1]) == 15 * len(paths), 'attribute-observation-malformed')
    _need(all(value in (b'unspecified', b'unset') for value in fields[2:-1:3]),
          'preparation-conversion-attributes-unsupported')
    return _json_hash([config, str(hooks), state, _hash(attrs)]), config


def stage_private(binding, target, paths, before, private, effects):
    from .commit_candidate import _index_tree
    policy, config = helper_policy(binding, paths)
    algorithm = binding.git(['rev-parse', '--show-object-format']).decode().strip()
    raw = binding.git(['ls-files', '--stage', '--full-name', '-z'], index=private)
    _index_tree(raw, algorithm)  # Refuse unmerged, unavailable objects/modes/paths.
    entries = {}
    for record in raw.rstrip(b'\0').split(b'\0') if raw else []:
        meta, path = record.split(b'\t', 1)
        mode, oid, _ = meta.split(b' ')
        entries[path.decode()] = (mode, oid)
    flags = binding.git(['ls-files', '-v', '--full-name', '-z'], index=private)
    selected_paths = set(paths)
    for record in flags.rstrip(b'\0').split(b'\0') if flags else []:
        if record[2:].decode() in selected_paths:
            _need(record[:1] == b'H', 'selected-index-flags-unsupported')
    diff = ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames", "--raw", "--no-abbrev", "-z"]
    hidden = binding.git([*diff, "--ita-invisible-in-index", before["parent"], "--"], index=private)
    visible = binding.git([*diff, "--ita-visible-in-index", before["parent"], "--"], index=private)
    _need(hidden == visible, "intent-to-add-unsupported")
    head = {}
    raw = binding.git(['ls-tree', '-r', '-z', before['parent']])
    for record in raw.rstrip(b'\0').split(b'\0') if raw else []:
        meta, path = record.split(b'\t', 1)
        mode, _, oid = meta.split(b' ')
        head[path.decode()] = (mode, oid)
    staged = {p for p in entries.keys() | head.keys() if entries.get(p) != head.get(p)}
    _need(staged <= selected_paths, 'staged-paths-outside-selection')
    captured, total = {}, 0
    changes = bytearray()
    # Capture every selected file and validate partial staging before object writes.
    for path in paths:
        _need(time.monotonic() < binding.deadline, 'operation-deadline')
        item = selected_bytes(target, path)
        captured[path] = item
        prior = entries.get(path)
        _need(prior is None or prior[0] in (b'100644', b'100755'), 'selected-index-mode-unsupported')
        if item is None:
            _need(path in head or prior is not None, 'selected-missing-untracked-file')
            selected = None
        else:
            content, signature = item
            total += len(content)
            _need(total <= MAX_BYTES, 'selection-total-byte-limit')
            mode = b'100755' if signature[2] & 0o111 else b'100644'
            if prior and config.get('core.filemode', 'true').lower() in ('false', 'no', 'off', '0'):
                mode = prior[0]
            oid = hashlib.new(algorithm, b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest().encode()
            selected = (mode, oid)
        _need(path not in staged or prior == selected, 'selected-mixed-staged-unstaged')
        captured[path] = (item, selected)
    binding.storage()
    _write_selected_blobs(binding, captured, effects)
    for path, (item, selected) in captured.items():
        if selected is None:
            changes.extend(b'0 ' + b'0' * len(before['parent']) + b'\t' + path.encode() + b'\0')
        else:
            changes.extend(selected[0] + b' ' + selected[1] + b'\t' + path.encode() + b'\0')
    # Active hooks were refused, not silently honored/suppressed. This fixed
    # override also prevents a newly introduced hook running in the check/use gap.
    binding.git(['-c', 'core.hooksPath=/dev/null', 'update-index', '-z', '--index-info'],
                index=private, input_bytes=bytes(changes))
    return captured, policy


def verify_selection(binding, target, paths, captured, policy):
    _need(helper_policy(binding, paths)[0] == policy, 'preparation-policy-changed')
    for path, (original, _) in captured.items():
        _need(time.monotonic() < binding.deadline, 'operation-deadline')
        _need(selected_bytes(target, path) == original, 'selected-file-changed')


def install_index(binding, index):
    """Caller holds the conventional index.lock and has just checked HEAD/index."""
    name = '.bridge-prepared-index-' + secrets.token_hex(16)
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=binding.fds[1])
    try:
        pending = memoryview(index)
        while pending:
            written = os.write(fd, pending)
            _need(written > 0, 'prepared-index-short-write')
            pending = pending[written:]
        mode = stat.S_IMODE(os.stat('index', dir_fd=binding.fds[1], follow_symlinks=False).st_mode)
        os.fchmod(fd, mode)
        os.fsync(fd)
        os.replace(name, 'index', src_dir_fd=binding.fds[1], dst_dir_fd=binding.fds[1])
        os.fsync(binding.fds[1])
    finally:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=binding.fds[1])
        except FileNotFoundError:
            pass
