# MakerMedic

Evidence-based diagnostics for Linux AI, robotics, and maker environments.

AI and robotics failures cross layers: a physical device must be visible to the
operating system, its driver must work, a runtime must expose it, and the
application must use it correctly. A downstream error often hides the earliest
useful cause. MakerMedic collects bounded evidence, evaluates deterministic
rules, models prerequisites, blocks invalid downstream conclusions, and surfaces
the smallest upstream finding supported by the evidence.

```console
$ makermedic lab run gpu-driver-unavailable
Scenario: gpu-driver-unavailable
Diagnostic contract
  gpu.nvidia.driver  FAIL  PASS
  gpu.nvidia.nvml  BLOCKED  PASS
  gpu.pytorch.cuda_visibility  BLOCKED  PASS
Root findings
  gpu.nvidia.driver  FAILURE  PASS
RESULT: PASS
```

The example is a controlled simulated scenario: it validates MakerMedic without
changing a GPU or requiring NVIDIA hardware.

## Why MakerMedic

- Typed evidence distinguishes unavailable data from false or zero values.
- Pure rules return deterministic `PASS`, `WARN`, `FAIL`, `UNKNOWN`, or
  `BLOCKED` results.
- An explicit dependency graph prevents one upstream problem from becoming many
  misleading downstream failures.
- Root-cause analysis separates failures, missing capabilities, optional
  absence, uncertainty, and supporting observations.
- Snapshots and two-dimensional comparison verify what changed after a manual
  repair.
- Support bundles export only explicitly allowlisted diagnostic evidence.
- A controlled validation lab proves contracts against simulated faults and one
  temporary loopback service.

## What it diagnoses

MakerMedic currently covers seven domains:

| Domain | Examples |
| --- | --- |
| System | Linux support, available memory, root-disk capacity |
| Python | Version, virtual environment, pip coherence, package metadata |
| GPU | NVIDIA PCI visibility, driver, NVML, PyTorch, CUDA, allocation/compute |
| Camera | Device presence, permissions, V4L2, busy state, OpenCV open/read |
| USB | Linux sysfs discovery and optional `lsusb` cross-check |
| Serial | Device presence, permissions, group context, busy/open state |
| Service | Loopback DNS, TCP, HTTP health, and local listener state |

See [Diagnostic domains](docs/diagnostics.md) for observed data, active
operations, and limitations.

## Quick start

Python 3.12 or newer is required. From a local source checkout:

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
makermedic --version
makermedic diagnose --category system
```

No public repository URL is assumed here. Development setup is documented in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Common workflows

Run all registered diagnostics or one category:

```console
makermedic diagnose
makermedic diagnose --category gpu
makermedic diagnose --category camera --json
makermedic diagnose --package pydantic
makermedic diagnose --category service --url http://localhost:8000/health
```

Service diagnostics accept only explicit loopback HTTP/HTTPS URLs. Serial port
opening remains disabled unless `--serial-open-test` is supplied with the serial
category.

Expected exit codes are `0` for a completed run without `FAIL`, `1` when at
least one diagnostic fails, and `2` for usage or configuration errors. `WARN`,
`UNKNOWN`, and `BLOCKED` do not independently produce exit code 1.

## How it works

```text
Probe -> Evidence -> Rule -> Dependency Graph -> Diagnostic Run
      -> Root-Cause Analysis -> Snapshot / Verification / Support Bundle
```

Probes observe; rules interpret. Rules do not access hardware, execute commands,
or perform network requests. The graph orders rules and emits `BLOCKED` results
when a prerequisite is not satisfied. The analyzer then identifies directly
observed upstream findings and their downstream impact.

See [Architecture](docs/architecture.md) for the Mermaid diagram and component
boundaries.

## Before/after verification

Save a baseline, make a manual change, then compare a later run:

```console
makermedic diagnose --category gpu --save before.json
# Make and review a change outside MakerMedic.
makermedic diagnose --category gpu --save after.json
makermedic compare before.json after.json
makermedic verify before.json after.json
```

Snapshots deliberately omit evidence values. Comparison treats availability and
outcome separately: for example, `BLOCKED -> FAIL` is an unblocked but now
conclusive check, not a resolution. Persistent pre-existing failures do not make
verification exit 1; new or regressed failures do.

## Privacy-safe support bundles

Preview before exporting:

```console
makermedic bundle --category gpu --preview
makermedic bundle --category gpu --output makermedic-gpu-support.zip
makermedic bundle --snapshot before.json --output snapshot-support.zip
```

Preview and export consume the same validated plan. ZIP member names are static,
writes are atomic, and existing files are refused unless `--force` is explicit.
Evidence uses an exact key/nested-field allowlist; unknown fields are omitted.
Snapshot bundles contain diagnostic state but no evidence values. MakerMedic
does not upload bundles or execute recommendations.

See [Safety and privacy](docs/safety-and-privacy.md) before sharing a bundle.

## Diagnostic validation lab

The lab uses controlled evidence with production rules, graph execution, and
root-cause analysis:

```console
makermedic lab list
makermedic lab show camera-permission-denied
makermedic lab run camera-permission-denied
makermedic lab run-all
```

The suite contains 39 meaningful scenarios across all seven domains. Most are
fully simulated. One temporary-local service scenario binds only an ephemeral
loopback port and verifies cleanup. “39 scenarios passed” means the declared
contracts held for those controlled conditions; it is not a claim that every
possible real-world fault is covered.

Run the short deterministic portfolio demo with:

```console
./scripts/demo.sh
```

See the [demo guide](docs/demo.md) and [validation methodology](docs/validation.md).

## Safety and privacy

MakerMedic is diagnostic-first. It does not install packages or drivers, change
permissions/groups, kill processes, alter firewalls, restart services, flash
devices, reset GPUs, or automatically apply recommendations. Normal operation
does not require root.

Camera tests retain dimensions rather than pixels. USB serial numbers are not
collected. Service checks are loopback-only. Support bundles exclude environment
dumps, credentials, HTTP bodies/headers, image data, serial traffic, full process
command lines, and raw logs by enforced allowlist policy. There is no telemetry,
cloud service, or automatic upload.

The full design and its caveats are in [Safety and privacy](docs/safety-and-privacy.md).

## Development and CI

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
pytest
```

The GitHub Actions workflow applies those checks on Python 3.12 and 3.13. The
test suite is designed to run without real GPU, camera, USB, or serial hardware,
external network access, or root privileges. The validation suite includes
hundreds of deterministic tests and 39 controlled fault scenarios; exact
versioned results are recorded in [Validation](docs/validation.md).

## Real development observations

Development checks observed NVIDIA PCI hardware with unavailable driver
communication, and the downstream GPU chain was correctly blocked. They also
observed no local camera or supported serial device, verified a loopback service
across HTTP 500 to 200, scanned generated bundles for known fake secret values,
and exercised the temporary-local service lab. These observations are not
benchmarks or general hardware compatibility claims.

## Limitations

- MakerMedic is Linux-focused; non-Linux hosts receive limited diagnostics.
- It does not diagnose every driver, CUDA toolkit installation, camera format,
  USB protocol, serial application, firewall, or service-specific payload.
- HTTPS uses the system trust store; certificate validation is not disabled.
- Opening a camera or explicitly opted-in serial port can be observable to the
  device even though MakerMedic minimizes activity.
- Recommendations require user review and are never executed automatically.
- Validation scenarios establish controlled contracts, not diagnostic accuracy
  for all real-world faults.

## License

MakerMedic is available under the [MIT License](LICENSE).
