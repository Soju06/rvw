#!/usr/bin/env bash
# Shared helpers for the rvw review-phase PATH shims. Sourced, not executed.
#
# The shims sit in /opt/rvw-shims ahead of the real binaries. Outside the review
# phase they are transparent. During RVW_PHASE=review they refuse remote access
# with a one-line machine-readable message and exit 2, so a model-driven tool
# command cannot fetch, clone, publish, or query remote services; the checkout is
# complete and the base and head are available locally.

rvw_shim_dir() {
  local source="${BASH_SOURCE[1]}"
  cd "$(dirname "$source")" && pwd -P
}

# Resolve the first executable named "$1" on PATH that is not one of the shims.
rvw_real_binary() {
  local name="$1" shim_dir="$2" entry candidate
  local IFS=':'
  for entry in $PATH; do
    [[ -z "$entry" ]] && entry="."
    candidate="$entry/$name"
    if [[ -x "$candidate" && ! -d "$candidate" ]]; then
      if [[ "$(cd "$entry" 2>/dev/null && pwd -P)" == "$shim_dir" ]]; then
        continue
      fi
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

rvw_in_review_phase() {
  [[ "${RVW_PHASE:-}" == "review" ]]
}

rvw_refuse() {
  printf '%s\n' "$1" >&2
  exit 2
}

rvw_exec_real() {
  local name="$1" shim_dir="$2"
  shift 2
  local real
  if ! real="$(rvw_real_binary "$name" "$shim_dir")"; then
    printf 'rvw: %s is not installed\n' "$name" >&2
    exit 127
  fi
  exec "$real" "$@"
}
