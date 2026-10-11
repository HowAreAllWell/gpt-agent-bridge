# Native execution retirement

Public `run` is removed from SOURCE, with no hidden alias or arbitrary-command replacement.
Its exclusive native_execution module and tests are removed after consumer inspection.
Source inspection and tests establish local contracts only; runtime deployment and
host acceptance require separate evidence.
The [tool reference](../README.md#tool-reference) lists retained capabilities;
[observation contracts](OBSERVATION-TOOLS.md) own exact evidence/version mechanics.

Distinct Agent resources may hold concurrent in-flight Work in one shared checkout;
a nonterminal Work or unconsumed handoff for the same Agent handle/resource still
rejects a duplicate prompt. Terminal
settlement does not prove manual/detached writers stopped. Shared gates and dispatch
identity checks remain; see [Lifecycle](LIFECYCLE-RESTART-CONTRACT.md).

Fixed Git observations retain bounded byte capture, timeout and joined cancellation cleanup.
They expose no caller argv. Spawn/nonzero failures and incomplete captures are not clean
observations. Inherited pipes, TERM-resistant descendants, repeated cancellation and escaped
pipe holders are covered by tests/test_fixed_git_lifecycle.py. Escaped processes and
nonpreemptible OS operations prevent an unconditional end-to-end bound.
See [observations](OBSERVATION-TOOLS.md) for query limits and unsupported configurations.

Shared admission regressions live in tests/test_checkout_admission.py; actual MCP retirement
and retained evidence calls are covered by tests/test_run_retirement.py.
Source tests do not certify runtime acceptance; validate the configured service and
client separately. This public source does not include private execution receipts.
