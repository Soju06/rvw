#!/usr/bin/env bash
# In-image self-test for the rvw review-phase PATH shims. Needs no network.
#
# The image build runs it once; operators can rerun it against a built image:
#   docker run --rm --entrypoint bash <image> /usr/local/lib/rvw/check-review-shims.sh
# Exits 0 when every check passes and prints one line per check.
set -uo pipefail

failures=0
pass() { printf 'ok   %s\n' "$1"; }
fail() { printf 'FAIL %s\n' "$1"; failures=$((failures + 1)); }

expect_refusal() {
  # expect_refusal <description> <expected stderr line> <command...>
  local description="$1" expected="$2" output code
  shift 2
  output="$("$@" 2>&1)"
  code=$?
  if [[ $code -eq 2 && "$output" == "$expected" ]]; then
    pass "$description"
  else
    fail "$description (exit $code, output: $output)"
  fi
}

expect_success() {
  local description="$1"
  shift
  if "$@" >/dev/null 2>&1; then pass "$description"; else fail "$description"; fi
}

expect_passthrough() {
  # The real binary ran: no refusal line and no refusal exit code (the command may still fail).
  local description="$1" output code
  shift
  output="$("$@" 2>&1)"
  code=$?
  if [[ $code -ne 2 && "$output" != *"disabled during review"* ]]; then
    pass "$description"
  else
    fail "$description (exit $code, output: $output)"
  fi
}

expect_output_contains() {
  local description="$1" needle="$2" output
  shift 2
  output="$("$@" 2>&1)"
  if [[ "$output" == *"$needle"* ]]; then pass "$description"; else fail "$description (output: $output)"; fi
}

for tool in git gh curl wget; do
  resolved="$(bash -lc "command -v $tool")"
  if [[ "$resolved" == "/opt/rvw-shims/$tool" ]]; then
    pass "login shell resolves $tool to the shim"
  else
    fail "login shell resolves $tool to the shim (got $resolved)"
  fi
  resolved="$(command -v "$tool")"
  if [[ "$resolved" == "/opt/rvw-shims/$tool" ]]; then
    pass "non-login shell resolves $tool to the shim"
  else
    fail "non-login shell resolves $tool to the shim (got $resolved)"
  fi
done

repo="$(mktemp -d)"
git -C "$repo" init -q
git -C "$repo" remote add origin https://example.invalid/example.git

expect_refusal "review: git fetch is refused" 'rvw: remote git is disabled during review' \
  env RVW_PHASE=review git -C "$repo" fetch origin
expect_refusal "review: git clone of a URL is refused" 'rvw: remote git is disabled during review' \
  env RVW_PHASE=review git clone https://example.invalid/example.git "$repo/clone"
expect_refusal "review: git ls-remote is refused" 'rvw: remote git is disabled during review' \
  env RVW_PHASE=review git -C "$repo" ls-remote origin
expect_refusal "review: git remote set-url is refused" 'rvw: remote git is disabled during review' \
  env RVW_PHASE=review git -C "$repo" remote set-url origin https://example.invalid/other.git
expect_refusal "review: scp-style URL is refused" 'rvw: remote git is disabled during review' \
  env RVW_PHASE=review git ls-remote git@example.invalid:example/example.git
expect_success "review: local git status still works" env RVW_PHASE=review git -C "$repo" status --short
expect_success "review: local git rev-parse still works" env RVW_PHASE=review git -C "$repo" rev-parse --git-dir
expect_success "review: git remote -v still works" env RVW_PHASE=review git -C "$repo" remote -v
expect_output_contains "review: absolute-path git fetch is stopped by GIT_ALLOW_PROTOCOL" \
  "not allowed" env RVW_PHASE=review GIT_ALLOW_PROTOCOL=none /usr/bin/git -C "$repo" fetch origin
expect_refusal "review: gh api is refused" 'rvw: gh is disabled during review' \
  env RVW_PHASE=review gh api repos/example/example
expect_success "review: gh --version still works" env RVW_PHASE=review gh --version
expect_refusal "review: curl is refused" 'rvw: curl is disabled during review' \
  env RVW_PHASE=review curl -sS https://example.invalid/
expect_refusal "review: wget is refused" 'rvw: wget is disabled during review' \
  env RVW_PHASE=review wget -q https://example.invalid/
expect_passthrough "checkout: git fetch reaches the real git" \
  env RVW_PHASE=checkout git -C "$repo" fetch origin
expect_passthrough "no phase: gh api reaches the real gh" gh api repos/example/example
expect_success "no phase: gh --version reaches the real gh" gh --version
expect_success "no phase: curl --version reaches the real curl" curl --version

rm -rf "$repo"
if [[ $failures -eq 0 ]]; then
  echo "review shims: all checks passed"
else
  echo "review shims: $failures check(s) failed"
  exit 1
fi
