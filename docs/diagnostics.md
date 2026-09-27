# Diagnostic domains

MakerMedic is Linux-focused. Absence of optional hardware is normally a warning,
not proof that the host is broken.

## System

Observes the operating system, kernel, architecture, CPU counts, memory, and
root-filesystem capacity. Rules identify unsupported platforms and low or
critically low memory/disk availability. Collection is passive.

## Python

Observes the interpreter version, virtual-environment state, interpreter-bound
pip, PATH pip, and optional distribution metadata. It identifies unsupported
Python versions, missing isolation, pip/environment mismatch, and missing
requested packages. Package inspection reads metadata without importing or
installing the package and does not access the network.

## NVIDIA GPU, CUDA, and PyTorch

Observes NVIDIA PCI visibility, bounded `nvidia-smi` output, NVML initialization,
optional PyTorch import/build information, CUDA visibility, and tiny allocation
and computation tests when prerequisites are healthy. The checks distinguish
missing optional hardware/PyTorch from driver, visibility, allocation, and
compute failures. MakerMedic does not change drivers, reset GPUs, or install
CUDA/PyTorch.

## Camera and OpenCV

Observes deterministic `/dev/video*` discovery, access permissions, optional
V4L2 capability data, busy state, OpenCV availability, and open/read outcomes.
When prerequisites permit, the probe may open one selected device and read one
frame. It records dimensions only, immediately releases the device, and does
not retain pixels, screenshots, or video.

## USB

Observes bounded Linux sysfs USB identity and optionally cross-checks `lsusb`.
Rules distinguish unavailable discovery, no devices, and missing optional
tooling. USB serial numbers are intentionally not collected. No USB device is
opened or modified.

## Serial

Observes `/dev/ttyUSB*` and `/dev/ttyACM*`, effective read/write access, owning
group context, safe USB identity, and busy state. Discovery and permission checks
are passive. Port open/close testing requires `--serial-open-test`; it writes and
reads no serial traffic and attempts to keep DTR/RTS low, though operating-system
or adapter behavior can still make opening a device observable.

## Local services

Accepts one explicit unauthenticated HTTP/HTTPS loopback URL. It observes host
resolution, TCP connectivity, one non-redirecting HTTP GET, status semantics,
and a bounded Linux listener view for the requested port. It never targets LAN
or public hosts, reads a response body beyond one discarded byte, sends
credentials/cookies, scans ports, or restarts services.
