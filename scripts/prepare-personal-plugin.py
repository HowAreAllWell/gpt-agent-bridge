#!/usr/bin/env python3
"""Prepare a private local marketplace; never install it or contact a host.

Linux/WSL only: renameat2(RENAME_NOREPLACE) publishes without a clobber race.
Only plugin.json, LICENSE and four reviewed SKILL.md files are source inputs.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import warnings


SKILLS = (
    "project-resume", "handoff-preparation", "project-onboarding", "team-deliberation",
)
APP_ID = re.compile(r"(?:asdk_app_|connector_|templated_apps_)[A-Za-z0-9][A-Za-z0-9_-]*\Z")
MAX_ID_LENGTH = 256  # Local bound, not a host-wide format requirement.
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
LIMIT = 1024 * 1024
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class PackageError(Exception):
    """Safe operator-facing explanation; never contains an input ID."""


def absolute_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        raise PackageError("Use an absolute path without '..', below an existing directory.")
    return path


def open_directory(path: Path) -> int:
    """Walk each component without following symlinks, returning an owned fd."""
    fd = os.open("/", DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_regular(parent: int, name: str, limit: int = LIMIT, private: bool = False) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise PackageError("Input must be a bounded regular file, without hard links.")
        if private and (before.st_uid != os.getuid()
                        or stat.S_IMODE(before.st_mode) not in (0o400, 0o600)):
            raise PackageError("The ID file must be owned by you with mode 0600 or 0400.")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                raise PackageError("Input exceeds the permitted size.")
        after = os.fstat(fd)
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if signature(before) != signature(after):
            raise PackageError("Input changed while being read; review before retrying.")
        return b"".join(chunks)
    finally:
        os.close(fd)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackageError("Duplicate manifest keys are not accepted.")
        result[key] = value
    return result


def source_snapshot(source: Path) -> dict[str, bytes]:
    """An explicit allowlist, never a recursive copy of the checkout."""
    with contextlib.ExitStack() as stack:
        root = open_directory(source)
        stack.callback(os.close, root)
        try:
            license_bytes = read_regular(root, "LICENSE")
        except (OSError, PackageError):
            raise PackageError("Source LICENSE is missing or unsafe. Use a reviewed licensed public source checkout; never invent a license.") from None
        try:
            license_text = license_bytes.decode("utf-8")
        except UnicodeError:
            raise PackageError("Source LICENSE must be nonempty UTF-8 notice text.") from None
        if not license_text.strip() or "\x00" in license_text:
            raise PackageError("Source LICENSE must be nonempty UTF-8 notice text.")
        manifest = read_regular(root, "plugin.json")
        try:
            data = json.loads(manifest.decode("utf-8"), object_pairs_hook=unique_object)
        except (ValueError, UnicodeError):
            raise PackageError("Source plugin.json must be valid UTF-8 JSON.") from None
        if (not isinstance(data, dict)
                or set(data) != {"$schema", "name", "version", "description", "extensions"}
                or data["$schema"] != SCHEMA or data["name"] != "gpt-agent-bridge"
                or not isinstance(data["version"], str)
                or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", data["version"])
                or not isinstance(data["description"], str) or not data["description"]):
            raise PackageError("Source manifest differs from the supported reviewed shape.")
        extension = data["extensions"]
        if not isinstance(extension, dict) or set(extension) != {"com.openai"}:
            raise PackageError("Unexpected plugin extension; review the source first.")
        settings = extension["com.openai"]
        if (not isinstance(settings, dict) or set(settings) != {"apps", "interface"}
                or settings["apps"] != "./.app.json"
                or not isinstance(settings["interface"], dict)
                or set(settings["interface"]) != {"displayName", "shortDescription"}
                or not all(isinstance(v, str) and v for v in settings["interface"].values())):
            raise PackageError("Unexpected plugin settings; hooks and extra paths are refused.")
        skills = os.open("skills", DIRECTORY, dir_fd=root)
        stack.callback(os.close, skills)
        if set(os.listdir(skills)) != set(SKILLS):
            raise PackageError("Source skills must contain exactly the four reviewed procedures.")
        result = {"plugin.json": manifest, "LICENSE": license_bytes}
        for name in SKILLS:
            folder = os.open(name, DIRECTORY, dir_fd=skills)
            stack.callback(os.close, folder)
            if os.listdir(folder) != ["SKILL.md"]:
                raise PackageError("Extra Skill files are refused; review the source first.")
            body = read_regular(folder, "SKILL.md")
            try:
                text = body.decode("utf-8")
            except UnicodeError:
                raise PackageError("Skill text must be UTF-8.") from None
            parts = text.split("---", 2)
            fields = parts[1].strip().splitlines() if len(parts) == 3 else []
            if (len(parts) != 3 or parts[0] != ""
                    or len(fields) != 2
                    or not re.search(r"^name: " + re.escape(name) + r"$", parts[1], re.M)
                    or not re.search(r"^description: \S.+$", parts[1], re.M)
                    or not parts[2].strip()):
                raise PackageError("Skill frontmatter/body differs from the supported shape.")
            result[f"skills/{name}/SKILL.md"] = body
        return result


def validate_id(value: str) -> str:
    # Native shared app_id_format, not a browser-ID conversion or access check.
    if value.startswith("plugin_"):
        raise PackageError("Browser plugin IDs cannot go in .app.json. Use Web Plugin Creator to select your existing App and resolve its native ID; no prefix conversion is performed.")
    if (len(value) > MAX_ID_LENGTH or value == "asdk_app_REPLACE_WITH_OWN_APP_ID"
            or not APP_ID.fullmatch(value)):
        raise PackageError("Use a verified native App ID with an approved prefix and ASCII alphanumeric suffix then alphanumeric/_/-. No URLs, whitespace or placeholders; local limit is 256 characters. See docs/TECHNICAL-REFERENCE.md#private-native-plugin-packaging for host resolution.")
    return value


def input_id(id_file: Path | None = None) -> str:
    if id_file is not None:
        path = absolute_path(id_file)
        parent = open_directory(path.parent)
        try:
            raw = read_regular(parent, path.name, limit=MAX_ID_LENGTH + 1, private=True).decode("utf-8")
        finally:
            os.close(parent)
        # One line only; whitespace is never silently stripped or prefix-converted.
        return validate_id(raw[:-1] if raw.endswith("\n") else raw)
    if not sys.stdin.isatty():
        raise PackageError("Use a private interactive terminal or an owner-only --id-file; stdin fallback is refused.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return validate_id(getpass.getpass("Verified native App ID for your existing connection (hidden): "))


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def rename_no_replace(parent: int, before: str, after: str) -> None:
    """Linux atomic no-clobber directory publication, never os.replace fallback."""
    if not sys.platform.startswith("linux"):
        raise PackageError("Atomic no-replace publication requires Linux/WSL.")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError:
        raise PackageError("renameat2 is unavailable; no unsafe rename fallback is used.") from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(before), parent, os.fsencode(after), 1) != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise PackageError("Destination appeared during preparation; it was not overwritten.")
        raise PackageError("Atomic no-replace publication failed; inspect before retrying.")


class Staging:
    """Track only our created objects; never recursively delete arbitrary content."""
    def __init__(self, parent: int):
        self.parent = parent
        self.name = ".bridge-plugin-pending-" + secrets.token_hex(12)
        os.mkdir(self.name, 0o700, dir_fd=parent)
        self.root_identity = self.identity(parent, self.name)
        try:
            self.root = os.open(self.name, DIRECTORY, dir_fd=parent)
        except BaseException:
            if self.identity(parent, self.name) == self.root_identity:
                os.rmdir(self.name, dir_fd=parent)
            raise
        self.directories = {"": self.root}
        self.created = []
        self.contents = {}
        self.published = False

    @staticmethod
    def identity(parent: int, name: str):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)

    def write(self, path: str, content: bytes):
        parts = path.split("/")
        prefix = ""
        for part in parts[:-1]:
            next_prefix = f"{prefix}/{part}".lstrip("/")
            if next_prefix not in self.directories:
                parent = self.directories[prefix]
                os.mkdir(part, 0o700, dir_fd=parent)
                self.created.append((parent, part, self.identity(parent, part), True))
                self.directories[next_prefix] = os.open(part, DIRECTORY, dir_fd=parent)
            prefix = next_prefix
        parent, name = self.directories[prefix], parts[-1]
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        self.created.append((parent, name, self.identity(parent, name), False))
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        self.contents[path] = content

    def verify(self):
        if self.identity(self.parent, self.name) != self.root_identity:
            raise PackageError("Staging root changed; nothing was published.")
        children = {path: set() for path in self.directories}
        for path in [*self.directories, *self.contents]:
            if path:
                parent, _, name = path.rpartition("/")
                children[parent].add(name)
        for path, fd in self.directories.items():
            if set(os.listdir(fd)) != children[path]:
                raise PackageError("Unexpected staging content; nothing was published.")
        for parent, name, identity, _ in self.created:
            if self.identity(parent, name) != identity:
                raise PackageError("Staging object changed; nothing was published.")
        for path, content in self.contents.items():
            parent, _, name = path.rpartition("/")
            if read_regular(self.directories[parent], name) != content:
                raise PackageError("Staging bytes changed; nothing was published.")

    def close(self):
        clean = True
        try:
            if not self.published:
                for parent, name, identity, directory in reversed(self.created):
                    try:
                        if self.identity(parent, name) != identity:
                            clean = False
                            continue
                        if directory:
                            os.rmdir(name, dir_fd=parent)
                        else:
                            os.unlink(name, dir_fd=parent)
                    except OSError:
                        clean = False
                if clean and self.identity(self.parent, self.name) == self.root_identity:
                    os.rmdir(self.name, dir_fd=self.parent)
                else:
                    clean = False
        except OSError:
            clean = False
        finally:
            for fd in reversed(list(self.directories.values())):
                os.close(fd)
        return clean


def prepare(source: Path, destination: Path, app_id: str) -> None:
    source, destination = absolute_path(source), absolute_path(destination)
    validate_id(app_id)
    if source == destination or source in destination.parents or destination in source.parents:
        raise PackageError("The marketplace must be outside, and must not contain, the source checkout.")
    inputs = source_snapshot(source)
    parent = open_directory(destination.parent)
    staging = None
    try:
        info = os.fstat(parent)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise PackageError("Destination parent must be owned by you and not writable by group/others.")
        try:
            os.stat(destination.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise PackageError("Destination already exists; choose a new marketplace root.")
        staging = Staging(parent)
        plugin = "plugins/gpt-agent-bridge/"
        for path, content in inputs.items():
            staging.write(plugin + path, content)
        staging.write(plugin + ".app.json", json_bytes({"apps": {
            "bridge": {"id": app_id, "required": True}}}))
        staging.write(".agents/plugins/marketplace.json", json_bytes({
            "name": "personal-gpt-agent-bridge",
            "interface": {"displayName": "Personal GPT-Agent Bridge"},
            "plugins": [{"name": "gpt-agent-bridge",
                         "source": {"source": "local", "path": "./plugins/gpt-agent-bridge"},
                         "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                         "category": "Productivity"}],
        }))
        if source_snapshot(source) != inputs:
            raise PackageError("Reviewed source changed during preparation; nothing was published.")
        check = open_directory(destination.parent)
        try:
            if (os.fstat(check).st_dev, os.fstat(check).st_ino) != (info.st_dev, info.st_ino):
                raise PackageError("Destination parent changed; nothing was published.")
        finally:
            os.close(check)
        staging.verify()
        for fd in reversed(list(staging.directories.values())):
            os.fsync(fd)
        rename_no_replace(parent, staging.name, destination.name)
        staging.published = True
        try:
            os.fsync(parent)
        except OSError:
            raise PackageError("Package was published; directory durability is uncertain. Inspect output; do not retry.") from None
    finally:
        try:
            if staging is not None and not staging.close():
                raise PackageError("Preparation stopped; private staging residue needs manual inspection. No recursive cleanup was attempted.")
        finally:
            os.close(parent)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unrecognized arguments, potentially an ID.
        raise PackageError("Invalid arguments. Use --help; never pass the technical ID as an argument.")


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).absolute().parents[1],
                        help="absolute reviewed licensed public Bridge checkout (default: script's checkout; fails without LICENSE)")
    parser.add_argument("--marketplace-root", type=Path, required=True,
                        help="absolute NEW directory outside source; parent must already exist")
    parser.add_argument("--id-file", type=Path,
                        help="optional absolute owner-only file with one exact ID line")
    try:
        args = parser.parse_args(argv)
        prepare(args.source, args.marketplace_root, input_id(args.id_file))
    except (PackageError, OSError, UnicodeError, getpass.GetPassWarning, EOFError, KeyboardInterrupt) as error:
        explanation = str(error) if isinstance(error, PackageError) else "Preparation stopped safely; no input ID is shown. Inspect output before retrying."
        print(explanation, file=sys.stderr)
        return 1
    print("Prepared personal marketplace. Review and install it separately; host Skills remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
