# Bridge Plugin Skills packaging and ownership

## Tools visible, Skills missing?

**18 Tools and 0 Skills** is consistent with a tools-only connection if you
only created a custom MCP connection. **Create as a plugin** registers that
connection, not the four source procedures.
The [SOURCE catalog](TECHNICAL-REFERENCE.md#tool-reference) has 18 model-facing tools (no app-only widget continuation tools); the Skills below are not extra MCP tools.
For a working Web connection, start with
[Getting started step 6](GETTING-STARTED.md#6-install-and-discover-all-four-native-skills).
Reuse the existing allowed App; keep canonical Skill bodies separate from Core.
Source packaging and another host's acceptance do not prove installation in
your target Web Project Chat.

The repository root is the canonical Bridge Plugin package source: `plugin.json`
uses the portable Agent Plugins manifest schema, and `skills/<name>/SKILL.md`
contains four separately triggered reusable procedures. These belong to the same
GPT-Agent Bridge plugin as its MCP integration.

| Skill and canonical source | Procedure | Prepared attachment filename |
| --- | --- | --- |
| [project-resume](../skills/project-resume/SKILL.md) | Recover the routed current judgment and selectively revalidate live facts | `project-resume.md` |
| [handoff-preparation](../skills/handoff-preparation/SKILL.md) | Publish only a decision-relevant continuity delta to the appropriate local layer | `handoff-preparation.md` |
| [project-onboarding](../skills/project-onboarding/SKILL.md) | Connect an existing repository and, when requested, seed genuine fresh continuity | `project-onboarding.md` |
| [team-deliberation](../skills/team-deliberation/SKILL.md) | Use independent views when they could change a consequential judgment | `team-deliberation.md` |

Project instructions retain authority and project selection. The local versionless
manifest, state, memory and rules remain the
project's durable cognition. Plugin skills own reusable workflow prose; tool
descriptors own capability/continuation contracts. Skills contain no async
watch/delegate sequencing rules. A skill's activation does not assign a role.

Principal Methods are retired. Local route wrappers are deleted, and continuity
manifests and initialization seeds reject the `methods` field even when empty or
null. Canonical reusable procedures live only in `skills/`; no forwarding stubs
or replacement manifest routes are provided. Project-specific decisions, causes
and rules stay with their local owners. This source retirement does not update
installed Skill texts or certify automatic trigger reliability.

## Attachment and discovery diagnostics

The preparation handoff supplies these four uniquely named copies in
`Creator-attachments/`. Preserve each canonical file's complete bytes, `name`
and `description` frontmatter. Rename only private attachment copies, never the
canonical Skill folders or files. A source URL does not prove that its body was
imported. If attachment names still collide, supply four complete, individually
labeled texts and confirm that each arrived without truncation. These are inputs,
not evidence of native installation; do not include private cognition or secrets.

Check **four complete installed native Skill bodies** and an actual
**`bridge_health()` result** separately in the intended ordinary Web Project Chat.
Health alone proves no Skill discovery; installed procedures alone prove no MCP
connectivity. A shortened per-turn listing or four-name summary is insufficient:
explicitly discover the bodies and compare them with the canonical inputs.
If tools work but Skills are missing, retain the working App/Tunnel and diagnose
native packaging or workspace permissions. Do not recreate credentials or prompt
tasks to force discovery. Record **tools working; Skills unverified**, adding
Core only if its instructions were separately checked. Work/Codex acceptance
does not establish ordinary Web availability or automatic Skill triggering.

## Public package configuration

[plugin.json](../plugin.json) points `extensions.com.openai.apps` to
[root .app.json](../.app.json). The sole alias `bridge` has `required: true` and
`asdk_app_REPLACE_WITH_OWN_APP_ID`, an explicitly nonfunctional placeholder.
[.app.example.json](../.app.example.json) provides the same reference shape.

For optional local packaging, the
[personal package guide](PERSONAL-PLUGIN-INSTALL.md#b-advanced-generate-and-install-a-local-marketplace)
uses [prepare-personal-plugin.py](../scripts/prepare-personal-plugin.py) to
copy this public manifest, its existing LICENSE and all four Skill texts into
a separate eight-file marketplace. The generator never reads the source App
binding or installs a host plugin. Only a verified native App reference is
accepted (`asdk_app_`, `connector_` or `templated_apps_`); browser
`plugin_asdk_app...` identifiers are not converted. Root placeholders stay here.
Use your own registered App ID in an independent configuration. This package
adds no endpoint, credential, runtime skill handler or marketplace configuration.

The source bundle and tests establish file layout and mapping shape. They do not
establish acceptance by a plugin distribution service, a working App connection,
installed skill discovery, automatic trigger reliability or fresh-chat usefulness.
Consult the host's current packaging requirements separately before installation
or distribution. No installation or publishing action follows from source tests.

Skills remain separate from project-local cognition. This public package includes
no actual project `.principal/` directory. Installation does not onboard projects,
start services, launch Agents or grant task authority. See
[Getting started](GETTING-STARTED.md) for the single first-use path.
