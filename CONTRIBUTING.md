# Contributing

## Development setup

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
pytest
```

## Architecture rules

- Probe is not diagnosis. Probes collect typed facts; deterministic rules
  interpret them.
- Keep diagnostic IDs stable because snapshots, comparisons, bundles, and lab
  contracts depend on them.
- Preserve `PASS`, `WARN`, `FAIL`, `UNKNOWN`, and `BLOCKED` semantics. Missing
  data is not false, and optional hardware absence is not automatically failure.
- Never add destructive diagnostic behavior or automatic remediation.
- Treat diagnostic evidence as sensitive. New support-bundle fields require an
  explicit allowlist decision and privacy tests.

## Adding or changing diagnostics

Add a narrowly scoped probe only when new observation is necessary, then add a
pure rule and register both explicitly in the composition root. Declare graph
dependencies and test healthy, failed, unavailable, and blocked states with fake
evidence. Hardware-specific integration coverage must also have deterministic
offline coverage suitable for CI.

For a lab scenario, start from its domain's healthy fixture, override the
minimum evidence, declare stable enum/ID expectations, and add it to the explicit
scenario registry. Do not store shell commands or arbitrary executable code in
scenario definitions.

Run the complete checks before proposing a change. Do not update exact measured
counts in documentation until the complete suite and `makermedic lab run-all`
have been rerun.
