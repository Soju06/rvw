# Runtime deadline change context

## Purpose and scope

This document records the operational evidence and compatibility boundaries behind the `--deadline` contract. Normative behavior is in the adjacent delta specifications.

## Key decisions and measured basis

- The Codex adapter invokes GNU `timeout` with the selected seconds. A timeout exits 124, which rvw records through its generic `exit_nonzero:<code>` reason.
- `openspec/specs/runtime-contract/context.md` records that all 39 discovery runs in the PR #1119 smoke were valid and that discovery and adjudication completed in about 410 and 197 seconds. At process concurrency no greater than eight, total discovery slot occupancy was at most `410 * 8` seconds, so mean occupancy across the 39 runs was under 85 seconds. The existing 600-second default therefore remains a generous outlier bound rather than a value to raise globally.
- `openspec/specs/adjudication/context.md` records a 2026-08-12 production sample of 26 runs, with a median of one adjudication run versus eight discovery runs. It also already specifies that an uncertain claim receives one expanded pass at twice the deadline.
- The 1800-second CLI ceiling is three times the existing default and more than twenty times the derived mean discovery-occupancy upper bound. The doubled expanded pass therefore has a bounded maximum of 3600 seconds.
- A runtime holds one host-global slot until it exits. An unbounded operator value could pin scarce shared capacity for hours; work that cannot fit within 1800 seconds should use the existing chunked discovery mechanism.
- `lower-default-runtime-concurrency` and `split-replica-defaults` explicitly left deadlines unchanged, so this change fills a deliberately deferred gap without changing those controls.

## Constraints

- The 1-through-1800 range is a CLI contract. Direct Python callers retain the existing rule that a deadline must be positive.
- The selected value is a base deadline. The established expanded adjudication and stack-presence passes still multiply it by two.
- Deadline values are execution inputs and are not added to persisted run or report schemas.

## Failure modes

- Missing one helper edge can make a visible flag silently fall back to 600 for part of a command.
- A long but permitted runtime can hold a host-global slot for up to 1800 seconds, or 3600 seconds during its one expanded pass.
- GNU `timeout` exit 124 remains an INVALID runtime result; the new option changes only the operator-selected bound.

## Concrete example

Without `--deadline`, initial discovery and adjudication use 600 seconds and an expanded adjudication pass uses 1200 seconds. With `--deadline 1800`, every runtime entry path receives 1800 as its base and an expanded pass uses 3600 seconds. Values 0 and 1801 are rejected by CLI validation before runtime construction or execution.

## Historical deltas

Concurrency change #13 and replica-default change #17 both named deadlines as non-goals. Upstream PR #15 implements the currently stubbed `adjudicate` command from an older base and will require a follow-up adding both `--concurrency` and `--deadline` when it lands.
