#!/usr/bin/env bash
# Shared helpers for the runbook scripts. Source it; do not run it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/environments/dev"
APP_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
export APP_VERSION

log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null || die "$tool is not installed"
  done
}

require_login() {
  need az
  az account show >/dev/null 2>&1 || die "not signed in: run 'az login' first"
}

# tf_out <name>: one raw output of the dev environment.
tf_out() { terraform -chdir="$TF_DIR" output -raw "$1"; }

# retry <attempts> <sleep seconds> <command...>: role assignments take minutes to apply, so data-plane calls retry.
retry() {
  local attempts=$1 pause=$2 attempt=1
  shift 2
  until "$@"; do
    if ((attempt >= attempts)); then return 1; fi
    log "attempt $attempt of $attempts failed; waiting ${pause}s for the role assignment to take effect"
    sleep "$pause"
    attempt=$((attempt + 1))
  done
}
