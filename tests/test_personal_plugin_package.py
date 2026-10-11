"""Isolated stdlib package tests; no host installation, MCP or real bindings."""
import contextlib
import getpass
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "personal_plugin_package", ROOT / "scripts/prepare-personal-plugin.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)
SYNTHETIC_ID = "asdk_app_SyntheticPackageTest_01-X"
LEGACY_ID = "asdk_app_" + "fedcba9876543210" * 2
# Independent public-format oracle: do not reuse package.APP_ID.
PUBLIC_NATIVE_FORMAT = re.compile(r"^(asdk_app_|connector_|templated_apps_)[A-Za-z0-9][A-Za-z0-9_-]*$")
# Test-only invented attribution. This is not a license for the Bridge source.
SYNTHETIC_LICENSE = b"""MIT License

Copyright (c) 2026 Synthetic Packaging Test Author

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


class PersonalPluginPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="personal-plugin-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir(mode=0o700)
        self.source_bytes = {"plugin.json": (ROOT / "plugin.json").read_bytes(),
                             "LICENSE": SYNTHETIC_LICENSE}
        for name in package.SKILLS:
            path = f"skills/{name}/SKILL.md"
            self.source_bytes[path] = (ROOT / path).read_bytes()
        for path, content in self.source_bytes.items():
            target = self.source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.output = self.base / "marketplace"

    def prepare(self, app_id=SYNTHETIC_ID):
        package.prepare(self.source, self.output, app_id)

    def assert_no_publication(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".bridge-plugin-pending-*")), [])

    def manifest_change(self, change):
        path = self.source / "plugin.json"
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_exact_tree_manifest_mapping_bytes_and_modes(self):
        # Poisoned extra root paths must never be read or copied.
        (self.source / ".app.json").symlink_to(self.base / "missing-real-binding")
        (self.source / ".principal").symlink_to(self.base / "missing-cognition")
        self.prepare()
        plugin = self.output / "plugins/gpt-agent-bridge"
        expected = {".agents/plugins/marketplace.json",
                    "plugins/gpt-agent-bridge/.app.json"}
        expected.update("plugins/gpt-agent-bridge/" + p for p in self.source_bytes)
        actual = {str(p.relative_to(self.output)) for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 8)
        for path, content in self.source_bytes.items():
            self.assertEqual((plugin / path).read_bytes(), content)
            self.assertEqual((self.source / path).read_bytes(), content)
        self.assertEqual(json.loads((plugin / ".app.json").read_text()),
                         {"apps": {"bridge": {"id": SYNTHETIC_ID, "required": True}}})
        self.assertTrue(PUBLIC_NATIVE_FORMAT.fullmatch(SYNTHETIC_ID))
        self.assertEqual((plugin / "LICENSE").read_bytes(), SYNTHETIC_LICENSE)
        self.assertIn(b"Synthetic Packaging Test Author", (plugin / "LICENSE").read_bytes())
        catalog = json.loads((self.output / ".agents/plugins/marketplace.json").read_text())
        self.assertEqual(catalog["name"], "personal-gpt-agent-bridge")
        entry, = catalog["plugins"]
        self.assertEqual(entry, {
            "name": "gpt-agent-bridge",
            "source": {"source": "local", "path": "./plugins/gpt-agent-bridge"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity"})
        self.assertEqual(self.output / entry["source"]["path"], plugin)
        for path in [self.output, *self.output.rglob("*")]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
            if path.is_file() and path.name != ".app.json":
                self.assertNotIn(SYNTHETIC_ID.encode(), path.read_bytes())
        self.assertEqual(list(self.base.glob(".bridge-plugin-pending-*")), [])

    def test_reproducible_files_across_distinct_output_roots(self):
        self.prepare()
        second = self.base / "another-marketplace"
        package.prepare(self.source, second, SYNTHETIC_ID)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (second / path.relative_to(self.output)).read_bytes())

    def test_legacy_id_preserved_without_conversion(self):
        self.prepare(LEGACY_ID)
        app = json.loads((self.output / "plugins/gpt-agent-bridge/.app.json").read_text())
        self.assertEqual(app["apps"]["bridge"]["id"], LEGACY_ID)

    def test_placeholder_and_unsupported_id_rejected_without_disclosure(self):
        for value in ("asdk_app_REPLACE_WITH_OWN_APP_ID", "plugin_asdk_app_",
                      "plugin_asdk_app_" + "a" * 32, "asdk_app_", "connector_", "templated_apps_",
                      SYNTHETIC_ID + "\n", " " + SYNTHETIC_ID, "https://example.invalid/mcp/private",
                      "asdk_app__suffix", "connector_-suffix", "templated_apps_\u00e9",
                      "asdk_app_A\x00", "asdk_app_A\x7f", "asdk_app_A\t", "asdk_app_A B",
                      SYNTHETIC_ID + "/extra", "asdk_app_A.", "ASDK_APP_A"):
            with self.subTest(value=value):
                with self.assertRaises(package.PackageError) as error:
                    self.prepare(value)
                self.assertNotIn(value, str(error.exception))
                self.assert_no_publication()

    def test_native_prefix_families_ascii_suffix_and_lengths_preserved(self):
        for number, value in enumerate((
            "asdk_app_A", "asdk_app_0", "asdk_app_" + "a" * 31,
            "asdk_app_" + "A" * 32, "connector_Z9_x-Y", "templated_apps_0_X-Y",
            "connector_" + "b" * 70, "asdk_app_" + "C" * (256 - len("asdk_app_")),
        )):
            with self.subTest(value=value):
                self.assertTrue(PUBLIC_NATIVE_FORMAT.fullmatch(value))
                output = self.base / f"native-market-{number}"
                package.prepare(self.source, output, value)
                mapping = json.loads((output / "plugins/gpt-agent-bridge/.app.json").read_text())
                result = mapping["apps"]["bridge"]["id"]
                self.assertEqual(result, value)
                self.assertTrue(PUBLIC_NATIVE_FORMAT.fullmatch(result))

    def test_browser_id_rejected_before_source_read_or_staging(self):
        value = "plugin_asdk_app_" + "a" * 32
        with patch.object(package, "source_snapshot") as source, patch.object(package, "Staging") as stage:
            with self.assertRaisesRegex(package.PackageError, "Web Plugin Creator") as error:
                self.prepare(value)
            self.assertNotIn(value, str(error.exception))
            source.assert_not_called()
            stage.assert_not_called()
        self.assert_no_publication()

    def test_id_length_bound_consistent_for_hidden_and_file_input(self):
        path = self.base / "id-input"
        for length in (256, 257):
            value = "asdk_app_" + "x" * (length - len("asdk_app_"))
            self.assertTrue(PUBLIC_NATIVE_FORMAT.fullmatch(value))
            path.write_text(value + "\n")
            path.chmod(0o600)
            with patch.object(package.sys.stdin, "isatty", return_value=True), \
                    patch.object(package.getpass, "getpass", return_value=value):
                if length == 256:
                    self.assertEqual(package.input_id(), value)
                    self.assertEqual(package.input_id(path), value)
                else:
                    with self.assertRaises(package.PackageError):
                        package.input_id()
                    with self.assertRaises(package.PackageError):
                        package.input_id(path)

    def test_missing_license_fails_before_staging_without_invention(self):
        path = self.source / "LICENSE"
        path.unlink()
        with patch.object(package, "Staging") as stage:
            with self.assertRaisesRegex(package.PackageError, "LICENSE.*reviewed licensed public"):
                self.prepare()
            stage.assert_not_called()
        self.assertFalse(path.exists())
        self.assert_no_publication()

    def test_empty_invalid_utf8_nul_oversized_license_refused(self):
        path = self.source / "LICENSE"
        for content in (b"", b" \n\t", b"\xff", b"notice\x00", b"x" * (package.LIMIT + 1)):
            with self.subTest(size=len(content)):
                path.write_bytes(content)
                with self.assertRaises(package.PackageError):
                    self.prepare()
                self.assertEqual(path.read_bytes(), content)
                self.assert_no_publication()

    def test_license_symlink_hardlink_directory_and_fifo_refused(self):
        path = self.source / "LICENSE"
        other = self.base / "other-license"
        other.write_bytes(SYNTHETIC_LICENSE)
        path.unlink()
        path.symlink_to(other)
        with self.assertRaises(package.PackageError):
            self.prepare()
        path.unlink()
        os.link(other, path)
        with self.assertRaises(package.PackageError):
            self.prepare()
        path.unlink()
        path.mkdir()
        with self.assertRaises(package.PackageError):
            self.prepare()
        path.rmdir()
        os.mkfifo(path)
        with self.assertRaises(package.PackageError):
            self.prepare()
        self.assertEqual(other.read_bytes(), SYNTHETIC_LICENSE)
        self.assert_no_publication()

    def test_license_changed_during_read_refused(self):
        original = package.os.read
        path = self.source / "LICENSE"
        changed = False

        def changing_read(fd, size):
            nonlocal changed
            result = original(fd, size)
            if not changed and result:
                changed = True
                with path.open("ab") as stream:
                    stream.write(b"\nsynthetic changed notice\n")
            return result

        with patch.object(package.os, "read", side_effect=changing_read):
            with self.assertRaises(package.PackageError):
                self.prepare()
        self.assertTrue(changed)
        self.assert_no_publication()

    def test_license_changed_between_snapshots_refused(self):
        original = package.source_snapshot
        calls = 0

        def changing(source):
            nonlocal calls
            calls += 1
            if calls == 2:
                (source / "LICENSE").write_bytes(SYNTHETIC_LICENSE + b"\nchanged\n")
            return original(source)

        with patch.object(package, "source_snapshot", changing):
            with self.assertRaisesRegex(package.PackageError, "source changed"):
                self.prepare()
        self.assertEqual(calls, 2)
        self.assert_no_publication()

    def test_staged_license_tampering_refused(self):
        original = package.Staging.verify

        def tampering(stage):
            (self.base / stage.name / "plugins/gpt-agent-bridge/LICENSE").write_text("changed notice")
            original(stage)

        with patch.object(package.Staging, "verify", tampering):
            with self.assertRaisesRegex(package.PackageError, "Staging bytes changed"):
                self.prepare()
        self.assert_no_publication()

    def test_existing_directory_and_file_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "user-work"
        marker.write_bytes(b"preserve")
        with self.assertRaises(package.PackageError):
            self.prepare()
        self.assertEqual(marker.read_bytes(), b"preserve")
        marker.unlink()
        self.output.rmdir()
        self.output.write_bytes(b"existing file")
        with self.assertRaises(package.PackageError):
            self.prepare()
        self.assertEqual(self.output.read_bytes(), b"existing file")

    def test_destination_symlink_and_broken_symlink_refused(self):
        for target in (self.source, self.base / "missing"):
            with self.subTest(target=target):
                self.output.symlink_to(target)
                with self.assertRaises(package.PackageError):
                    self.prepare()
                self.assertTrue(self.output.is_symlink())
                self.output.unlink()

    def test_source_manifest_skill_and_directory_symlinks_refused(self):
        for relative in ("plugin.json", "skills/project-resume/SKILL.md", "skills/project-resume", "skills"):
            with self.subTest(relative=relative):
                path = self.source / relative
                saved = self.base / "saved-input"
                path.rename(saved)
                path.symlink_to(saved, target_is_directory=saved.is_dir())
                try:
                    with self.assertRaises(OSError):
                        self.prepare()
                    self.assert_no_publication()
                finally:
                    path.unlink()
                    saved.rename(path)

    def test_symlink_in_source_or_destination_parent_refused(self):
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            package.prepare(alias, self.output, SYNTHETIC_ID)
        parent_alias = self.base / "parent-alias"
        parent_alias.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(OSError):
            package.prepare(self.source, parent_alias / "output", SYNTHETIC_ID)
        self.assert_no_publication()

    def test_relative_traversal_source_containment_and_missing_parent_refused(self):
        for output in (Path("relative"), self.source / "new-market", self.source,
                       self.base / "missing-parent/new-market", self.base / "x/../new-market"):
            with self.subTest(output=output):
                with self.assertRaises((package.PackageError, OSError)):
                    package.prepare(self.source, output, SYNTHETIC_ID)
        self.assert_no_publication()

    def test_shared_destination_parent_refused(self):
        self.base.chmod(0o777)
        try:
            with self.assertRaises(package.PackageError):
                self.prepare()
        finally:
            self.base.chmod(0o700)
        self.assert_no_publication()

    def test_extra_skill_or_skill_asset_refused(self):
        extra = self.source / "skills/extra"
        extra.mkdir()
        with self.assertRaises(package.PackageError):
            self.prepare()
        extra.rmdir()
        extra = self.source / "skills/project-resume/secret.txt"
        extra.write_text("synthetic unrelated data")
        with self.assertRaises(package.PackageError):
            self.prepare()
        self.assert_no_publication()

    def test_manifest_hooks_extra_extension_bad_mapping_version_refused(self):
        for change in (
            lambda d: d.update(hooks={}),
            lambda d: d["extensions"].update(other={}),
            lambda d: d["extensions"]["com.openai"].update(apps="../.app.json"),
            lambda d: d["extensions"]["com.openai"].update(hooks={}),
            lambda d: d.update(version="future-schema"),
            lambda d: d.update(name="other-plugin"),
        ):
            with self.subTest(change=change):
                self.manifest_change(change)
                with self.assertRaises(package.PackageError):
                    self.prepare()
                self.assert_no_publication()
                (self.source / "plugin.json").write_bytes(self.source_bytes["plugin.json"])

    def test_malformed_duplicate_json_and_skill_frontmatter_refused(self):
        manifest = self.source / "plugin.json"
        for data in (b"not JSON", b'{"name":"a","name":"b"}', b"\xff", b"[]"):
            manifest.write_bytes(data)
            with self.assertRaises(package.PackageError):
                self.prepare()
        manifest.write_bytes(self.source_bytes["plugin.json"])
        skill = self.source / "skills/project-resume/SKILL.md"
        skill.write_text("---\nname: wrong-name\ndescription: wrong\n---\nBody")
        with self.assertRaises(package.PackageError):
            self.prepare()
        self.assert_no_publication()

    def test_hardlinked_oversized_and_fifo_source_refused(self):
        manifest = self.source / "plugin.json"
        link = self.base / "linked-manifest"
        os.link(manifest, link)
        with self.assertRaises(package.PackageError):
            self.prepare()
        link.unlink()
        manifest.write_bytes(b"x" * (package.LIMIT + 1))
        with self.assertRaises(package.PackageError):
            self.prepare()
        manifest.unlink()
        os.mkfifo(manifest)
        with self.assertRaises(package.PackageError):
            self.prepare()
        self.assert_no_publication()

    def test_write_failure_cleans_only_owned_staging(self):
        original = package.Staging.write
        calls = 0

        def fail(stage, path, content):
            nonlocal calls
            calls += 1
            original(stage, path, content)
            if calls == 3:
                raise OSError("synthetic write failure")

        with patch.object(package.Staging, "write", fail):
            with self.assertRaises(OSError):
                self.prepare()
        self.assert_no_publication()

    def test_source_change_before_publication_refused(self):
        original = package.source_snapshot
        calls = 0

        def changing(source):
            nonlocal calls
            calls += 1
            result = original(source)
            if calls == 2:
                result["plugin.json"] += b"\n"
            return result

        with patch.object(package, "source_snapshot", changing):
            with self.assertRaises(package.PackageError):
                self.prepare()
        self.assert_no_publication()

    def test_concurrent_empty_destination_creation_not_clobbered(self):
        original = package.rename_no_replace
        identity = []

        def racing(parent, before, after):
            self.output.mkdir()
            identity.append(self.output.stat().st_ino)
            original(parent, before, after)

        with patch.object(package, "rename_no_replace", racing):
            with self.assertRaises(package.PackageError):
                self.prepare()
        self.assertEqual(self.output.stat().st_ino, identity[0])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list(self.base.glob(".bridge-plugin-pending-*")), [])

    def test_rename_failure_has_no_unsafe_fallback(self):
        with patch.object(package, "rename_no_replace", side_effect=package.PackageError("unsupported rename")):
            with self.assertRaises(package.PackageError):
                self.prepare()
        self.assert_no_publication()

    def test_platform_without_no_replace_rename_refuses_publication(self):
        with patch.object(package.sys, "platform", "darwin"):
            with self.assertRaisesRegex(package.PackageError, "Linux/WSL"):
                self.prepare()
        self.assert_no_publication()

    def test_post_publication_sync_uncertainty_preserves_published_package(self):
        original = package.os.fsync
        parent_inode = self.base.stat().st_ino

        def failed_parent_sync(fd):
            if os.fstat(fd).st_ino == parent_inode:
                raise OSError("synthetic parent sync failure")
            return original(fd)

        with patch.object(package.os, "fsync", side_effect=failed_parent_sync):
            with self.assertRaisesRegex(package.PackageError, "published.*uncertain"):
                self.prepare()
        self.assertTrue((self.output / "plugins/gpt-agent-bridge/.app.json").is_file())
        self.assertEqual(list(self.base.glob(".bridge-plugin-pending-*")), [])

    def test_staging_byte_tampering_and_unexpected_content_not_published(self):
        original = package.Staging.verify
        for unexpected in (False, True):
            with self.subTest(unexpected=unexpected):
                def tampering(stage):
                    path = self.base / stage.name / ("unowned" if unexpected else "plugins/gpt-agent-bridge/plugin.json")
                    path.write_text("synthetic tampering")
                    original(stage)

                with patch.object(package.Staging, "verify", tampering):
                    with self.assertRaises(package.PackageError):
                        self.prepare()
                self.assertFalse(self.output.exists())
                if not unexpected:
                    self.assert_no_publication()
                else:
                    residue, = self.base.glob(".bridge-plugin-pending-*")
                    self.assertEqual((residue / "unowned").read_text(), "synthetic tampering")

    def test_replaced_staging_file_is_preserved_on_failure(self):
        original = package.Staging.verify
        replacement = []

        def replace_file(stage):
            path = self.base / stage.name / "plugins/gpt-agent-bridge/plugin.json"
            # Move the original away so the inode cannot immediately be reused.
            path.rename(self.base / "original-staging-manifest")
            path.write_text("unknown replacement")
            replacement.append(path)
            original(stage)

        with patch.object(package.Staging, "verify", replace_file):
            with self.assertRaisesRegex(package.PackageError, "residue"):
                self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(replacement[0].read_text(), "unknown replacement")

    def test_unexpected_staging_content_preserved_not_recursively_cleaned(self):
        original = package.Staging.write
        unknown = []

        def foreign(stage, path, content):
            original(stage, path, content)
            extra = self.base / stage.name / "unowned"
            extra.write_text("preserve unknown")
            unknown.append(extra)
            raise OSError("synthetic failure")

        with patch.object(package.Staging, "write", foreign):
            with self.assertRaisesRegex(package.PackageError, "residue"):
                self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(unknown[0].read_text(), "preserve unknown")

    def test_private_id_file_success_and_permissions_owner_links_symlink_refused(self):
        path = self.base / "id-input"
        path.write_text(SYNTHETIC_ID + "\n")
        path.chmod(0o600)
        self.assertEqual(package.input_id(path), SYNTHETIC_ID)
        path.chmod(0o400)
        self.assertEqual(package.input_id(path), SYNTHETIC_ID)
        path.chmod(0o644)
        with self.assertRaises(package.PackageError):
            package.input_id(path)
        path.chmod(0o600)
        alias = self.base / "id-alias"
        alias.symlink_to(path)
        with self.assertRaises(OSError):
            package.input_id(alias)
        alias.unlink()
        os.link(path, alias)
        with self.assertRaises(package.PackageError):
            package.input_id(path)
        alias.unlink()
        info = path.stat()
        fake = type("Stat", (), {"st_mode": info.st_mode, "st_uid": info.st_uid + 1,
                                 "st_nlink": 1, "st_size": info.st_size})()
        with patch.object(package.os, "fstat", return_value=fake):
            with self.assertRaises(package.PackageError):
                package.input_id(path)

    def test_id_file_multiple_lines_and_crlf_rejected(self):
        path = self.base / "id-input"
        for content in (SYNTHETIC_ID + "\nother\n", SYNTHETIC_ID + "\r\n", ""):
            path.write_bytes(content.encode())
            path.chmod(0o600)
            with self.assertRaises(package.PackageError):
                package.input_id(path)

    def test_cli_success_has_no_id_in_output(self):
        path = self.base / "id-input"
        path.write_text(SYNTHETIC_ID)
        path.chmod(0o600)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = package.main(["--source", str(self.source), "--marketplace-root", str(self.output),
                                   "--id-file", str(path)])
        self.assertEqual(result, 0)
        self.assertIn("host Skills remain unverified", out.getvalue())
        self.assertNotIn(SYNTHETIC_ID, out.getvalue() + err.getvalue())

    def test_standalone_cli_uses_private_file_without_id_argv_or_output(self):
        path = self.base / "id-input"
        path.write_text(SYNTHETIC_ID + "\n")
        path.chmod(0o600)
        argv = [sys.executable, "-B", str(ROOT / "scripts/prepare-personal-plugin.py"),
                "--source", str(self.source), "--marketplace-root", str(self.output),
                "--id-file", str(path)]
        self.assertNotIn(SYNTHETIC_ID, " ".join(argv))
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=10, env={"PATH": os.defpath, "LANG": "C.UTF-8"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SYNTHETIC_ID, result.stdout + result.stderr)
        self.assertTrue((self.output / ".agents/plugins/marketplace.json").is_file())

    def test_invalid_argv_and_errors_do_not_echo_supplied_id(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = package.main(["--marketplace-root", str(self.output), "--app-id", SYNTHETIC_ID])
        self.assertEqual(result, 1)
        self.assertNotIn(SYNTHETIC_ID, out.getvalue() + err.getvalue())
        self.assert_no_publication()

    def test_non_tty_and_getpass_warning_fail_closed(self):
        with patch.object(package.sys.stdin, "isatty", return_value=False), \
                patch.object(package.getpass, "getpass") as prompt:
            with self.assertRaises(package.PackageError):
                package.input_id()
            prompt.assert_not_called()

        def unsafe_prompt(*args):
            warnings.warn("cannot hide input", getpass.GetPassWarning)
            self.fail("echo fallback must not reach this point")

        with patch.object(package.sys.stdin, "isatty", return_value=True), \
                patch.object(package.getpass, "getpass", side_effect=unsafe_prompt):
            with self.assertRaises(getpass.GetPassWarning):
                package.input_id()

    def test_hidden_interactive_input_returns_exact_id(self):
        with patch.object(package.sys.stdin, "isatty", return_value=True), \
                patch.object(package.getpass, "getpass", return_value=SYNTHETIC_ID):
            self.assertEqual(package.input_id(), SYNTHETIC_ID)


if __name__ == "__main__":
    unittest.main()
