#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
  echo "usage: $0 https://worker.example.workers.dev https://github.com/OWNER/REPO TARGET_SHA [DEADLINE_SECONDS]" >&2
  exit 2
fi

base_url=${1%/}
repo_url=$2
target_sha=$3
deadline_seconds=${4:-1500}
evidence="spike-evidence/run"
sandbox_id=""
process_id=""
destroyed=0
summary="driver stopped before the review outcome was observed"
last_observation="no status received"

if [[ ! "$repo_url" =~ ^https://github\.com/[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*(\.git)?$ ]]; then
  echo "REPO_URL must be a safe HTTPS GitHub repository URL" >&2
  exit 2
fi
if [[ ! "$target_sha" =~ ^[0-9a-f]{7,40}$ ]]; then
  echo "TARGET_SHA must be 7-40 lowercase hexadecimal characters" >&2
  exit 2
fi
if [[ ! "$deadline_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "DEADLINE_SECONDS must be a positive integer" >&2
  exit 2
fi

mkdir -p "$evidence/status"

# shellcheck disable=SC2317  # Invoked by the EXIT-trap handler.
cleanup() {
  if [[ -n "$sandbox_id" && "$destroyed" -eq 0 ]]; then
    if ! curl --fail-with-body --silent --show-error \
      --request POST "$base_url/destroy?sandboxId=$sandbox_id" \
      --output "$evidence/destroy.json"; then
      summary="$summary; sandbox destroy request also failed"
    fi
    destroyed=1
  fi
}

# shellcheck disable=SC2317  # Invoked indirectly by trap.
finish() {
  local driver_exit=$?
  trap - EXIT
  cleanup
  printf 'driver summary: %s\n' "$summary" >&2
  exit "$driver_exit"
}
trap finish EXIT

# Optional Codex runtime overrides: when RVW_CODEX_MODEL or RVW_CODEX_REASONING_EFFORT is set in
# the driver's environment it travels as the /start JSON body; otherwise the request is unchanged
# and the Worker var (or the packaged CLI default) applies. A set-but-empty value is forwarded so
# the Worker rejects it instead of silently running the default cell.
start_body_args=()
override_args=()
if [[ -n "${RVW_CODEX_MODEL+set}" ]]; then
  override_args+=(--arg model "$RVW_CODEX_MODEL")
fi
if [[ -n "${RVW_CODEX_REASONING_EFFORT+set}" ]]; then
  override_args+=(--arg reasoning_effort "$RVW_CODEX_REASONING_EFFORT")
fi
if ((${#override_args[@]} > 0)); then
  start_body=$(jq -n "${override_args[@]}" '$ARGS.named')
  printf '%s\n' "$start_body" > "$evidence/start-body.json"
  start_body_args=(--header 'Content-Type: application/json' --data "$start_body")
fi

date +%s%3N > "$evidence/start-request-epoch-ms.txt"
if ! curl --fail-with-body --silent --show-error \
  --request POST "$base_url/start?repo=$repo_url&target=$target_sha" \
  ${start_body_args[@]+"${start_body_args[@]}"} \
  --output "$evidence/start.json"; then
  summary="transport/API failure while starting the review"
  exit 3
fi
date +%s%3N > "$evidence/start-response-epoch-ms.txt"

if ! sandbox_id=$(jq -er '.sandboxId' "$evidence/start.json") ||
  ! process_id=$(jq -er '.processId' "$evidence/start.json"); then
  summary="invalid start response: sandboxId or processId is missing"
  exit 3
fi

deadline_at=$(($(date +%s) + deadline_seconds))
poll=0
outcome=""
review_exit=""
process_status="unknown"

while true; do
  status_file=$(printf '%s/status/%03d.json' "$evidence" "$poll")
  if ! curl --fail-with-body --silent --show-error \
    "$base_url/status?sandboxId=$sandbox_id&processId=$process_id" \
    --output "$status_file"; then
    summary="transport/API failure while polling status; last review observation: $last_observation"
    exit 3
  fi
  if ! process_status=$(jq -er '.process.status // "unknown"' "$status_file"); then
    summary="invalid status response at poll $poll"
    exit 3
  fi
  last_observation="process status $process_status at poll $poll"

  if review_exit=$(jq -er '.marker.exitCode' "$status_file" 2>/dev/null); then
    outcome="completed"
    break
  fi
  case "$process_status" in
    completed|failed|killed|error)
      outcome="missing_marker"
      break
      ;;
  esac

  now=$(date +%s)
  if ((now >= deadline_at)); then
    outcome="observer_deadline"
    break
  fi
  sleep_seconds=20
  remaining=$((deadline_at - now))
  if ((remaining < sleep_seconds)); then
    sleep_seconds=$remaining
  fi
  sleep "$sleep_seconds"
  poll=$((poll + 1))
done

if ! curl --fail-with-body --silent --show-error \
  "$base_url/result?sandboxId=$sandbox_id" \
  --output "$evidence/result.json"; then
  summary="transport/API failure while fetching results; last review observation: $last_observation"
  exit 3
fi

case "$outcome" in
  completed)
    if [[ ! "$review_exit" =~ ^-?[0-9]+$ ]]; then
      summary="invalid completion marker exit code: $review_exit"
      exit 5
    fi
    if ((review_exit == 0)); then
      summary="review completed successfully with exit code 0"
      exit 0
    fi
    summary="review completed with non-zero process exit code $review_exit"
    exit 6
    ;;
  observer_deadline)
    summary="review still running at the ${deadline_seconds}s observer deadline; this observer outcome is not evidence that the review failed"
    exit 4
    ;;
  missing_marker)
    summary="process reached terminal status $process_status without a completion marker"
    exit 5
    ;;
  *)
    summary="no completion marker was observed"
    exit 5
    ;;
esac
