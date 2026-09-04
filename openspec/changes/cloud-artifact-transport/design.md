## Context

Two A1 runs on Worker v0.11.3 completed their private clone and GitHub GraphQL
requests with HTTP 200, then reached `publishing` in about 35 seconds from
process start. Every `readFile(..., {encoding: "none"})` call failed with the
pinned SDK's RPC-only encoding error, leaving R2 empty. Because the Worker read
only files written by the shell and never captured `getProcessLogs`, neither the
process stderr nor an authoritative terminal record survived cleanup.

The current artifacts are all UTF-8 JSON, Markdown, or logs. Binary transport
is unnecessary for the A1 persistence contract.

## Goals / Non-Goals

**Goals:** supported text reads, best-effort terminal diagnostics before result
parsing, secret-filtered failure summaries, deterministic R2 keys, and offline
regression coverage.

**Non-Goals:** enabling an unneeded binary/RPC transport, deploying the Worker,
changing review policy, changing the Python runtime, or claiming a definitive
cause for the 44-second wall-clock exit without captured live logs.

## Decisions

### Use explicit UTF-8 reads

All persisted A1 artifacts are text. The Worker will request `encoding: "utf8"`
for result files and will put the resulting string into R2 with the existing
content types. This avoids coupling artifact publication to an optional binary
RPC transport and makes the intended encoding testable.

### Capture process observations before artifact interpretation

When an SDK process becomes terminal, the alarm will first obtain its captured
stdout/stderr, derive duration from SDK timestamps, and persist `run.log` and
`process.json`. The generated review script will also write a redacted,
printenv-style snapshot early enough to survive review-command failure. Each
diagnostic write is best-effort and independent so one unavailable source does
not prevent the remaining evidence from reaching R2.

`run.log` is assembled from the SDK-captured stdout and stderr. `process.json`
contains only `exitCode`, `signal`, `durationMs`, and `command`. The environment
snapshot redacts names or values matching credential-shaped terms even though
the Sandbox contract passes only placeholders.

### Enrich only missing-result summaries with safe stderr

When required result artifacts are missing, the neutral Check Run summary will
append the process exit code, duration, and approximately the last 20 stderr
lines. Before publication, lines containing `Bearer`, `token`, or `key=` are
redacted case-insensitively. Ordinary successful summaries remain compact.

### Remove two proven fast-failure conditions

The live trace contains exactly one GitHub API request after cloning: the
numeric PR target's preliminary `gh repo view` GraphQL request. It contains no
subsequent PR metadata, diff, or Codex request. The A1 command will instead use
the full PR URL already derivable from the validated webhook message, avoiding
that redundant repository lookup. The command also supplies the non-secret
`GH_REPO` identity so subsequent `gh pr` calls need not infer it from the clone
URL. Whether the HTTP-200 GraphQL response failed at authorization, response
validation, or another `gh` boundary remains a live rerun question because
stderr was lost.

The measured repository's base revision has no `.rvw/policies/auto.yaml`, and
the image has no external registry policy. Existing rvw behavior therefore
raises `PolicyNotFound` before the pipeline if target resolution succeeds. The
image will install a versioned default at rvw's existing external-policy path.
The CLI still probes the repository base revision first, so repository policy
remains authoritative when present.

## Offline diagnosis boundary

The A1 command runs from the target checkout, supplies the adjacent checkout as
`--repo-dir`, explicitly sets `RVW_CODEX_SANDBOX`, passes `CODEX_BASE_URL`, and
fetches the recorded base SHA into both clones. Repository auto policy is
optional only when the existing external default is available. Wrong working
directory, missing adjacent checkout, missing runtime environment, and missing
base object can therefore be rejected from source. The exact first GraphQL
failure still cannot be named without stderr; the new diagnostics are the proof
mechanism for the next live run.
