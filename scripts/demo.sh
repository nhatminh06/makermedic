#!/usr/bin/env bash
set -euo pipefail

makermedic --version
makermedic lab run gpu-driver-unavailable
makermedic lab run camera-permission-denied
makermedic lab run service-http-500
makermedic lab run-all
