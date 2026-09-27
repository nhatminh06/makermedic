# Demo guide

Run the deterministic portfolio demonstration from the project root:

```console
./scripts/demo.sh
```

It displays the installed version, then validates three simulated failures:

1. NVIDIA hardware is present but driver communication fails. The driver is the
   root finding and dependent checks are blocked.
2. A camera exists but lacks readable access. The permission check fails and
   OpenCV opening is blocked.
3. A loopback service returns HTTP 500. TCP and HTTP reachability pass while the
   health diagnostic fails.

The final command prints the concise 39-scenario category summary. The demo uses
simulated fixtures only, requires no hardware or external network, and does not
modify the host.
