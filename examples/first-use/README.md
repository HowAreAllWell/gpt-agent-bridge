# First-use demo: judge a tiny invoice fix

This stdlib-only synthetic fixture shows task framing, bounded delegation and
evidence-based acceptance. It contains an **intentionally incorrect baseline**,
not a corrected implementation. Its isolated test failures are teaching evidence,
not Bridge product failures. No financial records, credentials or services are used.
This is a small parsing exercise, not a real invoice system or financial advice.

You can inspect and test it without Bridge, Herdr, a plugin or Project instructions.
For the optional connected exercise, first complete the single
[Getting started guide](../../docs/GETTING-STARTED.md).
This example supplies neither a Principal Core nor a host setup or continuity seed.
No Agent execution, repaired test pass or fresh-chat recovery follows from these files.

## Bootstrap your own disposable Git repository

Use Linux/WSL Bash, Git 2.28+ and Python 3.10+. Start at the root of **your public
Bridge checkout containing this example**, never the private Bridge development
checkout. The source checkout is read-only. Choose a fresh destination directly
under your Linux home; do not substitute either Bridge checkout as the destination.
Use a shell without custom `GIT_*` environment overrides. Run this yourself only
if you authorize creating and copying into that disposable repository:

```bash
(
  set -e
  source_root="$(pwd -P)"
  demo_root="$HOME/bridge-first-use-demo"  # Choose a fresh name if this exists.
  if [[ -e "$demo_root" || -L "$demo_root" ]]; then
    printf 'Destination exists; stop and choose a new path.\n' >&2
    exit 1
  fi
  for file in README.md invoice.py test_invoice.py; do
    [[ -f "$source_root/examples/first-use/$file" ]] || {
      printf 'Missing fixture file; check the public source checkout.\n' >&2
      exit 1
    }
  done
  umask 077
  mkdir -p -- "$demo_root"
  cp -n -- "$source_root/examples/first-use/README.md" \
    "$source_root/examples/first-use/invoice.py" \
    "$source_root/examples/first-use/test_invoice.py" "$demo_root/"
  git -C "$demo_root" init -b main --template=
  git -C "$demo_root" status --short
  if git -C "$demo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
    printf 'Unexpected existing HEAD; stop and inspect the destination.\n' >&2
    exit 1
  fi
  printf 'Baseline: main, three untracked fixture files, HEAD absent.\n'
)
```

The new root contains only `README.md`, `invoice.py`, `test_invoice.py` and its
own `.git/`; no child example directory or `__init__.py` is needed. `cp -n` avoids
overwriting files. Stop on any error; do not rerun into the partially created
destination. Privately record the actual status. An unborn `HEAD` is expected:
Bridge registration checks an existing non-bare Git root, not a first commit.
Do not register the Bridge source checkout as this demo project.

From the disposable root, run the same isolated tests with a different start path
(replace the path consistently if you chose another name):

```bash
(
  cd -- "$HOME/bridge-first-use-demo" || exit 1
  python3 -B -m unittest discover -s . -p 'test_*.py' -v
)
```

The shipped baseline has nine tests: **three pass and six intentionally fail**.
The nonzero test exit is expected; import/setup errors are not acceptance failures.
Keep the command and actual result, not a fabricated passing receipt.

A first commit is optional for registration, but provides a tracked baseline for
later diffs. **Only if you explicitly authorize staging and committing in this
disposable demo**, run the following yourself. It refuses an existing HEAD and
uses command-local pseudonyms, disables commit hooks/signing, and changes no
global or persistent identity configuration:

```bash
(
  set -e
  demo_root="$HOME/bridge-first-use-demo"
  [[ -d "$demo_root/.git" && ! -L "$demo_root/.git" ]] &&
  [[ "$(git -C "$demo_root" rev-parse --show-toplevel)" == "$(cd -- "$demo_root" && pwd -P)" ]] || {
    printf 'Not the isolated demo Git root; stop.\n' >&2
    exit 1
  }
  if git -C "$demo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
    printf 'HEAD already exists; this first-commit step does not apply.\n' >&2
    exit 1
  fi
  git -C "$demo_root" add -- README.md invoice.py test_invoice.py
  git -C "$demo_root" -c core.hooksPath=/dev/null -c commit.gpgSign=false \
    -c user.name='First-use demo' -c user.email='first-use@example.invalid' \
    commit -m 'Record intentionally failing fixture baseline'
  git -C "$demo_root" status --short
  git -C "$demo_root" rev-parse --verify HEAD
)
```

Record the resulting commit and status only if you actually ran that optional
step. Never run these mutations on the public or private Bridge checkout. Local
preparation grants no authority to register a route, initialize continuity, start
services or send Agent input. For later Bridge use, separately authorize the
disposable root/ref and arrange an existing eligible Herdr-managed Agent there.
Each Work needs its own file/test scope; explicitly authorize mandatory report
publication under its supplied contract. A report write is not permission for
project edits, tests, staging or commits. No push is part of this bootstrap.

## Optional demo Agent with Herdr

This is operator setup for this disposable exercise, not a required installation
step or Bridge delegation. Keep an eligible Agent already running in the demo
root and skip launching another. Otherwise, choose a compatible Agent and finish
its provider installation/sign-in privately; the
[official Codex CLI guide](https://learn.chatgpt.com/docs/codex/cli) is one example,
not a required provider. Do not paste login output or credentials into Chat.

Use the same selected Linux Herdr CLI in each launch/control shell; see
[Herdr compatibility](../../docs/HERDR-COMPATIBILITY.md). Open Herdr yourself in
the prepared demo root and keep that session open. The Bridge code checkout
holds its server/venv; this separate demo Git root holds the fixture and is the
Agent's cwd and later registration target. Never substitute a Bridge checkout.

Only if you authorize creating a workspace, run this in Linux/WSL Bash. The
[Herdr automation reference](https://herdr.dev/docs/agent-automation/) describes
the returned root-pane field. The command does not send an Agent task:

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

Inspect that actual pane: it must be an **idle interactive shell prompt**, with no
foreground program/editor/Agent, and its cwd must be the demo root. Choose an
unused Agent name. Only after separately authorizing launch, from the same
control shell retaining `demo_pane`, this Codex example starts the Agent:

```bash
herdr agent start demo --kind codex --pane "$demo_pane"
```

If launch fails or its outcome is uncertain, observe the session before another
action; do not relaunch blindly or prompt it to force readiness. Verify the
intended Agent through read-only Herdr observations and fresh Bridge `context`.
Use its actual `agent_ref`; the Herdr name/pane is not a Bridge handle to invent.
Registration, Chat binding and Agent input remain separately authorized actions.

## Acceptance contract

The public function is `total_cents(amounts) -> int` in [invoice.py](invoice.py).
It accepts an iterable of individual amount strings and returns exact integer cents.
The amount syntax is deliberately strict:

- ASCII `0` or a nonzero digit followed by ASCII digits, optionally followed by a
  decimal point and one or two ASCII fractional digits: `0`, `2`, `12.3`, `0.29`.
- No signs, whitespace, leading zeros such as `01`, exponents, commas, Unicode
  digits, missing integer/fractional parts, or more than two fractional digits.
- Each invalid value, including `None`, an empty string, numbers and booleans,
  must raise `ValueError`. Do not silently supply zero or return a partial total.
- No float conversion, rounding or truncation of valid amounts. Preserve every cent,
  including the large case below. Empty input totals zero; input lists stay unchanged.
- Keep the function pure, keep its signature, and use only the Python standard library.
  No file/network access or new dependencies. Passing tests alone does not prove purity.

These independently specified examples are acceptance evidence:

| Input | Required outcome |
| --- | --- |
| `[]` | `0` |
| `["0.10", "0.20"]` | `30` |
| `["0.29", "1.15"]` | `144`, with neither cent lost |
| `["90071992547409.93"]` | `9007199254740993` |
| `["1.00", None, "2.00"]` | `ValueError`, rather than an apparently valid total |
| `["1.005"]` or `["1e2"]` | `ValueError`, rather than rounding or accepting a different format |

[test_invoice.py](test_invoice.py) has nine acceptance tests with fixed expected
values and rejection cases. Preserve them during implementation; do not weaken
the contract to turn the suite green. They exercise examples, not every possible input.

## Phase 1: read-only diagnosis before any Agent input

A suitable first request is:

> Read only. Explain whether this fixture meets its acceptance contract. Inspect
> the original implementation and tests, cite the relevant lines, and distinguish
> a predicted failure from a test result actually observed. Do not patch files or
> send Agent input.

The Principal should read this README, the original `invoice.py` and
`test_invoice.py` directly through available read-only evidence tools. Record
the source lines and file identity/hash when available. Do not substitute an
Agent report or screenshot for original-file inspection. An original-file resource
can supplement text evidence if supported; preparation alone does not prove receipt.
The precision and missing-row examples give the Principal criteria independent
of an implementer's success claim. This phase authorizes no patch or delegation.

## Isolated local test command

With Python 3.10+ installed, a user may run this from the public source checkout
root; use the `-s .` command above in the copied disposable root:

```sh
python3 -B -m unittest discover -s examples/first-use -p 'test_*.py' -v
```

Use `python` instead if that is your Python 3.10+ executable. `-B` avoids creating
bytecode caches. Discovery treats the hyphenated directory as a filesystem start
directory and makes its sibling `invoice.py` importable; it is not a dotted module
name. No venv, pip installation or Bridge runtime is needed.

The shipped baseline should return a nonzero exit and acceptance failures. Keep
the actual command, interpreter version, exit status and failures as the baseline
receipt. An import error or missing interpreter is a setup problem, not a valid
baseline failure. This suite is outside `tests/`, so ordinary product discovery
with `unittest discover -s tests` does not collect it.

After an authorized repair, the user must run the same unchanged suite again.
An exit of zero and all nine tests passing would support a corrected result for
those cases. **No corrected pass is supplied or claimed here.** If it still fails,
report the failure. No alternate passing implementation or automatic fix is bundled.

## Optional read-only Agent review

After [Getting started step 10](../../docs/GETTING-STARTED.md#10-begin-daily-use-with-a-bounded-read-only-check),
you may authorize exactly one read-only assignment to an Agent observed in fresh
context. State the exact selected files and prohibit edits, commands/tests and
Git actions; authorize only its mandatory report publication outside the checkout.
Enable the project and exact Chat recipient before dispatch. Keep the actual
dispatch receipt/Work ref privately. A refusal or unknown delivery is not a reason
to resend the assignment.

For the classified Work, read the complete `work_report`, following all pages
with the full SHA pin, then compare its claims with the original source. Missing
reports or attention diagnostics remain explicit gaps, not success. Record bounded
dispatch, report availability, source review, preserved scope and actual reminder/
host continuation as separate observations. This review proves no implemented fix
or executed tests. Optional attachment preparation likewise does not prove that
the host imported the original file; check its original size/hash if exercised.

## Phase 2: optional implementation and separate review

Proceed only after the user explicitly authorizes implementation. Use an already
configured project and actual discovered Agent handles; this fixture does not
create or launch Agents. In the disposable Git root, narrow the task to changing
only `invoice.py` against the contract; do not patch either Bridge checkout.
Preserve this README and the acceptance tests. No staging,
commit, push, service action or other project changes are part of this exercise.

Agent A may implement the repair under that scope. After its change is available,
Agent B may review it read-only against the original criteria and actual source,
without editing. This is a later review stage, not a simultaneous dependent task.
If only one Agent is available, use it for implementation and let the Principal
perform source review; label any same-Agent re-review honestly. Two Agents are
optional and their agreement is not independent proof of correctness.

The Principal should inspect the actual diff and original resulting files, check
the invalid-row and precision cases, and distinguish its source reasoning from
reported test execution. Bridge evidence tools do not supply a generic shell-test
execution endpoint. A user-run test receipt is stronger runtime evidence than
an unsupported report claim. Source review still matters if all tests pass.

## Truth rubric

| Evidence | Claim it supports | Claim it does not support |
| --- | --- | --- |
| Direct original-file read | What those observed bytes/lines show | A test was run, or files cannot change afterward |
| Baseline command with acceptance failures | The shipped defect was exercised on that interpreter | A product regression or successful model repair |
| Agent A's report | A reported implementation and its claims | Verified code, genuine test execution or task success |
| Agent B's review | A second stated assessment and any cited counterexample | Correctness by consensus or guaranteed reviewer independence |
| User reruns unchanged nine-test suite after repair | Those cases pass for the inspected version on that interpreter | All inputs, every environment or security properties are proven |
| Principal reads actual resulting source/diff | Independently observed implementation evidence and reasoning | Principal personally executed tests through Bridge |
| Fresh-chat routed-state read, if configured | The recorded decision/boundary was recovered | Restored active Work, automatic recovery or universal host support |

Record source identity, exact test receipts, disagreements and remaining limits.
If source and reports disagree, preserve the contradiction and seek discriminating
evidence. Do not manufacture a passing output, a review disagreement or a timing claim.
No benchmark or superiority over a single Agent is implied by this toy task.

## Optional fresh-chat continuity

Only if the user already configured Project instructions and project-local continuity
and authorizes a handoff, record the accepted or unresolved decision through the
existing workflow. A fresh chat can then recover that decision and its boundaries
through the configured routed reads. Do not initialize continuity merely to run
this fixture. This example reads or writes no `.principal/` files and supplies no
private configuration. Disclose any setup or cuts in a recorded demonstration;
do not present a three-minute walkthrough as guaranteed installation or runtime.
For an actual fresh-chat check, the successor must distinguish review from
implementation, recover the reason for the next action and respect its authority
boundary. Record whether that was observed; file readback alone does not pass it.
