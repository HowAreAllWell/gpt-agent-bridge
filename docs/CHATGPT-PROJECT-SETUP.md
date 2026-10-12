# Set up the complete product in a ChatGPT Web Project

This guide assembles ChatGPT Web, user-installed Principal Core instructions,
Bridge, Herdr-managed local Agents, and the four reusable Skill procedures. Start
here for the full workflow; [Developer quickstart](QUICKSTART.md) supplies the
local installation and foreground-server steps. Then use the
[first-use walkthrough](FIRST-USE-WALKTHROUGH.md) to check the assembled stack.

Reviewed against source and official documentation on **2026-10-11**. Existing
Windows/WSL operation and the maintainer's Plus/Pro experience do not establish a
clean WSL installation or acceptance on a fresh account. There is no one-click
installer or universal Plus/Pro capability guarantee in this guide.

## 1. Check prerequisites before installing anything

You need each of these independently:

| Layer | What you supply | Check before proceeding |
| --- | --- | --- |
| ChatGPT Web Project | An account/workspace that can create a Project and save Project Instructions | Both controls are available in your actual account |
| Principal Core | The [public Core template](../templates/WEB-PRINCIPAL-CORE.md), copied by you into Project Instructions | Saved instructions contain the Core, rather than only a file link |
| Linux execution environment | Git, Python 3.10+ with venv support, and the direct dependencies in the Quickstart | You can follow the Linux Bash steps in that environment |
| Local Agent substrate | Linux Herdr and compatible Agents you have already launched in the intended Git checkout | Herdr can observe the intended sessions; provider/model quota is available |
| Bridge transport | A local Bridge plus your own OpenAI Secure MCP Tunnel connection (recommended for private first use) or another verified HTTPS MCP relay | Initialized local MCP health succeeds, then a Web call succeeds separately |
| Tools and Skills | Your own registered MCP/App connection and an eligible installation surface for the Bridge plugin package | The target Project Chat sees tools and can explicitly discover all four Skills |
| Optional continuity | A separately authorized project-local rules/state/memory setup | Actual routed files can be read; no borrowed project cognition is copied |

On Windows, use [Windows + WSL2 onboarding](WINDOWS-WSL.md). Check the distribution
is WSL2 with `wsl --list --verbose` in **PowerShell**; follow the guide's Linux
installation steps in **Ubuntu Bash**, including installing Linux Herdr inside
WSL. Keep the checkout in the distro's Linux filesystem, rather than `/mnt/c`.
WSL1 is not a tested path here. Bridge uses its Linux codepath; native Windows
and native macOS operation are unsupported/unverified. Bare-metal Linux fresh
installation has not been separately field-tested by these docs.

The subscription supplies ChatGPT's reasoning; this workflow does not require
an OpenAI API-driven Principal. Agent providers and any relay still have their
own authentication, access conditions, and possible costs. A compatible CLI
installation alone does not establish a usable Herdr-managed session. Bridge
does not install or start an Agent when you delegate.

**Checkpoint:** choose the intended ChatGPT Project and one local Git checkout.
If a required account control, Agent session, or transport is unavailable, record
that layer as blocked. Do not substitute a different UI or claim full setup.

## 2. Create the Web Project and install Core as instructions

In the official ChatGPT website, create or open the Project intended for this
repository. Use that Project's menu/settings to locate its Project Instructions
control; labels may differ with the UI rollout. Do not paste the Core only into
account-wide personalization or an ordinary message.

Review the [Core template](../templates/WEB-PRINCIPAL-CORE.md), then copy its
entire contents into Project Instructions. Preserve relevant existing project
rules and resolve conflicts before saving. If the UI rejects the text or truncates it, stop and report the
limit rather than silently installing an incomplete Core. Reopen the control to
check the saved text, and start a new **Chat inside this Project**.

The Core defines the Principal's working responsibilities. It does not connect
an MCP server, register a repository, initialize continuity, install Skills, or
authorize any task. Uploading the template as a Project source is not the same
as installing its instructions. The [Web Principal overview](WEB-PRINCIPAL.md)
explains the product layers.

[OpenAI's Projects documentation](https://learn.chatgpt.com/docs/projects)
describes instructions shared by a Project's chats and distinguishes Project
context from access to a local folder. A similarly named ChatGPT Project and
local repository do not establish a Bridge binding.

**Checkpoint:** a new Project Chat can state its Principal responsibilities and
current authority limits. This checks instruction use, not tool connectivity or
the quality of future judgments.

## 3. Prepare the local stack, then connect your own HTTPS MCP

### Prepare a demo Agent with Herdr

For the invoice exercise, do this **before Agent launch or project_register**:

1. Clone/install the Bridge source using [Quickstart Step 2](QUICKSTART.md#2-clone-and-install-direct-dependencies).
   From that code checkout, follow the example's
   [disposable Git bootstrap](../examples/first-use/README.md#bootstrap-your-own-disposable-git-repository).
   It copies only the three fixture files into a new user-owned Git root.
   An initial demo commit is optional, not required for registration; its
   separate authorization and synthetic attribution are in the example.
2. Keep **two distinct roots**: the Bridge code checkout holds src/gpt_agent_bridge/server.py/.venv;
   the disposable demo root holds invoice.py/test_invoice.py and its own .git.
   Never use either Bridge checkout as the demo destination. Later registration
   must name the actual demo root, not the Bridge code root.
3. Choose an already supported Agent, or use Codex as this concrete example.
   Follow the [official Codex CLI installation and sign-in guide](https://learn.chatgpt.com/docs/codex/cli)
   inside Linux/WSL. Verify the download source before installing and authenticate
   privately with an available method. Do not paste login output or credentials
   into Chat. Confirm `command -v codex` and `codex --version`; provider access
   and quota still apply. Other compatible Herdr Agents are valid alternatives.
4. Check or select Linux Herdr **v0.9.0** using the
   [Herdr compatibility guide](HERDR-COMPATIBILITY.md); reuse a usable existing
   install. Apply the same CLI selection in each launch/control shell below.
   In a separate Ubuntu/Linux terminal, enter the **prepared demo root** and
   start `herdr` as described in
   its [quick start](https://herdr.dev/docs/quick-start/). Keep that session open.
5. In another shell in the same distro/session, create the demo workspace with
   its actual cwd. The [official automation guide](https://herdr.dev/docs/agent-automation/)
   defines the returned JSON field; this example uses Python rather than jq:

These are **operator setup actions**, not Bridge delegation. Run them only when
you choose to create that workspace and start an Agent. If you already have an
eligible Agent in the demo root, keep it and skip this launch example.

```bash
demo_root="$HOME/bridge-first-use-demo"  # Use the exact root you prepared.
demo_root="$(cd -- "$demo_root" && pwd -P)" || exit 1
[[ -d "$demo_root/.git" && ! -L "$demo_root/.git" ]] || {
  printf 'Prepare the independent demo Git root first.\n' >&2
  exit 1
}
workspace_json="$(herdr workspace create --cwd "$demo_root" --label bridge-first-use --no-focus)" || exit 1
demo_pane="$(printf '%s\n' "$workspace_json" | python3 -c 'import json, sys; value = json.load(sys.stdin)["result"]["root_pane"]["pane_id"]; assert isinstance(value, str) and value; print(value)')" || exit 1
printf 'Observed root shell pane: %s\n' "$demo_pane"
```

Inspect the new pane in Herdr. It must be at an **idle interactive shell prompt**,
with no foreground program/editor/Agent. Check its cwd is the intended demo root.
The variable above holds the actual `.result.root_pane.pane_id`, not an invented
pane. Choose an unused Agent name if `demo` is already taken. Only then, from the
same control shell retaining `demo_pane`, start Codex:

```bash
herdr agent start demo --kind codex --pane "$demo_pane"
```

If startup is blocked, fails or has an uncertain outcome, inspect the actual
session before any new action; do not relaunch blindly or prompt it to force
readiness. Launch sends no task from this guide. Quickstart's read-only snapshot
check must observe the intended Agent. Later Bridge `context` supplies its actual
`agent_ref`; the Herdr name/pane is not a Bridge handle to invent.

### Run Bridge from its code root and choose the connection

Return to the **Bridge code checkout**, where its .venv and src/gpt_agent_bridge/server.py live, for
the foreground server and both client-shell examples. The demo root has no Bridge
server or venv. Set BRIDGE_WORKSPACE as Quickstart specifies for the Bridge run;
it does not register the separate demo or silently select its project_ref.

Follow [Quickstart](QUICKSTART.md) for Herdr, dependencies and the foreground
Bridge. Windows readers first follow the WSL2 guide. **Choose the connection
before Quickstart Step 4 consumes its token handoff:** for private first use,
prepare the [Secure MCP Tunnel guide](OPENAI-SECURE-MCP-TUNNEL.md) and use its
[combined Step 4](OPENAI-SECURE-MCP-TUNNEL.md#combined-step-4) in place of the
standalone local check. It checks initialized local MCP health, then starts the
client within the same token-holding subshell. Systemd adoption is optional
later; enabling systemd does not keep WSL alive by itself.

Keep configuration private. Do not copy tokens, endpoint capability URLs, App
identifiers, terminal snapshots, or private host details into these docs, public
reports, screenshots, or Core instructions. The Quickstart owns secret handling;
its token block is deliberately not repeated here.

A successful **local** `bridge_health()` checks the responding server and
observed Herdr connection. It does not prove that ChatGPT can reach your relay,
that tools are visible, or that the bound schema is current. For private local
first use, the combined workflow requires your own tunnel and runtime credential,
and runs its Linux client next to Bridge after local health succeeds. Then select
that tunnel when creating a ChatGPT MCP connection. The
control-plane credential authenticates the tunnel; it is not a separately
API-billed model-reasoning controller. Protect the Bridge path token, tunnel
runtime credential and diagnostics. The local health-check token handoff must remain valid
through tunnel setup; do not generate a new token for an existing server.

An independently managed **public HTTPS relay** is an alternative, not the
recommended private first-use route. It must preserve the full MCP path and
Streamable HTTP/SSE behavior with verified Host/Origin and authentication.
Do not disable checks merely to make a copied deployment configuration work.
Where your account exposes the relevant controls, use the ChatGPT Apps/Plugins
custom-MCP connection flow, review the permissions and install/enable the
resulting connection. Choose **Tunnel** when using Secure MCP Tunnel, rather
than pasting the local `127.0.0.1` URL as a public endpoint. Use the current
interface and the [official plugin Quickstart](https://developers.openai.com/plugins/quickstart);
do not copy its example server's unauthenticated setting onto your Bridge.

That official tutorial demonstrates **Work**. This product's target here is a
**Web Chat in your Project**: enable/select the connection there using the
controls actually available, then ask for a read-only `bridge_health()` call.
Confirm an actual tool result, not a prose assurance that the tool exists. If
the plugin works in Work but not this Project Chat, record the surface mismatch;
it has not passed this guide's target-surface checkpoint.

**Checkpoint:** local MCP health and Project Chat MCP health are two separately
observed results. Neither authorizes project registration or Agent input.

## 4. Install and verify the four procedures when eligible

### Recommended: Web Chat Plugin Creator

Already seeing Bridge tools but no Skills? Follow
[Install Bridge Skills in ChatGPT Web](INSTALL-BRIDGE-SKILLS.md) first.
When available and permitted, edit the working plugin or create a private
combined plugin through Web Chat Plugin Creator. Tell Creator which connected,
allowed Bridge App to use; preserve it when editing, and use an App selector
if offered. Supply the four uniquely named attachment copies described in the
guide, preserving the canonical bytes and metadata. Review Apps and all four
Skill bodies, install through the supported UI, then verify discovery and
`bridge_health()` separately in a new target Web Project Chat. Do not rebuild
the tunnel or paste browser IDs to add procedures.

If creator/editing or native discovery is unavailable, record the checked
tools-only/Core + tools outcome with Skills unverified.

### Advanced Work/Codex local package route

Prefer the Web route above. If you have a verified native App ID and an
eligible local marketplace client, use
[the personal package guide](PERSONAL-PLUGIN-INSTALL.md#b-advanced-generate-and-install-a-local-marketplace)
and [reviewed generator](../scripts/prepare-personal-plugin.py). Its default
source is its licensed public checkout. It copies the manifest, existing LICENSE
and four Skills unchanged, then prepares eight files in a new private directory
outside the source. Generation does not install a plugin or change host settings.

A native App reference uses `asdk_app_`, `connector_` or `templated_apps_`;
a `plugin_asdk_app...` browser identifier is not an input for raw App mapping.
Let the eligible host resolve your own App. Do not convert prefixes, use a
placeholder, or send IDs as CLI arguments. The guide owns exact validation,
private input, no-clobber publication and optional explicit installation steps.
Local Work/Codex acceptance still needs a separate target Web Project Chat check.
Keep the public root placeholder unchanged.

| Procedure | Use it for |
| --- | --- |
| `project-onboarding` | Authorized registration and, separately, fresh continuity |
| `project-resume` | Recovering an existing routed project judgment in a later chat |
| `handoff-preparation` | A decision-relevant continuity delta before a handoff |
| `team-deliberation` | Independent views that may change a consequential judgment |

Do not infer all four from a shortened per-turn listing. Explicit discovery is
a check, not a guarantee of automatic selection or trigger reliability.
Installing or invoking a Skill does not expand task authority. If your surface
cannot install/discover the package, record **Core + tools working; Skills
unverified** only if those two layers were actually checked. Work/Codex package
acceptance does not prove ordinary Web Project Chat availability.
Reading a procedure manually can help diagnose the gap, but is not installed
Skill acceptance.

Current [public submission documentation](https://developers.openai.com/plugins/deploy/submission)
rejects ZIPs with app references; this source bundle's local/workspace mapping
does not establish universal public-directory distribution. A personal/local
marketplace is an eligible testing path, not a public listing or automatic
update guarantee. Do not publish that package or its connection ID implicitly.

## 5. Authorize registration and add the returned Project Binding

Choose an explicit non-reserved `project_ref`, such as `first-use`, and the
already prepared demo Git root as an absolute path inside Linux/WSL (or a
separately selected existing project root). A first commit is not required.
Check this is the Agent's target root, distinct from the Bridge code checkout.
The ref is a Bridge
route, not your ChatGPT Project's title. Values below are examples to replace
privately; they are not existing registrations.

Send this only when you intend to authorize the registry write:

```text
I authorize project_register for project_ref="first-use" and the existing Git
checkout at <ABSOLUTE_LINUX_GIT_ROOT>. Register that route only. Do not initialize
continuity, start or prompt Agents, edit project files, or perform Git mutations.
Show the registration result and its Project Binding amendment.
```

The model should use `project_register(project_ref, path)` with your actual
values. Check the returned root/ref and `persistence`/`registration` observations.
Registration creates no repository, ChatGPT Project, or continuity files and
grants no task authority. An uncertain publication or lost response requires
observation, not blind re-registration; `bridge_overview` can report registration
state without granting a new action.

After a confirmed matching result, **you** apply its
`project_instructions_snippet` as a Project Binding amendment alongside the
saved Core. Preserve other valid connected refs; it is not a replacement Core.
The returned shape names connected refs, for example:

```text
# Project Binding

Connected Bridge project refs:
- `project_ref="first-use"`
```

Save the amended Project Instructions and verify them in a new Project Chat.
Use an explicit `project_ref` for every project operation. The amendment does
not authenticate the ChatGPT Project identity or turn browsing into authorization.

**Checkpoint:** `context(project_ref="first-use")` resolves the intended checkout
and observed eligible Agent handles. It projects continuity pointers; it does
not read the state-file body. Continue with a bounded read-only repository
question in [First use](FIRST-USE-WALKTHROUGH.md) before authorizing a delegation.

## 6. Choose continuity separately, then test a fresh chat

You can read evidence and delegate without initializing cognition. For optional
fresh project-local continuity, first inspect the registration's onboarding
classification and [continuity contract](PROJECT-CONTINUITY.md). Separately
authorize `project_initialize(project_ref, seed)` in your own selected project.
Review a seed containing genuine existing rule paths, honest current
`state_content` and durable `memory_content`; meaningful
`project_rules_content` is optional. Use the current tool schema. Do not copy
another project's private cognition or invent prior decisions to fill a seed.

Initialization writes fresh routed continuity only when appropriate, leaves an
already canonical manifest untouched, and refuses an existing noncanonical
directory. A fresh setup is not `project-resume`, and refusal is not permission
to delete or repair another project's files. A lost response is not proof that
publication did not happen.

For an authorized handoff, read the actual routed state, memory and relevant
rules. Put the current judgment/next boundary in state and useful durable causes
in memory; these are separate publications. `current_state_update` needs the
revision of the state bytes actually read. On conflict, reread and reconcile;
on uncertain publication, observe before another write. Read back the resulting
bytes. State replacement does not archive displaced history or commit Git.

Start a new Chat in the same Web Project, verify Core/Binding and connection,
explicitly discover/use `project-resume` if installed, and recover the routed
judgment with fresh evidence. No init, Agent prompt, or repeated task is implied.
Work/Agent handles are process-local observations, not restart-stable identity.
Ask the successor to explain the next action and its limits before authorizing
new work. The walkthrough supplies a concrete acceptance exercise.

## Diagnose the layer that failed

| Symptom | Bounded next check |
| --- | --- |
| Project/Instructions control missing or text rejected | Check account/workspace policy and actual UI; do not claim a complete Core installation |
| Local MCP health fails | Follow Quickstart diagnostics for Bridge/Herdr; keep logs private |
| Local health succeeds but Web tools are absent | Check HTTPS/authentication, installed connection, target Chat surface and current schema |
| Tools work but Skills do not appear | Check package installation source and own mapping; explicit catalog discovery, not repeated task prompts |
| Registration is uncertain or conflicts with an existing route | Observe registration and ask the owner to reconcile; do not redirect the route |
| Context has no eligible Agent | Check the user-launched Herdr session, checkout, provider and quota; Bridge does not start one |
| Continuity is missing/noncanonical | Continue read-only orientation; initialize fresh only when separately authorized; preserve existing data |
| Report or continuation is unavailable | Inspect the actual receipt/diagnostic under the current task scope; do not assume success or resend an uncertain task |

Setup is complete only for the layers you actually observed. Record a private,
sanitized checklist: saved Core/Binding, local health, Project Chat tools, four
Skills, registered root/ref, first-use report/evidence, and optional fresh-chat
continuity. Do not label source checks, another account's experience, or a Work
test as fresh-account acceptance of this Project Chat workflow.
