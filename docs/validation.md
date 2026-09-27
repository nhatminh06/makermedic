# Validation

MakerMedic combines offline unit/contract tests with controlled diagnostic
scenarios. As verified for version 0.1.0 on 2026-09-27:

- 486 automated tests passed.
- 39 meaningful lab scenarios ran.
- 39 scenarios passed and 0 failed.
- Ruff formatting and lint checks passed.

The final test count includes the Phase 12 version-command regression test.

## What is tested

The deterministic suite covers domain invariants, evidence availability,
collection error boundaries, rule behavior, dependency blocking, graph
validation, root findings, snapshots, comparison transitions, verification,
privacy allowlists, atomic ZIP writing, CLI behavior, and lab mutation
sensitivity. Hardware behavior is represented through fake boundaries so normal
tests require no NVIDIA GPU, camera, USB board, or serial device.

Every shipped lab scenario passes evidence through the production rules,
dependency graph, engine, and root-cause analyzer. The matcher validates stable
diagnostic IDs, statuses, dependency states, origins, blockers, root-finding
kinds, and expected diagnostic exit semantics. It also rejects unlisted severe
results and actionable findings.

| Category | Scenarios |
| --- | ---: |
| system | 5 |
| Python | 5 |
| GPU | 8 |
| camera | 7 |
| USB | 2 |
| serial | 5 |
| service | 7 |
| **Total** | **39** |

One service scenario uses a real ephemeral loopback HTTP server and production
`ServiceProbe`; cleanup and port release are tested. Tests and demo commands do
not require external network access or privileged host changes.

“39 scenarios passed” means MakerMedic produced the expected diagnostic
contract for 39 controlled conditions. It does not prove that MakerMedic can
diagnose every possible real-world hardware or software fault.

## Development observations

Development validation also observed NVIDIA hardware through Linux PCI while
driver communication was unavailable, with dependent GPU checks correctly
blocked. Other checks observed no local camera or supported serial device. A
loopback service was verified across a 500-to-200 transition, generated bundles
were scanned for fake secret fixtures, and the temporary-local lab server was
cleaned up. These are observations, not benchmarks or compatibility guarantees.
