#!/usr/bin/env bash
# Run this ONCE on your WSL2 box, then paste the printed digest into
# PINNED_IMAGE in delta/evaluation/launcher.py.
#
# Why: Phase1 guide §17, pitfall #5 -- "Docker tags are mutable. Pin by
# digest or your 'reproducible' experiment isn't." Stage 1 needs no custom
# image (harness/ is bind-mounted read-only at run time, not baked in via a
# Dockerfile -- see harness/supervisor.py's module docstring), so the only
# thing worth pinning is this one upstream base image.
set -euo pipefail

IMAGE="python:3.12-slim"

echo "Pulling ${IMAGE}..."
docker pull "${IMAGE}"

DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${IMAGE}")

echo
echo "Pinned image reference:"
echo "  ${DIGEST}"
echo
echo "Paste this into delta/evaluation/launcher.py:"
echo "  PINNED_IMAGE = \"${DIGEST}\""
echo
echo "Record it in your manifest too (Phase1 guide §5: 'Include the"
echo "container image digest in the manifest')."
