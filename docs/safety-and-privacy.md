# Safety and privacy

MakerMedic is designed to observe, diagnose, explain, recommend, and verify. It
does not automatically apply recommendations or remediate the host.

## Operational boundaries

- Normal operation does not require sudo or root.
- Commands use argument arrays and bounded timeouts, not arbitrary shell input.
- MakerMedic does not install packages or drivers, modify permissions or groups,
  kill processes, alter firewalls, restart services, flash firmware, or reset
  GPUs.
- Serial opening is disabled unless `--serial-open-test` is explicitly selected.
- Service targets must be `localhost` or a loopback IP. Credentials, queries,
  fragments, redirects, proxies, and external targets are rejected or disabled.

## Collected data

Camera smoke tests retain only success state and frame dimensions; pixels are
released and are not exported. USB discovery intentionally avoids serial
numbers. Process inspection is limited to a listener PID and short process name,
not command lines or environments.

Snapshots exclude evidence values. Support bundles include selected evidence,
but every key and structured subfield must pass an explicit allowlist. Unknown
evidence is omitted rather than exported and redacted later. Bundle invariants
exclude environment dumps, credentials, response bodies and headers, image
data, USB serial numbers, serial traffic, full process command lines, and raw
logs. Bundles are previewed and written locally; MakerMedic does not upload them.

## Validation lab

`SIMULATED` scenarios use fabricated evidence and do not inspect host devices.
`TEMPORARY_LOCAL` scenarios may create an isolated local resource. The shipped
temporary scenario binds an OS-selected loopback port, runs the real service
probe, and closes the server even when validation fails.

These controls reduce risk but are not an absolute security guarantee. Review a
support-bundle preview and the generated archive before sharing it.
