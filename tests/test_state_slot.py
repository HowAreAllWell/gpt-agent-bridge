"""Opt-in current-state slot: mechanical publication guardrail."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault(
    "BRIDGE_PATH_TOKEN",
    "test-token-abcdefghijklmnopqrstuvwxyz-012345",
)

import unittest

import project_continuity as continuity
import server
from tests import test_project_continuity as continuity_tests


def _rev(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _slot(limit: int, body: str, *, newline: str = "\n", before: str = "", after: str = "") -> str:
    return (
        f"{before}"
        f"<!-- bridge-state-slot start limit={limit} -->{newline}"
        f"{body}"
        f"<!-- bridge-state-slot end -->{newline}"
        f"{after}"
    )


class StateSlotTests(unittest.IsolatedAsyncioTestCase):
    _write_manifest = continuity_tests.ProjectContinuityTests._write_manifest

    def setUp(self) -> None:
        continuity_tests.ProjectContinuityTests.setUp(self)
        self._write_manifest()
        self.state = self.root / "STATE.md"

    def _temps(self) -> list[Path]:
        return list(self.root.glob(".principal-checkpoint-*.tmp"))

    async def _publish(self, content: str | None, expected: str, edits=None):
        if edits is not None:
            return await server.checkpoint("project", None, expected, edits=edits)
        return await server.checkpoint("project", content, expected)

    async def test_legacy_no_slot_publication_is_byte_identical(self) -> None:
        content = "甲\r\nkeep <!-- bridge-state-slot start limit=8192 --> inline\r\n尾😀\r\n"
        created = await self._publish(content, continuity.CHECKPOINT_MISSING_REVISION)
        self.assertTrue(created["ok"], created)
        self.assertEqual(self.state.read_bytes(), content.encode("utf-8"))
        self.assertEqual(continuity.classify_state_slot(self.state.read_bytes())["kind"], "absent")
        indented = " <!-- bridge-state-slot start limit=8192 -->\r\nno slot\r\n"
        replaced = await self._publish(indented, created["revision"])
        self.assertTrue(replaced["ok"], replaced)
        self.assertEqual(self.state.read_bytes(), indented.encode("utf-8"))
        self.assertEqual(self._temps(), [])

    async def test_missing_file_adopts_one_valid_slot_and_exact_boundary(self) -> None:
        body = ("a" * 8191) + "\n"
        content = _slot(8192, body)
        created = await self._publish(content, "missing")
        self.assertTrue(created["ok"], created)
        raw = self.state.read_bytes()
        self.assertEqual(raw, content.encode("utf-8"))
        classified = continuity.classify_state_slot(raw)
        self.assertEqual((classified["kind"], classified["limit"], classified["body_bytes"]),
                         ("valid", 8192, 8192))
        over = _slot(8192, ("a" * 8192) + "\n")
        refused = await self._publish(over, created["revision"])
        self.assertEqual(refused["error_type"], "CheckpointSlotRejected")
        self.assertEqual(refused["slot_reason"], "slot_body_exceeds_limit")
        self.assertEqual(refused["slot_limit"], 8192)
        self.assertEqual(refused["slot_body_bytes"], 8193)
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertEqual(self._temps(), [])

    async def test_creation_over_limit_and_malformed_markers_write_nothing(self) -> None:
        over = await self._publish(_slot(1024, ("b" * 1024) + "\n"), "missing")
        self.assertEqual(over["slot_reason"], "slot_body_exceeds_limit")
        self.assertFalse(self.state.exists())
        for candidate in (
            "<!-- bridge-state-slot start limit=10 -->\nbody\n<!-- bridge-state-slot end -->\n",
            "<!-- bridge-state-slot start limit=08192 -->\nbody\n<!-- bridge-state-slot end -->\n",
            "<!-- bridge-state-slot start limit=65537 -->\nx\n<!-- bridge-state-slot end -->\n",
            "<!-- bridge-state-slot start limit=8192 -->\nno end\n",
            _slot(8192, "one\n") + _slot(8192, "two\n"),
            "```\n" + _slot(8192, "real\n") + "```\n" + _slot(8192, "fenced\n"),
        ):
            with self.subTest(candidate=candidate[:48]):
                result = await self._publish(candidate, "missing")
                self.assertEqual(result["error_type"], "CheckpointSlotRejected")
                self.assertEqual(result["slot_reason"], "slot_malformed")
                self.assertNotIn("body", result["error"])
                self.assertFalse(self.state.exists())
                self.assertEqual(self._temps(), [])

    async def test_grammar_bounds_and_code_fence_does_not_hide_one_pair(self) -> None:
        for limit in (1024, 65536):
            content = _slot(limit, "ok\n")
            result = await self._publish(content, "missing")
            self.assertTrue(result["ok"], result)
            self.state.unlink()
        fenced = "```\n" + _slot(8192, "inside\n") + "```\n"
        adopted = await self._publish(fenced, "missing")
        self.assertTrue(adopted["ok"], adopted)
        self.assertEqual(continuity.classify_state_slot(self.state.read_bytes())["kind"], "valid")
        prefixed = "```<!-- bridge-state-slot start limit=8192 -->\nnot a marker\n"
        self.state.unlink()
        legacy = await self._publish(prefixed, "missing")
        self.assertTrue(legacy["ok"], legacy)
        self.assertEqual(continuity.classify_state_slot(self.state.read_bytes())["kind"], "absent")

    async def test_adopted_slot_refuses_removal_widen_and_narrow(self) -> None:
        original = _slot(8192, "keep\n", before="head\n", after="tail\n")
        created = await self._publish(original, "missing")
        raw = self.state.read_bytes()
        cases = {
            "slot_removed": "head\nkeep\ntail\n",
            "slot_widened": _slot(8193, "keep\n", before="head\n", after="tail\n"),
            "slot_narrowed": _slot(1024, "keep\n", before="head\n", after="tail\n"),
        }
        for reason, candidate in cases.items():
            with self.subTest(reason=reason):
                result = await self._publish(candidate, created["revision"])
                self.assertEqual(result["slot_reason"], reason)
                self.assertEqual(result["slot_limit"], 8192)
                if reason == "slot_widened":
                    self.assertEqual(result["candidate_slot_limit"], 8193)
                if reason == "slot_narrowed":
                    self.assertEqual(result["candidate_slot_limit"], 1024)
                self.assertEqual(self.state.read_bytes(), raw)
                self.assertEqual(self._temps(), [])

    async def test_malformed_current_repairs_to_clean_or_one_slot(self) -> None:
        broken = b"<!-- bridge-state-slot start limit=8192 -->\norphan\n"
        self.state.write_bytes(broken)
        revision = _rev(broken)
        still_bad = await self._publish("<!-- bridge-state-slot end -->\n", revision)
        self.assertEqual(still_bad["slot_reason"], "slot_malformed")
        self.assertEqual(self.state.read_bytes(), broken)
        cleaned = await self._publish("plain\n", revision)
        self.assertTrue(cleaned["ok"], cleaned)
        self.assertEqual(self.state.read_bytes(), b"plain\n")
        self.state.write_bytes(broken)
        repaired = await self._publish(_slot(2048, "fixed\n"), _rev(broken))
        self.assertTrue(repaired["ok"], repaired)
        self.assertEqual(continuity.classify_state_slot(self.state.read_bytes())["limit"], 2048)

    async def test_edits_revalidate_inside_and_outside_the_slot(self) -> None:
        body = ("a" * 8187) + "TAIL\n"
        content = _slot(8192, body, before="HEAD\n", after="OUTSIDE\n")
        created = await self._publish(content, "missing")
        raw = self.state.read_bytes()
        outside = await self._publish(None, created["revision"], edits=[
            {"old_text": "OUTSIDE", "new_text": "EDITED"},
        ])
        self.assertTrue(outside["ok"], outside)
        updated = self.state.read_bytes()
        self.assertIn(b"EDITED", updated)
        self.assertNotIn(b"OUTSIDE", updated)
        classified = continuity.classify_state_slot(updated)
        self.assertEqual((classified["limit"], classified["body_bytes"]), (8192, 8192))
        grown = await self._publish(None, outside["revision"], edits=[
            {"old_text": "TAIL", "new_text": "TAILX"},
        ])
        self.assertEqual(grown["slot_reason"], "slot_body_exceeds_limit")
        self.assertEqual(grown["slot_body_bytes"], 8193)
        self.assertEqual(self.state.read_bytes(), updated)
        widened = await self._publish(None, outside["revision"], edits=[
            {"old_text": "limit=8192", "new_text": "limit=9000"},
        ])
        self.assertEqual(widened["slot_reason"], "slot_widened")
        self.assertEqual(self.state.read_bytes(), updated)
        self.assertEqual(self._temps(), [])

    async def test_stale_revision_wins_over_a_slot_violation(self) -> None:
        content = _slot(8192, "stable\n")
        created = await self._publish(content, "missing")
        raw = self.state.read_bytes()
        stale = await self._publish(_slot(8192, "a" * 9000), "sha256:" + "0" * 64)
        self.assertEqual(stale["error_type"], "CheckpointConflict")
        stale_edit = await self._publish(None, "sha256:" + "ab" * 32, edits=[
            {"old_text": "stable", "new_text": "a" * 9000},
        ])
        self.assertEqual(stale_edit["error_type"], "CheckpointConflict")
        self.assertEqual(self.state.read_bytes(), raw)
        self.assertEqual(self._temps(), [])

    async def test_overlong_digit_limit_is_malformed_for_every_current_kind(self) -> None:
        digits = "5" * 5000
        bad_start = f"<!-- bridge-state-slot start limit={digits} -->\n"
        candidate = bad_start + "body\n<!-- bridge-state-slot end -->\n"
        encoded = candidate.encode("utf-8")
        self.assertEqual(
            continuity.classify_state_slot(encoded),
            {"kind": "malformed", "limit": None, "body_bytes": None},
        )
        missing = await self._publish(candidate, continuity.CHECKPOINT_MISSING_REVISION)
        self.assertEqual((missing["error_type"], missing["slot_reason"]),
                         ("CheckpointSlotRejected", "slot_malformed"))
        self.assertFalse(self.state.exists())
        created = await self._publish("plain\n", continuity.CHECKPOINT_MISSING_REVISION)
        self.assertTrue(created["ok"], created)
        unslotted = await self._publish(candidate, created["revision"])
        self.assertEqual(unslotted["slot_reason"], "slot_malformed")
        self.assertEqual(self.state.read_bytes(), b"plain\n")
        slotted = await self._publish(_slot(8192, "keep\n", before="head\n"), created["revision"])
        self.assertTrue(slotted["ok"], slotted)
        slotted_raw = self.state.read_bytes()
        over_slotted = await self._publish(candidate, slotted["revision"])
        self.assertEqual(over_slotted["slot_reason"], "slot_malformed")
        self.assertEqual(self.state.read_bytes(), slotted_raw)
        stale = await self._publish(candidate, "sha256:" + "cd" * 32)
        self.assertEqual(stale["error_type"], "CheckpointConflict")
        self.assertEqual(self.state.read_bytes(), slotted_raw)
        self.assertEqual(self._temps(), [])

    async def test_overlong_digit_limit_malformed_current_repairs(self) -> None:
        digits = "5" * 5000
        bad_start = f"<!-- bridge-state-slot start limit={digits} -->\n"
        orphan = bad_start + "orphan\n"
        broken = bad_start + "body\n<!-- bridge-state-slot end -->\n"
        broken_bytes = broken.encode("utf-8")
        self.state.write_bytes(broken_bytes)
        revision = _rev(broken_bytes)
        still_bad = await self._publish(orphan, revision)
        self.assertEqual((still_bad["error_type"], still_bad["slot_reason"]),
                         ("CheckpointSlotRejected", "slot_malformed"))
        cleaned = await self._publish("clean\n", revision)
        self.assertTrue(cleaned["ok"], cleaned)
        self.assertEqual(self.state.read_bytes(), b"clean\n")
        self.state.write_bytes(broken_bytes)
        replaced = await self._publish(_slot(2048, "fixed\n"), _rev(broken_bytes))
        self.assertTrue(replaced["ok"], replaced)
        self.assertEqual(self.state.read_bytes(),
                         _slot(2048, "fixed\n").encode("utf-8"))
        self.state.write_bytes(broken_bytes)
        edited = await self._publish(None, _rev(broken_bytes), edits=[
            {"old_text": f"<!-- bridge-state-slot start limit={digits} -->",
             "new_text": "<!-- bridge-state-slot start limit=8192 -->"},
        ])
        self.assertTrue(edited["ok"], edited)
        classified = continuity.classify_state_slot(self.state.read_bytes())
        self.assertEqual((classified["kind"], classified["limit"], classified["body_bytes"]),
                         ("valid", 8192, 5))
        self.assertEqual(self._temps(), [])


    async def test_crlf_and_multibyte_body_boundaries(self) -> None:
        exact = _slot(1024, ("x" * 1022) + "\r\n", newline="\r\n")
        encoded = exact.encode("utf-8")
        classified = continuity.classify_state_slot(encoded)
        self.assertEqual(classified["body_bytes"], 1024)
        created = await self._publish(exact, "missing")
        self.assertTrue(created["ok"], created)
        self.assertEqual(self.state.read_bytes(), encoded)
        over = _slot(1024, ("x" * 1023) + "\r\n", newline="\r\n")
        refused = await self._publish(over, created["revision"])
        self.assertEqual(refused["slot_reason"], "slot_body_exceeds_limit")
        self.assertEqual(refused["slot_body_bytes"], 1025)
        self.assertEqual(self.state.read_bytes(), encoded)
        fit = _slot(1024, ("a" * 1021) + "é\n")
        self.assertEqual(continuity.classify_state_slot(fit.encode("utf-8"))["body_bytes"], 1024)
        accepted = await self._publish(fit, created["revision"])
        self.assertTrue(accepted["ok"], accepted)
        spill = _slot(1024, ("a" * 1022) + "é\n")
        self.assertEqual(continuity.classify_state_slot(spill.encode("utf-8"))["body_bytes"], 1025)
        rejected = await self._publish(spill, accepted["revision"])
        self.assertEqual(rejected["slot_reason"], "slot_body_exceeds_limit")
        self.assertEqual(rejected["slot_body_bytes"], 1025)
        self.assertEqual(self.state.read_bytes(), fit.encode("utf-8"))

    async def test_whole_file_cap_remains_the_backstop(self) -> None:
        refused = await self._publish("x" * 65537, "missing")
        self.assertEqual(refused["error_type"], "InvalidCheckpointContent")
        self.assertFalse(self.state.exists())
        slotted = _slot(1024, ("b" * 1024) + "\n")
        pad = 65536 - len(slotted.encode("utf-8"))
        self.assertGreater(pad, 0)
        full = slotted + ("p" * pad)
        self.assertEqual(len(full.encode("utf-8")), 65536)
        capped = await self._publish(full, "missing")
        self.assertEqual(capped["error_type"], "CheckpointSlotRejected")
        self.assertEqual(capped["slot_reason"], "slot_body_exceeds_limit")
        self.assertFalse(self.state.exists())

    async def test_project_text_edit_can_bypass_the_slot(self) -> None:
        content = _slot(8192, "body\n")
        created = await self._publish(content, "missing")
        self.assertTrue(created["ok"], created)
        original = self.state.read_bytes()
        edited = await server.project_text_edit(
            "project", "STATE.md", hashlib.sha256(original).hexdigest(),
            [{"old_text": "limit=8192", "new_text": "limit=9000"}],
        )
        self.assertEqual(edited["status"], "edited", edited)
        classified = continuity.classify_state_slot(self.state.read_bytes())
        self.assertEqual((classified["kind"], classified["limit"]), ("valid", 9000))
