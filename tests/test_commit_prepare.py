"""Constrained preparation in real temporary main/linked repositories."""
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault("BRIDGE_PATH_TOKEN", "test-token-abcdefghijklmnopqrstuvwxyz-012345")

import commit_candidate as candidate
import commit_preparation as preparation
import fixed_git
import server
from evidence_target import EvidenceCheckout, EvidenceTarget
from tests import test_commit_candidate as fixtures
from workspace_context import WorkspaceContext, WorkspaceRegistry, WorkspaceRegistryStore, canonical_git_worktree


class CommitPrepareTests(unittest.TestCase):
    setUp = fixtures.CommitCandidateTests.setUp
    git = fixtures.CommitCandidateTests.git
    resolve = fixtures.CommitCandidateTests.resolve
    index = fixtures.CommitCandidateTests.index

    def prepare(self, paths, **kwargs):
        return self.store.prepare('p', paths=paths, **kwargs)

    def external(self, *args, root=None):
        """Ungated Git (no --no-optional-locks): the ordinary external writer."""
        return subprocess.run([candidate.GIT, *args], cwd=root or self.root,
                              check=True, capture_output=True).stdout

    def external_status_refresh(self, path):
        """Deterministically move the path mtime eight seconds back, then
        run the ungated external status refresh that ordinary tools perform;
        returns index bytes. The whole-second change is visible to Git's
        stat comparison on every call, so each refresh really rewrites the
        installed index without any sleep."""
        path_stat = os.stat(path)
        os.utime(path, (path_stat.st_atime, path_stat.st_mtime - 8))
        self.external("status", "--porcelain=v1", "-uall")
        return self.index(self.root)

    def test_modification_new_binary_and_explicit_deletion_preserve_other_files(self):
        (self.root / 'file').unlink()
        (self.root / 'new').write_bytes(b'new\r\n')
        (self.root / 'binary').write_bytes(b'\0\xff')
        (self.root / 'untouched').write_bytes(b'keep')
        page = self.prepare(['file', 'new', 'binary'])
        self.assertEqual(page['status'], 'previewed', page)
        self.assertTrue(page['index_updated'])
        self.assertFalse(page['ref_updated'])
        self.assertEqual({(f['path'], f['status']) for f in page['files']},
                         {('file', 'D'), ('new', 'A'), ('binary', 'A')})
        prepared_index = self.index(self.root)
        result = self.store.commit('p', page['candidate_id'], 'exact selection')
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(self.index(self.root), prepared_index)
        self.assertEqual(self.git('show', 'HEAD:new'), b'new\r\n')
        self.assertEqual(self.git('show', 'HEAD:binary'), b'\0\xff')
        self.assertEqual((self.root / 'untouched').read_bytes(), b'keep')

    def test_linked_work_target_and_cached_paging_never_recapture(self):
        original = self.index(self.root)
        (self.linked / 'file').write_text('linked chosen\n')
        page = self.prepare(['file'], work_ref='work', view='patch', limit=7)
        self.assertEqual(page['status'], 'previewed', page)
        self.assertEqual(page['target_kind'], 'work_checkout')
        self.assertEqual(self.index(self.root), original)
        (self.linked / 'file').write_text('later unstaged\n')
        with patch.object(self.store, '_resolve', side_effect=AssertionError('must be cache-only')):
            again = self.store.prepare('p', 'work', candidate_id=page['candidate_id'], view='summary')
        self.assertFalse(again['repository_writes'])
        self.assertEqual(again['tree'], page['tree'])
        self.assertEqual(again['preparation'], page['preparation'])
        result = self.store.commit('p', page['candidate_id'], 'linked')
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(self.git('show', 'HEAD:file', root=self.linked), b'linked chosen\n')
        self.assertEqual((self.linked / 'file').read_text(), 'later unstaged\n')

    def test_no_paths_preserves_already_staged_partial_hunks(self):
        (self.root / 'file').write_text('chosen\n')
        self.git('add', 'file')
        (self.root / 'file').write_text('chosen\nleft unstaged\n')
        original = self.index(self.root)
        page = self.store.prepare('p')
        self.assertEqual(page['status'], 'previewed', page)
        self.assertFalse(page['repository_writes'])
        self.assertEqual(self.index(self.root), original)
        self.assertEqual(self.store.commit('p', page['candidate_id'], 'partial')['status'], 'committed')
        self.assertEqual(self.git('show', 'HEAD:file'), b'chosen\n')

    def test_mixed_selected_staging_rejected_without_overwriting_index(self):
        (self.root / 'file').write_text('chosen\n')
        self.git('add', 'file')
        (self.root / 'file').write_text('chosen\npartial hunk stays\n')
        original = self.index(self.root)
        page = self.prepare(['file'])
        self.assertEqual(page['reason'], 'selected-mixed-staged-unstaged', page)
        self.assertEqual(self.index(self.root), original)
        self.assertFalse(page['index_updated'])

    def test_already_fully_staged_selected_file_supported(self):
        (self.root / 'file').write_text('chosen\n')
        self.git('add', 'file')
        page = self.prepare(['file'])
        self.assertEqual(page['status'], 'previewed', page)

    def test_staged_outside_selection_rejected_and_preserved(self):
        (self.root / 'other').write_text('staged outside\n')
        self.git('add', 'other')
        (self.root / 'file').write_text('selected\n')
        original = self.index(self.root)
        page = self.prepare(['file'])
        self.assertEqual(page['reason'], 'staged-paths-outside-selection', page)
        self.assertEqual(self.index(self.root), original)

    def test_literal_paths_cannot_expand_or_recurse(self):
        (self.root / 'literal*').write_text('exact\n')
        (self.root / 'literal_other').write_text('not selected\n')
        page = self.prepare(['literal*'])
        self.assertEqual(page['status'], 'previewed', page)
        self.assertEqual([f['path'] for f in page['files']], ['literal*'])
        for paths in (['literal_*'], ['.'], ['..'], ['/etc/passwd'], ['.git/config'],
                      ['../other'], [':(glob)*'], ['file', 'file'], [], ['a/../file'],
                      ['a//file'], ['a\\file'], ['a/./file']):
            with self.subTest(paths=paths):
                original = self.index(self.root)
                result = self.prepare(paths)
                self.assertEqual(result['status'], 'rejected', result)
                self.assertEqual(self.index(self.root), original)

    def test_directory_symlink_special_and_symlink_parent_rejected(self):
        outside = self.base / 'outside'; outside.mkdir()
        (outside / 'file').write_text('outside\n')
        (self.root / 'dir').mkdir()
        (self.root / 'sym').symlink_to(outside / 'file')
        (self.root / 'parent').symlink_to(outside, target_is_directory=True)
        os.mkfifo(self.root / 'fifo')
        for path in ('dir', 'sym', 'parent/file', 'fifo'):
            with self.subTest(path=path):
                original = self.index(self.root)
                self.assertEqual(self.prepare([path])['status'], 'rejected')
                self.assertEqual(self.index(self.root), original)
        self.assertEqual((outside / 'file').read_text(), 'outside\n')

    def test_missing_untracked_rejected_and_missing_parent_tracked_deletion_supported(self):
        self.assertEqual(self.prepare(['absent'])['reason'], 'selected-missing-untracked-file')
        (self.root / 'dir').mkdir(); (self.root / 'dir/file').write_text('tracked\n')
        self.git('add', 'dir/file'); self.git('commit', '-m', 'nested')
        (self.root / 'dir/file').unlink(); (self.root / 'dir').rmdir()
        result = self.prepare(['dir/file'])
        self.assertEqual(result['status'], 'previewed', result)
        self.assertEqual(result['files'][0]['status'], 'D')

    def test_active_index_hook_refused_without_execution(self):
        hook = self.root / '.git/hooks/post-index-change'
        marker = self.base / 'HOOK_RAN'
        hook.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n'); hook.chmod(0o755)
        (self.root / 'file').write_text('selected\n')
        original = self.index(self.root)
        page = self.prepare(['file'])
        self.assertEqual(page['reason'], 'active-index-hook-unsupported', page)
        self.assertFalse(marker.exists())
        self.assertEqual(self.index(self.root), original)

    def test_clean_process_filters_and_conversion_attributes_refused(self):
        marker = self.base / 'FILTER_RAN'
        for config in ('filter.danger.clean', 'filter.danger.process'):
            with self.subTest(config=config):
                self.git('config', config, 'touch ' + str(marker))
                (self.root / 'file').write_text('selected\n')
                original = self.index(self.root)
                self.assertEqual(self.prepare(['file'])['reason'], 'preparation-filters-unsupported')
                self.assertEqual(self.index(self.root), original)
                self.assertFalse(marker.exists())
                self.git('config', '--unset', config)
        for attribute in ('filter=unconfigured', 'text', 'eol=lf', 'working-tree-encoding=UTF-16', 'ident'):
            with self.subTest(attribute=attribute):
                (self.root / '.gitattributes').write_text('file ' + attribute + '\n')
                self.assertEqual(self.prepare(['file'])['reason'], 'preparation-conversion-attributes-unsupported')
        (self.root / '.gitattributes').unlink()
        self.git('config', 'core.autocrlf', 'true')
        self.assertEqual(self.prepare(['file'])['reason'], 'preparation-autocrlf-unsupported')

    def test_flagged_and_unmerged_index_preserved(self):
        self.git('update-index', '--assume-unchanged', 'file')
        (self.root / 'file').write_text('selected\n')
        original = self.index(self.root)
        self.assertEqual(self.prepare(['file'])['reason'], 'selected-index-flags-unsupported')
        self.assertEqual(self.index(self.root), original)
        self.git('update-index', '--no-assume-unchanged', 'file')
        self.git('update-index', '--skip-worktree', 'file')
        self.assertEqual(self.prepare(['file'])['reason'], 'selected-index-flags-unsupported')

    def test_candidate_failure_never_installs_prepared_index(self):
        (self.root / 'file').write_text('selected\n')
        original = self.index(self.root)
        with patch.object(self.store, '_capture', side_effect=candidate.Refused('validation failure')):
            result = self.prepare(['file'])
        self.assertEqual(result['status'], 'rejected')
        self.assertFalse(result['index_updated'])
        self.assertEqual(self.index(self.root), original)
        self.assertFalse(self.store._items)

    def test_selected_working_file_race_refuses_install(self):
        (self.root / 'file').write_text('selected\n')
        original = self.index(self.root)
        capture = self.store._capture
        def race(*args):
            item = capture(*args)
            (self.root / 'file').write_text('external change\n')
            return item
        with patch.object(self.store, '_capture', side_effect=race):
            page = self.prepare(['file'])
        self.assertEqual(page['reason'], 'selected-file-changed', page)
        self.assertEqual(self.index(self.root), original)
        self.assertFalse(self.store._items)

    def test_real_index_race_preserves_external_staging(self):
        (self.root / 'file').write_text('selected\n')
        capture = self.store._capture
        changed = []
        def race(*args):
            item = capture(*args)
            (self.root / 'external').write_text('external\n'); self.git('add', 'external')
            changed.append(self.index(self.root))
            return item
        with patch.object(self.store, '_capture', side_effect=race):
            page = self.prepare(['file'])
        self.assertEqual(page['reason'], 'index_sha256-changed', page)
        self.assertEqual(self.index(self.root), changed[0])
        self.assertFalse(self.store._items)

    def test_install_uncertainty_seals_checkout_and_branch_without_candidate(self):
        (self.root / 'file').write_text('selected\n')
        install = preparation.install_index
        def lost(*args):
            install(*args)
            raise OSError('directory fsync uncertain')
        with patch.object(preparation, 'install_index', side_effect=lost):
            page = self.prepare(['file'])
        self.assertEqual(page['status'], 'unknown', page)
        self.assertIsNone(page['index_updated'])
        self.assertFalse(page['ref_updated'])
        self.assertFalse(page['retry_safe'])
        self.assertFalse(self.store._items)
        self.assertEqual(self.prepare(['file'])['reason'], 'checkout-quarantined-unknown-attempt')
        self.assertEqual(self.store.prepare('p')['reason'], 'checkout-quarantined-unknown-attempt')

    def test_outer_preparation_cleanup_failure_never_retains_new_candidate(self):
        (self.root / 'file').write_bytes(b'previous staged candidate')
        self.git('add', 'file')
        existing = self.store.prepare('p')
        self.assertEqual(existing['status'], 'previewed', existing)
        cached = set(self.store._items)
        # Already-staged selection is admissible; it still gets a fresh candidate.
        directory = candidate.tempfile.TemporaryDirectory
        observed = []
        class CleanupFailure:
            def __init__(inner, *args, **kwargs):
                inner.context = directory(*args, **kwargs)
            def __enter__(inner):
                inner.path = inner.context.__enter__()
                return inner.path
            def __exit__(inner, *args):
                observed.append((set(self.store._items), inner.path))
                inner.context.__exit__(*args)
                raise OSError('outer preparation cleanup unconfirmed')
        def temporary(*args, **kwargs):
            factory = CleanupFailure if kwargs.get('prefix') == 'bridge-candidate-prepare-' else directory
            return factory(*args, **kwargs)
        with patch.object(candidate.tempfile, 'TemporaryDirectory', side_effect=temporary):
            result = self.prepare(['file'])
        self.assertEqual(result['status'], 'unknown', result)
        self.assertEqual(result['reason'], 'outer preparation cleanup unconfirmed')
        self.assertTrue(result['index_updated'])
        self.assertTrue(result['objects_may_remain'])
        self.assertFalse(result['ref_updated'])
        self.assertIs(result['retry_safe'], False)
        self.assertNotIn('candidate_id', result)
        self.assertEqual(set(self.store._items), cached)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], cached)  # No publication even during cleanup.
        self.assertFalse(Path(observed[0][1]).exists())
        self.assertTrue(self.store._preparation_unknown)
        self.assertEqual(self.prepare(['file'])['reason'], 'checkout-quarantined-unknown-attempt')
        self.assertEqual(self.store.prepare('p')['reason'], 'checkout-quarantined-unknown-attempt')

    def test_paths_forbidden_on_paging_and_unknown_id_never_recaptures(self):
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        original = self.index(self.root)
        rejected = self.prepare(['file'], candidate_id=page['candidate_id'])
        self.assertEqual(rejected['reason'], 'paths-forbidden-with-candidate-id')
        self.assertEqual(self.store.prepare('p', candidate_id='lost')['reason'], 'candidate-unavailable-no-recapture')
        self.assertEqual(self.index(self.root), original)

    def test_final_commit_refuses_post_prepare_semantic_index_change(self):
        # A real staged change (new path/OID) is semantic drift, not a
        # harmless refresh; it still refuses without touching anything.
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        (self.root / 'other').write_text('other\n'); self.git('add', 'other')
        original = self.index(self.root)
        result = self.store.commit('p', page['candidate_id'], 'cannot recapture')
        self.assertEqual(result['reason'], 'index-semantic-drift')
        self.assertEqual(self.index(self.root), original)

    def test_commit_admits_external_status_refresh_and_preserves_latest_bytes(self):
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        prepared = self.index(self.root)
        # An ordinary external status refresh rewrites the installed index:
        # the freshly staged entry carries zeroed stat-cache fields until the
        # refresh fills them. Raw bytes change; staged semantics do not.
        self.external('status', '--porcelain=v1', '-uall')
        refreshed = self.index(self.root)
        self.assertNotEqual(refreshed, prepared)
        result = self.store.commit('p', page['candidate_id'], 'stat refresh admitted')
        self.assertEqual(result['status'], 'committed', result)
        self.assertFalse(result['index_unchanged'])
        self.assertEqual(result['admitted_index_sha256'], candidate._hash(refreshed))
        # The latest admitted real index bytes are preserved; the captured
        # candidate index is never reinstalled.
        self.assertEqual(self.index(self.root), refreshed)
        self.assertEqual(self.git('show', 'HEAD:file'), b'selected\n')

    def test_partial_hunk_commit_admits_unrelated_stat_refresh(self):
        (self.root / 'second').write_text('tracked\n')
        self.git('add', 'second')
        self.git('commit', '-m', 'second')
        (self.root / 'file').write_text('chosen\n')
        self.git('add', 'file')
        (self.root / 'file').write_text('chosen\nleft unstaged\n')
        page = self.store.prepare('p')
        self.assertEqual(page['status'], 'previewed', page)
        self.assertFalse(page['repository_writes'])
        before = self.index(self.root)
        refreshed = self.external_status_refresh(self.root / 'second')
        self.assertNotEqual(refreshed, before)
        result = self.store.commit('p', page['candidate_id'], 'partial hunk')
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(self.git('show', 'HEAD:file'), b'chosen\n')
        self.assertEqual(self.index(self.root), refreshed)

    def test_commit_rejects_semantic_index_drift(self):
        def ita():
            (self.root / 'ita-new').write_text('i\n')
            self.git('add', '-N', 'ita-new')
        def new_path():
            (self.root / 'extra').write_text('extra\n')
            self.git('add', 'extra')
        def unmerged():
            oid = self.git('rev-parse', 'HEAD:file').strip()
            records = b'0 ' + b'0' * 40 + b'\tfile\0' + b''.join(
                b'100644 ' + oid + b' ' + str(stage).encode() + b'\tfile\0' for stage in (1, 2, 3))
            self.git('update-index', '-z', '--index-info', input=records)
        cases = (
            ('mode', lambda: self.git('update-index', '--chmod=+x', 'file'),
                     lambda: self.git('update-index', '--chmod=-x', 'file')),
            ('assume-valid', lambda: self.git('update-index', '--assume-unchanged', 'file'),
                     lambda: self.git('update-index', '--no-assume-unchanged', 'file')),
            ('skip-worktree', lambda: self.git('update-index', '--skip-worktree', 'file'),
                     lambda: self.git('update-index', '--no-skip-worktree', 'file')),
            ('intent-to-add', ita, lambda: self.git('reset', '-q', '--', 'ita-new')),
            ('new-path', new_path, lambda: self.git('reset', '-q', '--', 'extra')),
            ('unmerged', unmerged, lambda: self.git('reset', '-q', '--', 'file')),
        )
        for name, action, reset in cases:
            with self.subTest(case=name):
                (self.root / 'file').write_text('selected\n')
                page = self.prepare(['file'])
                prepared = self.index(self.root)
                action()
                drifted = self.index(self.root)
                self.assertNotEqual(drifted, prepared)
                result = self.store.commit('p', page['candidate_id'], 'semantic drift ' + name)
                self.assertEqual(result['status'], 'rejected', result)
                self.assertEqual(result['reason'], 'index-semantic-drift', result)
                self.assertFalse(result['ref_updated'])
                self.assertEqual(self.index(self.root), drifted)
                reset()

    def test_commit_rejects_split_index_representation(self):
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        prepared = self.index(self.root)
        # Transient -c config keeps policy clean; the written 'link' extension
        # is the actual split-index representation and must fail closed.
        self.external('-c', 'core.splitIndex=true', 'update-index', '--refresh')
        drifted = self.index(self.root)
        self.assertNotEqual(drifted, prepared)
        result = self.store.commit('p', page['candidate_id'], 'split index')
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(result['reason'], 'split-or-sparse-index-unsupported', result)
        self.assertEqual(self.index(self.root), drifted)
        # The existing config-level refusal stays upstream of admission.
        self.git('config', 'core.splitIndex', 'true')
        (self.root / 'file').write_text('again\n')
        refused = self.prepare(['file'])
        self.assertEqual(refused['reason'], 'split-index-unsupported', refused)
        self.git('config', '--unset', 'core.splitIndex')

    def test_capture_rejects_configless_split_index_layout_before_any_divergence(self):
        # The candidate anchor is validated at capture: a configless split
        # representation refuses even though no index divergence ever occurs.
        original = self.index(self.root)
        self.external('-c', 'core.splitIndex=true', 'update-index', '--refresh')
        split = self.index(self.root)
        self.assertNotEqual(split, original)
        (self.root / 'file').write_text('selected\n')
        result = self.prepare(['file'])
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(result['reason'], 'split-or-sparse-index-unsupported', result)
        self.assertFalse(self.store._items)
        self.assertEqual(self.index(self.root), split)

    def test_capture_rejects_configless_sparse_index_layout_before_any_divergence(self):
        (self.root / 'top.txt').write_text('top\n')
        (self.root / 'deep').mkdir()
        (self.root / 'deep/b.txt').write_text('b\n')
        self.git('add', '-A')
        self.git('commit', '-m', 'nested')
        self.git('sparse-checkout', 'init', '--cone')
        self.git('sparse-checkout', 'set', '--cone', 'top.txt')
        self.external('-c', 'index.sparse=true', 'read-tree', 'HEAD')
        original = self.index(self.root)
        self.assertIn(b'sdir', original)
        (self.root / 'top.txt').write_text('selected\n')
        result = self.prepare(['top.txt'])
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(result['reason'], 'split-or-sparse-index-unsupported', result)
        self.assertFalse(self.store._items)
        self.assertEqual(self.index(self.root), original)

    def test_commit_admits_stat_refresh_in_index_version_four_repository(self):
        self.git('config', 'index.version', '4')
        self.git('read-tree', 'HEAD')
        self.assertEqual(int.from_bytes(self.index(self.root)[4:8], 'big'), 4)
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        prepared = self.index(self.root)
        self.assertEqual(int.from_bytes(prepared[4:8], 'big'), 4)
        self.external('status', '--porcelain=v1', '-uall')
        refreshed = self.index(self.root)
        self.assertNotEqual(refreshed, prepared)
        result = self.store.commit('p', page['candidate_id'], 'v4 refresh admitted')
        self.assertEqual(result['status'], 'committed', result)
        self.assertFalse(result['index_unchanged'])
        self.assertEqual(self.index(self.root), refreshed)

    def test_commit_admits_refresh_in_version_four_index_with_prefix_strips(self):
        self.git('config', 'index.version', '4')
        self.git('read-tree', 'HEAD')
        self.assertEqual(int.from_bytes(self.index(self.root)[4:8], 'big'), 4)
        for name in ('ab', 'abc', 'a' * 200, 'b', 'com1.txt', 'com2.txt'):
            (self.root / name).write_text(name + '\n')
        self.git('add', '-A')
        self.git('commit', '-m', 'v4 strips')
        (self.root / 'ab').write_text('selected\n')
        page = self.prepare(['ab'])
        self.assertEqual(page['status'], 'previewed', page)
        prepared = self.index(self.root)
        # Native strips cover zero strip ('ab'->'abc'), a 200-byte full
        # removal with a multi-byte varint ('a'*200 -> 'b'), shared prefixes
        # ('com1.txt'->'com2.txt') and unrelated later paths.
        refreshed = self.external_status_refresh(self.root / 'ab')
        self.assertNotEqual(refreshed, prepared)
        result = self.store.commit('p', page['candidate_id'], 'v4 strips')
        self.assertEqual(result['status'], 'committed', result)
        self.assertFalse(result['index_unchanged'])
        self.assertEqual(self.index(self.root), refreshed)
        self.assertEqual(self.git('show', 'HEAD:ab'), b'selected\n')

    def test_commit_seals_latest_eligible_index_bytes_after_multiple_refreshes(self):
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        first = self.external_status_refresh(self.root / 'file')
        second = self.external_status_refresh(self.root / 'file')
        self.assertNotEqual(first, second)
        result = self.store.commit('p', page['candidate_id'], 'latest eligible sealed')
        self.assertEqual(result['status'], 'committed', result)
        self.assertFalse(result['index_unchanged'])
        self.assertEqual(result['admitted_index_sha256'], candidate._hash(second))
        self.assertEqual(self.index(self.root), second)
        self.assertEqual(self.git('show', 'HEAD:file'), b'selected\n')

    def test_commit_sealed_baseline_rejects_injected_races(self):
        parent = self.git('rev-parse', 'HEAD').decode().strip()
        for trigger, mutate_after, expected in (
            ('mktree', False, 'rejected'),        # after locked admission
            ('commit-tree', True, 'rejected'),    # after mktree
            ('update-ref', True, 'unknown'),      # after ref CAS
        ):
            with self.subTest(trigger=trigger):
                (self.root / 'file').write_text('selected\n')
                page = self.prepare(['file'])
                baseline = self.index(self.root)
                variant = bytearray(baseline)
                variant[20] ^= 0x5A   # one volatile stat-cache byte; same identity
                variant[-20:] = hashlib.sha1(bytes(variant[:-20])).digest()
                variant = bytes(variant)
                self.assertNotEqual(variant, baseline)
                self.assertEqual(candidate._index_admission_identity(variant, 'sha1'),
                                 candidate._index_admission_identity(baseline, 'sha1'))
                real = candidate._run_git
                def racing(root, args, env, deadline, input_bytes=None,
                           trigger=trigger, mutate_after=mutate_after):
                    if args[0] == trigger and not mutate_after:
                        (self.root / '.git' / 'index').write_bytes(variant)
                    result = real(root, args, env, deadline, input_bytes)
                    if args[0] == trigger and mutate_after:
                        (self.root / '.git' / 'index').write_bytes(variant)
                    return result
                with patch.object(candidate, '_run_git', side_effect=racing):
                    result = self.store.commit('p', page['candidate_id'],
                                               'sealed race ' + trigger)
                self.assertEqual(result['status'], expected, result)
                self.assertEqual(result['reason'], 'index-changed-after-baseline', result)
                self.assertEqual(self.index(self.root), variant)
                if expected == 'rejected':
                    self.assertFalse(result['ref_updated'])
                    self.assertEqual(self.git('rev-parse', 'HEAD').decode().strip(), parent)
                else:
                    # Post-update-ref divergence stays honest unknown: the ref
                    # update is known-complete, never newly admitted.
                    self.assertIs(result['ref_updated'], True)
                    self.assertEqual(self.git('rev-parse', 'HEAD').decode().strip(),
                                     result['commit'])

    def test_fixed_diff_observation_does_not_auto_refresh_index(self):
        (self.root / 'file').write_text('selected\n')
        page = self.prepare(['file'])
        prepared = self.index(self.root)
        (self.root / 'file').write_text('selected\nworktree\n')
        rc, out, err = fixed_git.observe(self.root, ['diff', '--no-color', '--unified=3'])
        self.assertEqual(rc, 0, err)
        self.assertIn(b'diff --git', out)
        self.assertIn(b'+worktree', out)
        self.assertEqual(self.index(self.root), prepared)

    def test_head_and_branch_races_refuse_index_install(self):
        for change, reason in (("branch", "branch-changed"), ("head", "parent-changed")):
            with self.subTest(change=change):
                (self.root / 'file').write_text('selected\n')
                original = self.index(self.root)
                capture = self.store._capture
                def race(*args):
                    item = capture(*args)
                    if change == 'branch':
                        self.git('branch', 'other-branch')
                        self.git('symbolic-ref', 'HEAD', 'refs/heads/other-branch')
                    else:
                        tree = self.git('rev-parse', 'HEAD^{tree}').strip().decode()
                        parent = self.git('rev-parse', 'HEAD').strip().decode()
                        commit = self.git('commit-tree', tree, '-p', parent, input=b'external head\n').strip().decode()
                        self.git('update-ref', 'refs/heads/main', commit, parent)
                    return item
                with patch.object(self.store, '_capture', side_effect=race):
                    page = self.prepare(['file'])
                self.assertEqual(page['reason'], reason, page)
                self.assertEqual(self.index(self.root), original)
                if change == 'branch':
                    self.git('symbolic-ref', 'HEAD', 'refs/heads/main')

    def test_index_lock_collision_preserves_foreign_lock_and_index(self):
        (self.root / 'file').write_text('selected\n')
        original = self.index(self.root)
        lock = self.root / '.git/index.lock'; lock.write_bytes(b'foreign lock')
        result = self.prepare(['file'])
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(lock.read_bytes(), b'foreign lock')
        self.assertEqual(self.index(self.root), original)
        self.assertFalse(result['repository_writes'])

    def test_late_helper_policy_changes_refused_without_execution(self):
        for helper in ('hook', 'filter'):
            with self.subTest(helper=helper):
                (self.root / 'file').write_text('selected\n')
                original = self.index(self.root)
                marker = self.base / 'LATE_HELPER'
                hook = self.root / '.git/hooks/post-index-change'
                capture = self.store._capture
                def race(*args):
                    item = capture(*args)
                    if helper == 'hook':
                        hook.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n'); hook.chmod(0o755)
                    else:
                        self.git('config', 'filter.late.clean', 'touch ' + str(marker))
                    return item
                with patch.object(self.store, '_capture', side_effect=race):
                    page = self.prepare(['file'])
                self.assertEqual(page['reason'], 'active-index-hook-unsupported' if helper == 'hook'
                                 else 'preparation-filters-unsupported', page)
                self.assertEqual(self.index(self.root), original)
                self.assertFalse(marker.exists())
                if helper == 'hook':
                    hook.unlink()
                else:
                    self.git('config', '--unset', 'filter.late.clean')

    def test_intent_to_add_and_unmerged_index_not_overwritten(self):
        (self.root / 'new').write_bytes(b'intent\n'); self.git('add', '-N', 'new')
        original = self.index(self.root)
        self.assertEqual(self.prepare(['new'])['reason'], 'intent-to-add-unsupported')
        self.assertEqual(self.index(self.root), original)
        self.git('reset', '--', 'new')
        oid = self.git('rev-parse', 'HEAD:file').strip()
        records = b'0 ' + b'0' * 40 + b'\tfile\0' + b''.join(
            b'100644 ' + oid + b' ' + str(stage).encode() + b'\tfile\0' for stage in (1, 2, 3))
        self.git('update-index', '-z', '--index-info', input=records)
        original = self.index(self.root)
        self.assertEqual(self.prepare(['file'])['reason'], 'unmerged-index-unsupported')
        self.assertEqual(self.index(self.root), original)

    def test_36_file_batch_preserves_exact_candidate_index_modes_and_deletion(self):
        (self.root / 'doomed').write_bytes(b'tracked\n')
        self.git('add', 'doomed'); self.git('commit', '-m', 'deletion fixture')
        head = self.git('rev-parse', 'HEAD')
        (self.root / 'doomed').unlink()
        strange = '-literal\n\t"中文*'
        contents = {**{'new' + str(i): (str(i) + '\r\n').encode() for i in range(33)},
                    'file': b'changed\n', strange: b'\0\xffraw\r\n'}
        for path, data in contents.items():
            (self.root / path).write_bytes(data)
        (self.root / 'new0').chmod(0o755)
        (self.root / 'untouched').write_bytes(b'unselected')
        paths = [*contents, 'doomed']
        self.assertEqual(len(paths), 36)
        result = self.prepare(paths)
        self.assertEqual(result['status'], 'previewed', result)
        self.assertEqual(result['total'], 36)
        self.assertTrue(result['index_updated'])
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        entries = {}
        for record in self.git('ls-files', '--stage', '-z').rstrip(b'\0').split(b'\0'):
            meta, path = record.split(b'\t', 1)
            mode, oid, stage = meta.split()
            entries[path.decode()] = (mode, oid, stage)
        self.assertEqual(set(entries), set(contents))
        for path, data in contents.items():
            expected = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest().encode()
            self.assertEqual(entries[path], (b'100755' if path == 'new0' else b'100644', expected, b'0'))
            self.assertEqual(self.git('cat-file', 'blob', expected.decode()), data)
        self.assertEqual((self.root / 'untouched').read_bytes(), b'unselected')
        item = self.store._items[result['candidate_id']]
        events = item['preview_events']
        self.assertEqual(sum(e['operation'] == 'hash-object' for e in events), 1)
        self.assertLess(len(events), 96)
        tree, _, _ = candidate._index_tree(self.git('ls-files', '--stage', '-z'), 'sha1')
        self.assertEqual(result['tree'], tree)
        before = self.index(self.root)
        with patch.object(candidate, '_run_git', side_effect=AssertionError('cache must not query')):
            page = self.store.prepare('p', candidate_id=result['candidate_id'])
        self.assertEqual(page['tree'], tree)
        self.assertEqual(self.index(self.root), before)

    def test_query_count_stays_constant_through_36_paths(self):
        self._assert_query_count_stays_constant((1, 36))

    @unittest.skipUnless(os.environ.get('BRIDGE_MAINTAINER_SUITE') == '1',
                         'maintainer lane: full 2,048-path preparation stress '
                         '(BRIDGE_MAINTAINER_SUITE=1)')
    def test_query_count_stays_constant_through_2048_path_complexity_ceiling(self):
        self._assert_query_count_stays_constant((1, 36, 256, preparation.MAX_SELECTED_PATHS))

    def _assert_query_count_stays_constant(self, path_counts):
        counts = []
        for count in path_counts:
            with self.subTest(count=count):
                paths = [f'p{i:04d}' for i in range(count)]
                for path in paths:
                    (self.root / path).write_bytes(path.encode())
                result = self.prepare(paths, limit=100)
                self.assertEqual(result['status'], 'previewed', result)
                self.assertEqual(result['total'], count)
                item = self.store._items[result['candidate_id']]
                events = item['preview_events']
                self.assertEqual(sum(e['operation'] == 'hash-object' for e in events), 1)
                self.assertEqual(len(item['files']), count)
                self.assertEqual({f['path'] for f in item['files']}, set(paths))
                counts.append(len(events))
        self.assertEqual(counts, [counts[0]] * len(counts))
        self.assertLess(counts[0], 96)

    def test_empty_and_over_limit_selection_rejected(self):
        original = self.index(self.root)
        self.assertEqual(self.prepare(['file'])['reason'], 'empty-candidate')
        with patch.object(candidate, '_run_git', side_effect=AssertionError('must refuse before Git')):
            self.assertEqual(self.prepare([])['reason'], 'nonempty-literal-selection-required')
            self.assertEqual(self.prepare(['p' + str(i) for i in range(preparation.MAX_SELECTED_PATHS + 1)])['reason'],
                             'selection-path-count-limit')
        (self.root / 'large').write_bytes(b'x' * (candidate.MAX_BYTES + 1))
        self.assertEqual(self.prepare(['large'])['status'], 'rejected')
        self.assertEqual(self.index(self.root), original)

    def test_total_content_and_path_byte_bounds(self):
        exact_paths = [str(i) + 'x' * 4095 for i in range(4)]
        self.assertEqual(preparation.selection_paths(exact_paths), exact_paths)
        with self.assertRaisesRegex(candidate.Refused, '^selection-path-byte-limit$'):
            preparation.selection_paths([*exact_paths, 'y'])
        unicode_paths = [str(i) + 'é' * 2000 for i in range(4)]
        self.assertEqual(preparation.selection_paths(unicode_paths), unicode_paths)
        with self.assertRaisesRegex(candidate.Refused, '^selection-path-byte-limit$'):
            preparation.selection_paths([*unicode_paths, 'é' * 200])
        (self.root / 'a').write_bytes(b'\0' * (candidate.MAX_BYTES // 2))
        (self.root / 'b').write_bytes(b'\0' * (candidate.MAX_BYTES // 2 + 1))
        original = self.index(self.root)
        result = self.prepare(['a', 'b'])
        self.assertEqual(result['reason'], 'selection-total-byte-limit', result)
        self.assertFalse(result['objects_may_remain'])
        self.assertEqual(self.index(self.root), original)
        (self.root / 'b').write_bytes(b'\0' * (candidate.MAX_BYTES // 2))
        self.assertEqual(self.prepare(['a', 'b'])['status'], 'previewed')

    def test_blob_batch_uses_private_captured_bytes_and_fixed_argv(self):
        content = b'captured\r\n\0\xff'
        (self.root / 'file').write_bytes(content)
        original = self.index(self.root)
        run, temporary = candidate._run_git, []
        def inspect(root, args, env, deadline, input_bytes=None):
            if args[0] == 'hash-object':
                self.assertEqual(args, ['hash-object', '-w', '--no-filters', '--stdin-paths'])
                names = input_bytes.decode('ascii').splitlines()
                self.assertEqual(len(names), 1)
                for name in names:
                    path = Path(name)
                    temporary.append(path)
                    self.assertTrue(path.is_absolute())
                    self.assertEqual(path.parent.parent, Path('/tmp'))
                    self.assertTrue(path.name.isdecimal())
                    self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(path.read_bytes(), content)
                # Git must hash the capture, not this concurrent worktree edit.
                (self.root / 'file').write_bytes(b'changed after capture')
            return run(root, args, env, deadline, input_bytes)
        with patch.object(candidate, '_run_git', side_effect=inspect):
            result = self.prepare(['file'])
        self.assertEqual(result['reason'], 'selected-file-changed', result)
        self.assertTrue(result['objects_may_remain'])
        self.assertEqual(self.index(self.root), original)
        oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        self.assertEqual(self.git('cat-file', 'blob', oid), content)
        self.assertTrue(temporary)
        self.assertTrue(all(not path.parent.exists() for path in temporary))

    def test_batch_failure_or_malformed_oids_never_updates_real_index(self):
        (self.root / 'file').write_bytes(b'chosen')
        original, run = self.index(self.root), candidate._run_git
        for failure in ('timeout', 'wrong-oid', 'extra-output', 'truncated-output'):
            with self.subTest(failure=failure):
                temporary = []
                def corrupt(root, args, env, deadline, input_bytes=None):
                    if args[0] != 'hash-object':
                        return run(root, args, env, deadline, input_bytes)
                    temporary.extend(Path(p).parent for p in input_bytes.decode().splitlines())
                    rc, out, err = run(root, args, env, deadline, input_bytes)
                    if failure == 'timeout':
                        raise candidate.GitFailure('timeout')
                    out = (b'0' * 40 + b'\n' if failure == 'wrong-oid' else
                           out + out if failure == 'extra-output' else out[:-1])
                    return rc, out, err
                with patch.object(candidate, '_run_git', side_effect=corrupt):
                    result = self.prepare(['file'])
                self.assertEqual(result['status'], 'rejected', result)
                self.assertEqual(result['reason'], 'git-timeout' if failure == 'timeout' else 'selected-blob-mismatch')
                self.assertTrue(result['objects_may_remain'])
                self.assertFalse(result['index_updated'])
                self.assertEqual(self.index(self.root), original)
                self.assertFalse(self.store._items)
                self.assertTrue(all(not p.exists() for p in temporary))

    def test_batch_no_filters_even_if_conversion_policy_changes_after_capture(self):
        content = b'raw\r\n'
        (self.root / 'file').write_bytes(content)
        original, run = self.index(self.root), candidate._run_git
        marker = self.base / 'FILTER_RAN'
        def race(root, args, env, deadline, input_bytes=None):
            if args[0] == 'hash-object':
                self.git('config', 'filter.unsafe.clean', 'touch ' + str(marker))
                (self.root / '.gitattributes').write_text('file filter=unsafe text eol=lf\n')
            return run(root, args, env, deadline, input_bytes)
        with patch.object(candidate, '_run_git', side_effect=race):
            result = self.prepare(['file'])
        self.assertEqual(result['status'], 'rejected', result)
        self.assertTrue(result['objects_may_remain'])
        self.assertFalse(result['index_updated'])
        self.assertFalse(marker.exists())
        self.assertEqual(self.index(self.root), original)
        oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        self.assertEqual(self.git('cat-file', 'blob', oid), content)

    def test_distinct_blob_output_must_validate_fully_before_any_index_update(self):
        contents = {'file': b'alpha', 'second': b'beta', 'third': b'gamma'}
        for path, content in contents.items():
            (self.root / path).write_bytes(content)
        original, run = self.index(self.root), candidate._run_git
        for failure in ('reordered', 'missing', 'extra'):
            with self.subTest(failure=failure):
                operations, batches = [], []
                def corrupt(root, args, env, deadline, input_bytes=None):
                    operation = args[2] if args[:2] == ['-c', 'core.hooksPath=/dev/null'] else args[0]
                    operations.append(operation)
                    rc, out, err = run(root, args, env, deadline, input_bytes)
                    if operation == 'hash-object':
                        oids = out.splitlines(keepends=True)
                        self.assertEqual(len(oids), 3)
                        self.assertEqual(len(set(oids)), 3)
                        batches.append(oids)
                        out = b''.join(oids[::-1] if failure == 'reordered' else
                                       [oids[0], oids[2]] if failure == 'missing' else
                                       [*oids, oids[0]])
                    return rc, out, err
                with patch.object(candidate, '_run_git', side_effect=corrupt), patch.object(
                        preparation, 'install_index') as install, patch.object(
                        self.store, '_capture') as capture:
                    result = self.prepare(list(contents))
                self.assertEqual(result['status'], 'rejected', result)
                self.assertEqual(result['reason'], 'selected-blob-mismatch')
                self.assertTrue(result['objects_may_remain'])
                self.assertTrue(result['repository_writes'])
                self.assertFalse(result['index_updated'])
                self.assertFalse(result['ref_updated'])
                self.assertNotIn('candidate_id', result)
                self.assertEqual(len(batches), 1)
                self.assertNotIn('update-index', operations)
                install.assert_not_called()
                capture.assert_not_called()
                self.assertEqual(self.index(self.root), original)
                self.assertFalse(self.store._items)

    def test_duplicate_content_oids_keep_one_result_per_selected_blob(self):
        contents = {'file': b'shared\0bytes', 'copy': b'shared\0bytes', 'other': b'distinct'}
        for path, content in contents.items():
            (self.root / path).write_bytes(content)
        run, batches, operations = candidate._run_git, [], []
        expected = [hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest().encode()
                    for data in contents.values()]
        def inspect(root, args, env, deadline, input_bytes=None):
            operation = args[2] if args[:2] == ['-c', 'core.hooksPath=/dev/null'] else args[0]
            operations.append(operation)
            if operation == 'update-index':
                self.assertEqual(batches, [expected])
            rc, out, err = run(root, args, env, deadline, input_bytes)
            if operation == 'hash-object':
                self.assertEqual(len(input_bytes.splitlines()), 3)
                batches.append(out.splitlines())
            return rc, out, err
        with patch.object(candidate, '_run_git', side_effect=inspect):
            result = self.prepare(list(contents))
        self.assertEqual(result['status'], 'previewed', result)
        self.assertEqual(batches, [expected])
        self.assertEqual(expected[0], expected[1])
        self.assertNotEqual(expected[1], expected[2])
        self.assertEqual(operations.count('hash-object'), 1)
        self.assertEqual(operations.count('update-index'), 1)
        self.assertTrue(result['objects_may_remain'])
        self.assertTrue(result['index_updated'])
        self.assertIn(result['candidate_id'], self.store._items)
        entries = {f['path']: f['object'] for f in result['files']}
        self.assertEqual(entries, {path: oid.decode() for path, oid in zip(contents, expected)})
        for path, content in contents.items():
            self.assertEqual(self.git('show', ':' + path), content)

    def test_batch_deadline_and_temporary_storage_failure_precede_object_mutation(self):
        (self.root / 'file').write_bytes(b'captured')
        original = self.index(self.root)
        batch = preparation._write_selected_blobs
        def expired(binding, *args):
            binding.deadline = time.monotonic() - 1
            return batch(binding, *args)
        with patch.object(preparation, '_write_selected_blobs', side_effect=expired):
            result = self.prepare(['file'])
        self.assertEqual(result['reason'], 'operation-deadline', result)
        self.assertFalse(result['objects_may_remain'])
        self.assertEqual(self.index(self.root), original)
        def unavailable(binding, *args):
            with patch.object(preparation.tempfile, 'TemporaryDirectory', side_effect=OSError('temporary storage full')):
                return batch(binding, *args)
        with patch.object(preparation, '_write_selected_blobs', side_effect=unavailable):
            result = self.prepare(['file'])
        self.assertEqual(result['status'], 'rejected', result)
        self.assertFalse(result['objects_may_remain'])
        self.assertFalse(result['index_updated'])
        self.assertEqual(self.index(self.root), original)

    def test_wide_mixed_selection_rejects_before_batch_and_preserves_partial_staging(self):
        (self.root / 'file').write_bytes(b'staged')
        self.git('add', 'file')
        (self.root / 'file').write_bytes(b'partly unstaged')
        paths = [f'p{i}' for i in range(35)] + ['file']
        for path in paths[:-1]:
            (self.root / path).write_bytes(path.encode())
        original = self.index(self.root)
        with patch.object(preparation, '_write_selected_blobs', side_effect=AssertionError('capture must finish first')):
            result = self.prepare(paths)
        self.assertEqual(result['reason'], 'selected-mixed-staged-unstaged', result)
        self.assertFalse(result['objects_may_remain'])
        self.assertEqual(self.index(self.root), original)

    def test_deletion_only_selection_writes_no_blobs(self):
        (self.root / 'file').unlink()
        result = self.prepare(['file'])
        self.assertEqual(result['status'], 'previewed', result)
        self.assertFalse(result['objects_may_remain'])
        events = self.store._items[result['candidate_id']]['preview_events']
        self.assertFalse(any(e['operation'] == 'hash-object' for e in events))

    def test_sha256_batch_prepares_36_files_with_exact_oids(self):
        root = self.base / 'sha256'; root.mkdir()
        self.git('init', '--object-format=sha256', '-b', 'main', root=root)
        self.git('config', 'user.name', 'Fixture', root=root)
        self.git('config', 'user.email', 'fixture@example.invalid', root=root)
        (root / 'base').write_bytes(b'base')
        self.git('add', 'base', root=root); self.git('commit', '-m', 'fixture', root=root)
        _, identity = canonical_git_worktree(root)
        project = WorkspaceContext('p', root, identity, str(root))
        store = candidate.CandidateStore(lambda *_: EvidenceTarget(project, project, None))
        paths = [f'p{i}' for i in range(36)]
        for path in paths:
            (root / path).write_bytes(path.encode() + b'\0\xff')
        result = store.prepare('p', paths=paths)
        self.assertEqual(result['status'], 'previewed', result)
        self.assertEqual(result['total'], 36)
        for entry in result['files']:
            content = entry['path'].encode() + b'\0\xff'
            expected = hashlib.sha256(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            self.assertEqual(entry['object'], expected)
            self.assertEqual(self.git('cat-file', 'blob', expected, root=root), content)
        self.assertEqual(sum(e['operation'] == 'hash-object' for e in
                             store._items[result['candidate_id']]['preview_events']), 1)


class CommitPrepareObservationPurityTests(unittest.IsolatedAsyncioTestCase):
    """Public current diff never mutates the exact index a selected prepare froze."""

    git = fixtures.CommitCandidateTests.git
    resolve = fixtures.CommitCandidateTests.resolve
    index = fixtures.CommitCandidateTests.index

    def setUp(self):
        fixtures.CommitCandidateTests.setUp(self)
        registry = WorkspaceRegistry(self.project.root, json.dumps({'p': str(self.project.root)}),
            store=WorkspaceRegistryStore(self.base / 'registry.json'))
        for name, value in (('_WORKSPACE_REGISTRY', registry), ('_WORK_REGISTRY', {}), ('_RESULT_INBOX', {})):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        server._WORK_REGISTRY['work'] = {
            'project_ref': 'p', 'workspace_root': str(self.project.root),
            'execution_identity': 'bound',
            'evidence_checkout': EvidenceCheckout.capture(registry.resolve('p'), str(self.linked)),
        }

    async def test_root_prepare_then_public_current_diff_never_writes_index(self):
        (self.root / 'file').write_text('selected\n')
        page = await server.commit_prepare('p', ['file'])
        self.assertEqual(page['status'], 'previewed', page)
        prepared = self.index(self.root)
        os.utime(self.root / 'file', None)
        for work_ref, root in ((None, self.root), ('work', self.linked)):
            with self.subTest(work_ref=work_ref):
                before = self.index(root)
                for view in ('summary', 'patch'):
                    for staged in (False, True):
                        result = await server.diff('p', view=view, staged=staged, work_ref=work_ref)
                        self.assertTrue(result['ok'], result)
                        self.assertEqual(self.index(root), before, (work_ref, view, staged))
        result = await server.commit('p', page['candidate_id'], 'diff stayed pure')
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(self.git('show', 'HEAD:file'), b'selected\n')

    async def test_linked_prepare_then_public_current_diff_never_writes_index(self):
        (self.linked / 'file').write_text('linked selected\n')
        page = await server.commit_prepare('p', ['file'], work_ref='work')
        self.assertEqual(page['status'], 'previewed', page)
        self.assertEqual(page['target_kind'], 'work_checkout')
        prepared = self.index(self.linked)
        os.utime(self.linked / 'file', None)
        for view in ('summary', 'patch'):
            for staged in (False, True):
                result = await server.diff('p', view=view, staged=staged, work_ref='work')
                self.assertTrue(result['ok'], result)
                self.assertEqual(self.index(self.linked), prepared, (view, staged))
        result = await server.commit('p', page['candidate_id'], 'linked pure')
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(self.git('show', 'HEAD:file', root=self.linked), b'linked selected\n')


class CommitIndexAdmissionTests(unittest.TestCase):
    """The admission identity normalizes only the volatile stat cache."""

    A = bytes(range(20))
    B = bytes(range(20, 40))

    @staticmethod
    def entry(name, oid, mode=0o100644, stage=0, flags=0, stat=b'\1' * 40, ext_flags=0):
        # 40-byte on-disk stat block: ctime/mtime/dev/ino, mode at [24:28),
        # uid/gid/size; then OID, 16-bit flags, [16-bit extended flags when
        # the 0x4000 bit is set], name, NUL padding to 8.
        stat = stat[:24] + mode.to_bytes(4, 'big') + stat[28:]
        name_bytes = name.encode()
        main = (flags & ~0x3000) | (stage << 12) | min(len(name_bytes), 0xFFF)
        extended = b'' if not flags & 0x4000 else ext_flags.to_bytes(2, 'big')
        fixed = 42 + len(oid) + len(extended)
        body = stat + oid + main.to_bytes(2, 'big') + extended + name_bytes
        pad = ((fixed + len(name_bytes)) // 8 + 1) * 8 - (fixed + len(name_bytes))
        return body + b'\0' * pad

    @staticmethod
    def raw_index(*entries, version=2, extensions=b'', algorithm='sha1'):
        header = b'DIRC' + version.to_bytes(4, 'big') + len(entries).to_bytes(4, 'big')
        body = header + b''.join(entries) + extensions
        return body + hashlib.new(algorithm, body).digest()

    def test_volatile_stat_bytes_alone_do_not_change_identity(self):
        left = self.raw_index(self.entry('file', self.A))
        right = self.raw_index(self.entry('file', self.A, stat=bytes(range(40))))
        self.assertNotEqual(left, right)
        self.assertEqual(candidate._index_admission_identity(left, 'sha1'),
                         candidate._index_admission_identity(right, 'sha1'))

    def test_semantic_bytes_change_identity(self):
        base = candidate._index_admission_identity(self.raw_index(self.entry('file', self.A)), 'sha1')
        variants = (
            ('mode', self.raw_index(self.entry('file', self.A, mode=0o100755))),
            ('oid', self.raw_index(self.entry('file', self.B))),
            ('assume-valid', self.raw_index(self.entry('file', self.A, flags=0x8000))),
            ('path', self.raw_index(self.entry('other', self.A))),
            ('stage', self.raw_index(self.entry('file', self.A, stage=1))),
        )
        for name, raw in variants:
            with self.subTest(case=name):
                self.assertNotEqual(candidate._index_admission_identity(raw, 'sha1'), base)

    def test_extended_flag_bytes_change_identity_in_version_three(self):
        plain = self.entry('file', self.A, flags=0x4000)
        skip = self.entry('file', self.A, flags=0x4000, ext_flags=0x4000)
        intent = self.entry('file', self.A, flags=0x4000, ext_flags=0x2000)
        identity = lambda raw: candidate._index_admission_identity(raw, 'sha1')
        base = identity(self.raw_index(plain, version=3))
        self.assertNotEqual(base, identity(self.raw_index(skip, version=3)))
        self.assertNotEqual(base, identity(self.raw_index(intent, version=3)))
        # Stat normalization still applies to extended entries.
        refreshed = self.entry('file', self.A, flags=0x4000, ext_flags=0x4000,
                               stat=bytes(range(40)))
        self.assertEqual(identity(self.raw_index(skip, version=3)),
                         identity(self.raw_index(refreshed, version=3)))

    def test_checksum_and_unsupported_layouts_fail_closed(self):
        def identity(raw):
            return candidate._index_admission_identity(raw, 'sha1')
        corrupted = bytearray(self.raw_index(self.entry('file', self.A)))
        corrupted[50] ^= 0xFF
        with self.assertRaises(candidate.Refused) as ctx:
            identity(bytes(corrupted))
        self.assertEqual(str(ctx.exception), 'index-checksum-invalid')
        def with_extension(signature):
            ext = signature + (0).to_bytes(4, 'big')
            body = bytearray(self.raw_index(self.entry('file', self.A)))[:-20] + ext
            return bytes(body) + hashlib.sha1(bytes(body)).digest()
        for signature in (b'link', b'sdir'):
            with self.subTest(extension=signature):
                with self.assertRaises(candidate.Refused) as ctx:
                    identity(with_extension(signature))
                self.assertEqual(str(ctx.exception), 'split-or-sparse-index-unsupported')
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_index(self.entry('deep', self.A, mode=0o040000)))
        self.assertEqual(str(ctx.exception), 'sparse-index-unsupported')
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_index(self.entry('file', self.A), version=5))
        self.assertEqual(str(ctx.exception), 'index-version-admission-unsupported')

    def test_sha256_identity_normalizes_volatile_fields(self):
        oid = bytes(range(32))
        left = self.raw_index(self.entry('file', oid), algorithm='sha256')
        right = self.raw_index(self.entry('file', oid, stat=bytes(range(40))), algorithm='sha256')
        changed = self.raw_index(self.entry('file', bytes(range(32, 64))), algorithm='sha256')
        identity = lambda raw: candidate._index_admission_identity(raw, 'sha256')
        self.assertEqual(identity(left), identity(right))
        self.assertNotEqual(identity(left), identity(changed))

    @staticmethod
    def v4_varint(value):
        out = bytearray([value & 0x7F])
        value >>= 7
        while value:
            value -= 1
            out.insert(0, 0x80 | (value & 0x7F))
            value >>= 7
        return bytes(out)

    def build_v4_entry(self, previous_name, name, oid, strip_bytes=None, varint_bytes=None,
                       mode=0o100644, name_len_field=None):
        """Native-convention v4 entry: the varint counts bytes removed from the
        END of the previous pathname and the suffix is only the non-common
        remainder, NUL-terminated, without padding. The 12-bit name length
        field carries the FULL name length (saturating at 0xFFF) unless
        overridden for malformed-layout tests."""
        if varint_bytes is None:
            if strip_bytes is None:
                common = 0
                while (common < min(len(previous_name), len(name))
                       and previous_name[common:common + 1] == name[common:common + 1]):
                    common += 1
                strip_bytes = len(previous_name) - common
            varint_bytes = self.v4_varint(strip_bytes)
            suffix = name.encode()[len(previous_name) - strip_bytes:]
        else:
            suffix = name.encode()
        stat = b'\1' * 24 + mode.to_bytes(4, 'big') + b'\2' * 12
        field = min(len(name), 0xFFF) if name_len_field is None else name_len_field
        flags = field.to_bytes(2, 'big')
        return stat + oid + flags + varint_bytes + suffix + b'\0'

    @staticmethod
    def raw_v4_index(*entries):
        header = b'DIRC' + (4).to_bytes(4, 'big') + len(entries).to_bytes(4, 'big')
        body = header + b''.join(entries)
        return body + hashlib.sha1(body).digest()

    def test_v4_strip_reconstruction_semantics(self):
        identity = lambda raw: candidate._index_admission_identity(raw, 'sha1')
        # Zero strip: the previous name is a strict prefix of the new name.
        zero = self.raw_v4_index(self.build_v4_entry('', 'ab', self.A),
                                 self.build_v4_entry('ab', 'abc', self.B))
        self.assertIsNotNone(identity(zero))
        # Full previous-name removal: an unrelated later path strips len(prev).
        full = self.raw_v4_index(self.build_v4_entry('', 'abc', self.A),
                                 self.build_v4_entry('abc', 'zz', self.B))
        self.assertIsNotNone(identity(full))
        # Shared prefix: single-byte strip keeps only the common part.
        shared = self.raw_v4_index(self.build_v4_entry('', 'file', self.A),
                                   self.build_v4_entry('file', 'foobar', self.B))
        self.assertIsNotNone(identity(shared))
        # Multi-byte varint: a 200-byte previous name fully stripped encodes
        # as two varint bytes (0x80 0x48 for 200).
        self.assertEqual(self.v4_varint(200), b'\x80\x48')
        multi = self.raw_v4_index(self.build_v4_entry('', 'a' * 200, self.A),
                                  self.build_v4_entry('a' * 200, 'b', self.B))
        self.assertIn(b'\x80\x48b\x00', multi)
        self.assertIsNotNone(identity(multi))
        # strip > len(previous) fails closed on the decoded value...
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_v4_index(self.build_v4_entry('', 'ab', self.A),
                                       self.build_v4_entry('ab', 'x', self.B, strip_bytes=3)))
        self.assertEqual(str(ctx.exception), 'index-path-strip-invalid')
        # ... and a malformed multi-byte continuation run rejects while
        # decoding, as soon as the partial value exceeds the previous length.
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_v4_index(
                self.build_v4_entry('', 'ab', self.A),
                self.build_v4_entry('ab', 'x', self.B, varint_bytes=b'\xff\xff\xff\x7f')))
        self.assertEqual(str(ctx.exception), 'index-path-strip-invalid')

    def test_v4_reconstruction_matches_git_native_reader(self):
        names = ['ab', 'abc', 'file', 'foobar', 'zz']
        oids = [bytes([i]) * 20 for i in range(1, len(names) + 1)]
        entries, previous = [], ''
        for name, oid in zip(names, oids):
            entries.append(self.build_v4_entry(previous, name, oid))
            previous = name
        crafted = self.raw_v4_index(*entries)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run([candidate.GIT, 'init', '-q', '-b', 'main'], cwd=root,
                           check=True, capture_output=True)
            (root / '.git' / 'index').write_bytes(crafted)
            listed = subprocess.run([candidate.GIT, 'ls-files'], cwd=root,
                                    check=True, capture_output=True).stdout.decode().split()
        self.assertEqual(listed, names)
        self.assertIsNotNone(candidate._index_admission_identity(crafted, 'sha1'))

    def test_v4_declared_name_length_matches_reconstruction(self):
        identity = lambda raw: candidate._index_admission_identity(raw, 'sha1')
        # Correct full-length declaration (existing valid cases) still parse.
        self.assertIsNotNone(identity(self.raw_v4_index(
            self.build_v4_entry('', 'ab', self.A))))
        # Wrong declared length for a short name rejects.
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_v4_index(
                self.build_v4_entry('', 'ab', self.A, name_len_field=3)))
        self.assertEqual(str(ctx.exception), 'index-format-invalid')
        # Saturated 0xFFF declaration is valid for a >=4095-byte name...
        saturated = self.raw_v4_index(self.build_v4_entry(
            '', 'x' * 4095, self.A, name_len_field=0xFFF))
        self.assertIsNotNone(identity(saturated))
        # ... but a short name claiming saturation rejects.
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_v4_index(
                self.build_v4_entry('', 'ab', self.A, name_len_field=0xFFF)))
        self.assertEqual(str(ctx.exception), 'index-format-invalid')
        # Non-ASCII names count UTF-8 bytes, not characters.
        unicode_name = '\u00e9' * 5            # five characters, ten UTF-8 bytes
        correct_bytes = self.raw_v4_index(self.build_v4_entry(
            '', unicode_name, self.A, name_len_field=10))
        self.assertIsNotNone(identity(correct_bytes))
        with self.assertRaises(candidate.Refused) as ctx:
            identity(self.raw_v4_index(
                self.build_v4_entry('', unicode_name, self.A, name_len_field=5)))
        self.assertEqual(str(ctx.exception), 'index-format-invalid')
        # Zero strip / full removal / multi-byte strip keep passing with the
        # reconstructed-length check in place.
        self.assertIsNotNone(identity(self.raw_v4_index(
            self.build_v4_entry('', 'ab', self.A),
            self.build_v4_entry('ab', 'abc', self.B))))
        self.assertIsNotNone(identity(self.raw_v4_index(
            self.build_v4_entry('', 'abc', self.A),
            self.build_v4_entry('abc', 'zz', self.B))))
        self.assertIsNotNone(identity(self.raw_v4_index(
            self.build_v4_entry('', 'a' * 200, self.A),
            self.build_v4_entry('a' * 200, 'b', self.B))))

    def test_extension_classification_matches_native_git(self):
        base = self.raw_index(self.entry('file', self.A))
        def with_ext(signature, payload=b''):
            body = bytearray(base[:-20]) + signature + len(payload).to_bytes(4, 'big') + payload
            return bytes(body) + hashlib.sha1(body).digest()
        identity = lambda raw: candidate._index_admission_identity(raw, 'sha1')
        # Native reader oracle (git 2.34): an unknown uppercase-first
        # extension is optional and ignored; lowercase and non-alphabetic
        # first bytes make it mandatory and the index unreadable.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run([candidate.GIT, 'init', '-q', '-b', 'main'], cwd=root,
                           check=True, capture_output=True)
            index = root / '.git' / 'index'
            index.write_bytes(with_ext(b'ABCD', b'payload'))
            upper = subprocess.run([candidate.GIT, 'ls-files'], cwd=root, capture_output=True)
            index.write_bytes(with_ext(b'abcd', b'payload'))
            lower = subprocess.run([candidate.GIT, 'ls-files'], cwd=root, capture_output=True)
            index.write_bytes(with_ext(b'\x01BCD'))
            nonalpha = subprocess.run([candidate.GIT, 'ls-files'], cwd=root, capture_output=True)
        self.assertEqual(upper.returncode, 0, upper.stderr)
        self.assertNotEqual(lower.returncode, 0)
        self.assertIn(b'which we do not understand', lower.stderr)
        self.assertNotEqual(nonalpha.returncode, 0)
        # Parser policy matches native Git: optional uppercase payloads are
        # retained byte-exact and accepted...
        self.assertIsNotNone(identity(with_ext(b'ABCD', b'payload')))
        self.assertNotEqual(identity(with_ext(b'ABCD', b'payload')), identity(base))
        self.assertNotEqual(identity(with_ext(b'ABCD')), identity(with_ext(b'ABCD', b'payload')))
        # ... mandatory lowercase/non-alphabetic signatures reject.
        for signature in (b'abcd', b'\x01BCD'):
            with self.subTest(signature=signature):
                with self.assertRaises(candidate.Refused) as ctx:
                    identity(with_ext(signature))
                self.assertEqual(str(ctx.exception), 'index-extension-unsupported')

    def test_admission_tracks_refreshes_then_seals_latest_bytes(self):
        prepared = self.raw_index(self.entry('file', self.A))
        prepared_identity = candidate._index_admission_identity(prepared, 'sha1')
        refresh_one = self.raw_index(self.entry('file', self.A, stat=bytes(range(40))))
        refresh_two = self.raw_index(self.entry('file', self.A, stat=bytes(range(40, 80))))
        drifted = self.raw_index(self.entry('file', self.B))
        admission = candidate._CommitIndexAdmission(prepared, prepared_identity, 'sha1')
        admission.observe(prepared)
        self.assertIsNone(admission.admitted_sha256)
        # Pre-lock eligibility tracking follows the latest eligible live bytes;
        # several successive harmless refreshes do not reject.
        admission.observe(refresh_one)
        self.assertEqual(admission.admitted_sha256, candidate._hash(refresh_one))
        admission.observe(refresh_two)
        self.assertEqual(admission.admitted_sha256, candidate._hash(refresh_two))
        # Final locked admission seals the latest eligible bytes; from sealing
        # on, any byte divergence rejects even when it would be eligible.
        admission.observe(refresh_two, seal=True)
        self.assertTrue(admission.sealed)
        admission.observe(refresh_two)
        with self.assertRaises(candidate.Refused) as ctx:
            admission.observe(drifted)
        self.assertEqual(str(ctx.exception), 'index-changed-after-baseline')
        with self.assertRaises(candidate.Refused) as ctx:
            admission.observe(refresh_one)
        self.assertEqual(str(ctx.exception), 'index-changed-after-baseline')
        # Without sealing, an ineligible divergence still rejects as drift.
        with self.assertRaises(candidate.Refused) as ctx:
            candidate._CommitIndexAdmission(
                prepared, prepared_identity, 'sha1').observe(drifted)
        self.assertEqual(str(ctx.exception), 'index-semantic-drift')

    def test_sealed_admission_validates_layout_even_when_bytes_never_diverge(self):
        prepared = self.raw_index(self.entry('file', self.A))
        prepared_identity = candidate._index_admission_identity(prepared, 'sha1')
        admission = candidate._CommitIndexAdmission(prepared, prepared_identity, 'sha1')
        # The final locked admission re-walks the live bytes; byte-equality
        # with the capture-validated anchor is still validated at sealing.
        admission.observe(prepared, seal=True)
        self.assertTrue(admission.sealed)
        # A divergent split-index layout refuses through the seal path too.
        link = bytearray(self.raw_index(self.entry('file', self.A)))
        body = bytes(link[:-20]) + b'link' + (0).to_bytes(4, 'big')
        link_index = body + hashlib.sha1(body).digest()
        with self.assertRaises(candidate.Refused) as ctx:
            candidate._CommitIndexAdmission(
                prepared, prepared_identity, 'sha1').observe(link_index, seal=True)
        self.assertEqual(str(ctx.exception), 'split-or-sparse-index-unsupported')
