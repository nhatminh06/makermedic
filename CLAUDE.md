# CLAUDE.md — MakerMedic

## Project

MakerMedic is an evidence-based diagnostic and troubleshooting toolkit for Linux AI, robotics, and makerspace development environments.

The project should eventually help answer questions such as:

- Why can PyTorch not use the GPU?
- Why is a camera detected by Linux but unavailable to OpenCV?
- Why is an Arduino visible over USB but its serial port inaccessible?
- Why does a local AI service fail to start?
- Which failure is the root cause and which failures are downstream symptoms?
- Did the user's attempted repair actually resolve the original problem?

MakerMedic is a diagnostic engineering project, not a chatbot.

---

## Core Philosophy

MakerMedic follows this pipeline:

    Probe
      ↓
    Evidence
      ↓
    Diagnostic Rule
      ↓
    Diagnostic Result
      ↓
    Recommendation
      ↓
    Verification

The separation between these stages is fundamental.

### Probes collect facts

A probe observes the environment.

Examples:

    torch.version.cuda = null
    /dev/video0 exists = true
    serial device owner = root
    TCP port 8000 reachable = false

A probe must not turn observations into diagnoses.

Bad:

    "Your PyTorch installation is broken."

Good:

    torch.version.cuda = null

Diagnostic rules are responsible for interpreting that evidence.

### Rules interpret facts

Diagnostic rules consume evidence and produce conclusions.

Rules must be deterministic.

Given the same evidence, a rule must produce the same result.

Rules must not directly:

- access hardware
- execute system inspection commands
- open cameras
- inspect USB devices
- perform network requests
- import hardware-specific libraries

Those operations belong in probes.

---

## Evidence-First Diagnostics

Every diagnosis should be explainable using concrete evidence.

Prefer:

    Diagnosis:
    CPU-only PyTorch build

    Evidence:
    - NVIDIA GPU detected
    - NVIDIA driver operational
    - NVML operational
    - PyTorch installed
    - torch.version.cuda is null

over:

    CUDA seems broken.

MakerMedic must never claim more than its evidence supports.

---

## Missing Data

Missing information is not equivalent to false or zero.

These states must remain distinguishable:

    GPU utilization = 0%

and:

    GPU utilization unavailable

Likewise:

    camera exists = false

is different from:

    camera existence could not be determined

Use typed states and nullable values.

Do not use magic strings such as:

    "N/A"
    "unknown"
    "error"

inside domain models.

---

## Diagnostic Statuses

The core system supports:

    PASS
    WARN
    FAIL
    UNKNOWN
    BLOCKED

### PASS

The condition was evaluated and is healthy.

### WARN

Something noteworthy exists but does not establish failure.

### FAIL

Evidence supports a diagnostic failure.

### UNKNOWN

There is insufficient evidence to determine the state.

### BLOCKED

The diagnostic cannot meaningfully execute because an upstream dependency failed.

Example:

    Camera detected        PASS
    Camera permissions     FAIL
    OpenCV capture         BLOCKED
    Model inference        BLOCKED

Do not convert every downstream consequence into another FAIL.

---

## Hardware Absence

Hardware absence is not automatically a failure.

For example:

    No NVIDIA GPU detected

may be completely normal.

Its status depends on the diagnostic being requested and its context.

Do not assume every machine should contain every supported device.

---

## Error Handling

Distinguish diagnostic conditions from implementation or collection errors.

Example:

    No camera connected

is normally evidence.

It is not inherently a Python exception.

By contrast, if a probe unexpectedly fails while parsing device metadata, that may be a collection error.

Expected probe failures should be represented explicitly without crashing unrelated diagnostics.

Unexpected programming errors must not be silently swallowed.

Never write:

    try:
        ...
    except Exception:
        pass

Do not hide programming defects to make diagnostics appear robust.

---

## Root Cause Direction

MakerMedic will eventually model dependency relationships.

The architecture must not prevent:

    root failure
        ↓
    blocked dependency
        ↓
    blocked dependency

from being represented later.

Do not implement the full dependency graph until its designated phase.

---

## Remediation Philosophy

MakerMedic is diagnostic-first.

Default behavior:

    observe
    diagnose
    explain
    recommend
    verify

Not:

    observe
    sudo modify system

Do not automatically:

- install packages
- uninstall packages
- change drivers
- modify kernel configuration
- modify device permissions
- change user groups
- kill processes
- modify firewall rules
- edit shell startup files
- execute privileged commands

unless a future phase explicitly introduces a narrowly scoped remediation feature.

Recommendations may display commands, but commands must be clearly presented for user review.

---

## Security

Treat diagnostic information as potentially sensitive.

Do not casually collect:

- passwords
- API keys
- access tokens
- SSH private keys
- browser data
- Wi-Fi credentials
- complete environment-variable dumps
- unrelated user files

Future support bundles must implement explicit privacy filtering.

Never introduce secret collection merely because it makes debugging easier.

---

## Shell Commands

When system commands become necessary in later phases:

- use argument arrays rather than shell interpolation
- avoid shell=True
- use reasonable timeouts
- capture stdout and stderr deliberately
- inspect return codes
- handle missing commands explicitly
- never execute user-provided strings as shell code

System commands are evidence sources, not business logic.

Parsing should remain separate from process execution where practical.

---

## Linux Focus

MakerMedic is primarily a Linux diagnostic tool.

Do not weaken Linux functionality merely to claim cross-platform support.

Platform-specific code should be isolated cleanly.

If functionality is unsupported on another OS, report that honestly.

Do not fake portability.

---

## Architecture

Prefer a small architecture around:

    core/
        domain models
        probe contracts
        diagnostic rule contracts
        evidence storage
        registry
        engine

    probes/
        environment observation

    diagnostics/
        evidence interpretation

    presentation/
        terminal rendering

Keep domain logic independent from CLI and Rich.

---

## Extensibility

Future domains include:

    System
    Python
    NVIDIA
    CUDA
    PyTorch
    Camera
    OpenCV
    USB
    Serial
    Arduino
    Processes
    Networking
    Local AI services
    ROS2

Adding one should generally mean adding probes and diagnostic rules.

It should not require rewriting the core engine.

Do not build a generic plugin framework merely because future extension is expected.

Simple explicit registration is preferred.

---

## Dependency Policy

Keep dependencies minimal.

A dependency must provide meaningful functionality that would otherwise require substantial or fragile reimplementation.

Do not add packages speculatively for future phases.

Add phase-specific dependencies only when that phase requires them.

Avoid dependency-heavy frameworks.

---

## Python

Target Python 3.12+.

Prefer:

- type hints
- enums for finite states
- dataclasses or Pydantic models where appropriate
- pathlib
- explicit interfaces
- small functions
- deterministic behavior

Avoid excessive metaprogramming.

---

## Pydantic

Pydantic may be used for domain models that benefit from:

- validation
- serialization
- stable schemas

Do not use Pydantic merely to wrap every internal object.

Use ordinary Python types where simpler.

---

## CLI

Typer is the preferred CLI framework.

Rich is the preferred terminal presentation library.

CLI code must remain thin.

The CLI should only:

    parse input
    invoke core functionality
    render results
    choose exit code

The CLI must not contain diagnostic logic.

---

## JSON Output

Machine-readable output is a first-class interface.

When --json is requested:

- produce valid JSON
- do not mix Rich formatting into stdout
- use stable field names
- represent unavailable values structurally
- preserve diagnostic status explicitly

This will later support:

- saved runs
- comparisons
- support bundles
- external tooling

---

## Exit Codes

Keep exit codes simple.

Expected convention:

    0 = diagnostic run completed without FAIL
    1 = one or more FAIL diagnostics
    2 = usage/configuration error

WARN alone should not produce exit code 1.

UNKNOWN and BLOCKED should not automatically become FAIL merely to affect the exit code.

If semantics change later, document and test them.

---

## Testing

Tests are required for every phase.

Core logic must be testable without:

- NVIDIA hardware
- CUDA
- cameras
- USB hardware
- Arduino
- root privileges
- network connectivity
- internet access

Use fake probes and deterministic evidence.

Hardware-specific integration tests added later must be separable from the normal offline test suite.

CI must never depend on the developer's machine configuration.

---

## Test Quality

Do not create meaningless tests merely to increase the test count.

Prioritize:

- domain invariants
- error boundaries
- serialization
- deterministic rule behavior
- missing-data behavior
- duplicate evidence handling
- filtering
- CLI semantics
- regression behavior

When reporting test counts, report actual executed counts.

Never invent coverage or test numbers.

---

## Timing

Do not use arbitrary sleep() calls in unit tests.

If future functionality depends on time, inject or abstract the clock where practical.

Tests should remain deterministic.

---

## Concurrency

Do not introduce:

- async
- threads
- multiprocessing
- background workers

unless a concrete future requirement demands them.

Most MakerMedic diagnostics should remain synchronous and understandable.

---

## Performance

MakerMedic is a diagnostic tool, not a high-throughput server.

Prioritize:

1. correctness
2. evidence quality
3. reproducibility
4. explainability
5. maintainability

before optimization.

Do not make unsupported performance claims.

---

## AI / LLM Policy

Do not add:

- LLM APIs
- chatbots
- RAG
- embeddings
- vector databases
- generative AI dependencies

to MakerMedic.

Root-cause analysis should be based on deterministic diagnostic rules and observable evidence.

This is intentional.

The project should demonstrate engineering and troubleshooting capability rather than outsourcing reasoning to an API.

---

## UI Policy

The CLI is the primary interface.

A TUI may be added in a later designated phase.

Do not add:

- React
- Next.js
- Electron
- web dashboards
- frontend frameworks

unless explicitly requested in a future phase.

---

## Scope Discipline

Implement only the requested phase.

Do not implement roadmap items early.

Current roadmap:

1. Core diagnostic engine
2. System and Python environment diagnostics
3. NVIDIA / CUDA / PyTorch diagnostics
4. Camera / OpenCV diagnostics
5. USB / serial diagnostics
6. Local services and networking
7. Diagnostic dependency graph
8. Root-cause analysis
9. Verification and run comparison
10. Privacy-safe support bundles
11. Fault-injection laboratory
12. TUI and final documentation

The roadmap may evolve, but phase boundaries should be respected.

---

## Avoid Overengineering

Do not introduce:

- microservices
- cloud infrastructure
- Kubernetes
- databases
- message queues
- event buses
- dependency injection frameworks
- generic plugin frameworks
- package-entry-point discovery
- unnecessary repository layers
- abstract factories without multiple real implementations
- complex configuration systems
- distributed architecture

Docker should only be introduced later if a concrete reproducible test scenario requires it.

MakerMedic should remain a focused local diagnostic application.

---

## Code Quality

Use Ruff for formatting and linting.

Before completing a phase, run:

    ruff format --check .
    ruff check .
    pytest

All must pass.

Do not disable lint rules merely to avoid fixing straightforward problems.

---

## Documentation

Documentation must describe implemented functionality only.

Clearly distinguish between:

    implemented

and:

    planned

Do not make roadmap features sound available.

Avoid marketing language.

Prefer concrete technical descriptions.

---

## Claims

Never fabricate:

- benchmark results
- diagnostic accuracy
- test counts
- supported hardware
- compatibility
- fault-detection rates
- performance numbers

Only report results actually measured.

If something has not been tested, state that.

---

## Git

Do not:

- create commits
- push branches
- create tags
- rewrite history

unless explicitly instructed.

Do not alter unrelated repository state.

---

## Development Workflow

Before modifying code:

1. Inspect the existing repository.
2. Read this CLAUDE.md completely.
3. Understand the current phase.
4. Inspect existing tests.
5. Preserve established contracts unless the current phase explicitly requires a change.

After modifying code:

1. Format.
2. Lint.
3. Run tests.
4. Manually smoke-test relevant CLI behavior.
5. Inspect the diff.
6. Report actual results.

---

## Final Principle

MakerMedic should behave like a careful engineer troubleshooting a machine:

Observe first.

Preserve evidence.

Distinguish uncertainty from failure.

Identify the smallest conclusion supported by the evidence.

Verify the result.

Do not trade those principles for flashy output or unnecessary features.