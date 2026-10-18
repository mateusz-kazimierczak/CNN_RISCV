#!/usr/bin/env bash
# Run inside Ubuntu as root (Windows WSL supports `wsl.exe -u root`).
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
  echo 'Run this dependency installer as root.' >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  git curl ca-certificates build-essential autoconf flex bison help2man \
  libfl-dev zlib1g-dev libelf-dev ccache python3 python3-venv \
  binutils-riscv64-unknown-elf
