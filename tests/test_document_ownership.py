"""Cognition ownership and active navigation contracts."""
import json
from pathlib import Path
import re
import tempfile
import unittest

from tests.continuity_fixture import write_canonical_cognition

from gpt_agent_bridge.project_continuity import MAX_CHECKPOINT_CONTENT_BYTES, classify_state_slot

ROOT = Path(__file__).resolve().parents[1]


def markdown_link_graph():
    import subprocess, re, html, urllib.parse, unicodedata
    root = ROOT
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', '*.md'], cwd=root).decode().split('\x00')
    files = [root / n for n in names if n and (not n.startswith('.principal/')) and (root / n).is_file()]

    def visible(text):
        out = []
        fence = None
        for line in text.splitlines():
            m = re.match('^ {0,3}(`{3,}|~{3,})(.*)$', line)
            if m:
                mark = m.group(1)
                if fence is None:
                    fence = mark
                elif mark[0] == fence[0] and len(mark) >= len(fence):
                    fence = None
                out.append('')
                continue
            out.append('' if fence else line)
        return out

    def slug(h):
        h = re.sub('\\[([^\\]]+)\\]\\([^)]*\\)', '\\1', h)
        h = html.unescape(re.sub('<[^>]*>', '', h)).strip().lower()
        h = re.sub('\\s+#+\\s*$', '', h)
        h = ''.join((c for c in h if c in '-_' or c.isspace() or unicodedata.category(c)[0] in 'LMN'))
        return re.sub('\\s', '-', h)
    cache = {}

    def anchors(path):
        if path in cache:
            return cache[path]
        lines = visible(path.read_text())
        ids = set()
        used = set()
        for (i, l) in enumerate(lines):
            m = re.match('^ {0,3}#{1,6}\\s+(.+?)\\s*$', l)
            heading = m.group(1) if m else None
            if not heading and i and re.match('^ {0,3}(?:=+|-+)\\s*$', l) and lines[i - 1].strip():
                heading = lines[i - 1].strip()
            if heading:
                base = slug(heading)
                candidate = base
                n = 0
                while candidate in used:
                    n += 1
                    candidate = base + '-' + str(n)
                used.add(candidate)
                ids.add(candidate)
            ids.update(re.findall('(?i)<(?:a|[a-z][a-z0-9]*)\\b[^>]*\\b(?:id|name)\\s*=\\s*["\\\']([^"\\\']+)["\\\']', l))
        cache[path] = ids
        return ids
    errors = []
    links = 0
    fragments = 0
    external = 0

    def check(path, line, dest):
        nonlocal links, fragments, external
        dest = html.unescape(dest.strip().strip('<>'))
        if not dest:
            return
        if re.match('^[A-Za-z][A-Za-z0-9+.-]*:', dest) or dest.startswith('//'):
            external += 1
            return
        (rel, sep, frag) = dest.partition('#')
        rel = urllib.parse.unquote(rel)
        frag = urllib.parse.unquote(frag)
        if '?' in rel:
            rel = rel.split('?', 1)[0]
        target = (root / rel.lstrip('/') if rel.startswith('/') else path.parent / rel).resolve() if rel else path
        links += 1
        if root not in target.parents and target != root:
            errors.append((str(path.relative_to(root)), line, dest, 'outside repository'))
            return
        if not target.exists():
            errors.append((str(path.relative_to(root)), line, dest, 'missing file'))
            return
        if sep and frag and (target.suffix.lower() == '.md'):
            fragments += 1
            if frag not in anchors(target):
                errors.append((str(path.relative_to(root)), line, dest, 'missing fragment'))
    inline = re.compile('!?\\[[^\\]\\n]*\\]\\(\\s*(<[^>]+>|(?:[^\\s()\\\\]|\\\\.|\\([^()]*\\))+)(?:\\s+["\\\'][^\\n]*?["\\\'])?\\s*\\)')
    for path in files:
        lines = visible(path.read_text())
        defs = {}
        for l in lines:
            m = re.match('^ {0,3}\\[([^\\]]+)\\]:\\s*(<[^>]+>|\\S+)', l)
            if m:
                defs[' '.join(m.group(1).lower().split())] = m.group(2)
        for (n, l) in enumerate(lines, 1):
            if re.match('^ {0,3}\\[[^\\]]+\\]:', l):
                continue
            l = re.sub('(`+)(.*?)\\1', '', l)
            if re.search(r'!?\[[^\]\n]*\]\(\s*\)', l):
                errors.append((str(path.relative_to(root)), n, '', 'empty inline destination'))
            for m in inline.finditer(l):
                check(path, n, m.group(1))
            remainder = inline.sub('', l)
            for m in re.finditer('!?\\[([^\\]]+)\\]\\[([^\\]]*)\\]', remainder):
                ref = ' '.join((m.group(2) or m.group(1)).lower().split())
                if ref in defs:
                    check(path, n, defs[ref])
            for m in re.finditer('(?<!!)\\[([^\\]]+)\\](?![\\[(])', remainder):
                ref = ' '.join(m.group(1).lower().split())
                if ref in defs:
                    check(path, n, defs[ref])
    return dict(markdown_files=len(files), local_links=links, fragment_links=fragments, errors=errors)


class DocumentOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cognition_root = Path(temporary.name)
        write_canonical_cognition(self.cognition_root)


    def test_synthetic_manifest_is_canonical_and_state_is_slotless(self):
        self.assertFalse((ROOT / '.principal').exists())
        manifest = json.loads((self.cognition_root / '.principal/project.json').read_text())
        self.assertEqual(set(manifest), {'rules', 'current_state', 'memory'})
        self.assertNotIn('version', manifest)
        self.assertEqual(manifest['rules'], ['AGENTS.md'])
        self.assertEqual(manifest['current_state'], '.principal/state.md')
        self.assertEqual(manifest['memory'], '.principal/memory.md')
        paths = manifest['rules'] + [manifest['current_state'], manifest['memory']]
        self.assertEqual(len(paths), len(set(paths)))
        for path in paths:
            self.assertTrue((self.cognition_root / path).is_file(), path)
        state = (self.cognition_root / manifest['current_state']).read_bytes()
        state.decode('utf-8')
        self.assertLessEqual(len(state), MAX_CHECKPOINT_CONTENT_BYTES)
        self.assertEqual(classify_state_slot(state)['kind'], 'absent')


    def test_active_document_links_resolve(self):
        graph = markdown_link_graph()
        self.assertGreater(graph['local_links'], 0)
        self.assertEqual(graph['errors'], [])

    def test_same_plugin_source_bundle_owns_reusable_procedures(self):
        package = json.loads((ROOT / 'plugin.json').read_text())
        self.assertEqual(package['name'], 'gpt-agent-bridge')
        self.assertEqual(package['$schema'], 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json')
        skills = {path.parent.name: path for path in (ROOT / 'skills').glob('*/SKILL.md')}
        self.assertEqual(set(skills), {'project-resume', 'handoff-preparation', 'project-onboarding', 'team-deliberation'})
        for name, path in skills.items():
            frontmatter = path.read_text().split('---', 2)
            self.assertEqual(frontmatter[0], '')
            fields = dict(line.split(': ', 1) for line in frontmatter[1].strip().splitlines())
            self.assertEqual(set(fields), {'name', 'description'})
            self.assertEqual(fields['name'], name)
            self.assertTrue(fields['description'].strip())
            self.assertTrue(frontmatter[2].strip())

    def test_registered_bridge_binding_path_id_required_and_skills(self):
        package = json.loads((ROOT / 'plugin.json').read_text())
        apps_path = package['extensions']['com.openai']['apps']
        self.assertEqual(apps_path, './.app.json')
        binding = json.loads((ROOT / apps_path).read_text())
        self.assertEqual(binding, {'apps': {'bridge': {
            'id': 'asdk_app_REPLACE_WITH_OWN_APP_ID', 'required': True}}})
        self.assertEqual(binding, json.loads((ROOT / '.app.example.json').read_text()))
        self.assertFalse((ROOT / 'docs/evidence').exists())
        entry = binding['apps']['bridge']
        self.assertRegex(entry['id'], r'\Aasdk_app_[A-Za-z0-9][A-Za-z0-9_-]*\Z')
        self.assertIs(entry['required'], True)
        self.assertEqual({p.name for p in (ROOT / 'skills').iterdir() if p.is_dir()},
                         {'project-resume', 'handoff-preparation', 'project-onboarding', 'team-deliberation'})

    def test_registered_binding_has_no_endpoint_or_distribution_configuration(self):
        package = json.loads((ROOT / 'plugin.json').read_text())
        self.assertEqual(set(package), {'$schema', 'name', 'version', 'description', 'extensions'})
        self.assertEqual(set(package['extensions']['com.openai']), {'apps', 'interface'})
        self.assertEqual(set(package['extensions']['com.openai']['interface']),
                         {'displayName', 'shortDescription'})
        for path in ('mcp.json', '.mcp.json', 'marketplace.json', '.agents/plugins/marketplace.json',
                     '.claude-plugin/marketplace.json'):
            self.assertFalse((ROOT / path).exists(), path)
