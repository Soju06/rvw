## Design

`AutoPolicy.triggers` defaults to `mode: denylist`, `drafts: skip`, and an empty rule list. A rule has a required `[a-z0-9-]+` name and optional authors, head/base fnmatch patterns, case-insensitive labels, and a Python/JavaScript-compatible title regular expression. Fields in one rule are ANDed; rules are ORed.

The existing base-revision policy reader remains the source boundary. Missing policy uses the packaged/default behavior. A read/parse failure on the Worker falls back to empty denylist behavior while recording `trigger.policy_error`; Python preserves its existing invalid-policy failure contract for other policy blocks. The trusted App trigger snapshot can suppress only invalid trigger validation after pre-enqueue fallback, while malformed whole YAML or invalid publication policy remains a visible run failure. Trigger evaluation only consumes webhook/API metadata.

The Worker evaluates before queue insertion. A skip creates/updates a neutral check with localized policy text and trigger facts, without allocating a sandbox. Draft skipping remains the existing no-check path. The CLI evaluates resolved PR metadata before discovery and writes a minimal summary on skip; SHA/uncommitted targets record `not_applicable`.

The shared trigger facts shape is optional for legacy artifacts and is validated strictly when present. `rerequested` and `--force-review` set `bypassed` and always enqueue/run.

## Portability

Title expressions use a portable subset: literals, explicit ranges, grouping,
alternation, anchors, ordinary quantifiers, and lookahead. Shorthand Unicode classes,
word boundaries, backreferences, inline flags, possessive quantifiers, named groups,
and lookbehind are rejected. The Worker translates dot/end-anchor behavior to Python
semantics and uses Unicode code points. Branch matching retains Python fnmatch semantics,
including slash-spanning wildcards and bracket classes.

## Publication-controls integration

The trigger change is rebased onto repository-publication-controls. The summary model and Worker parser retain publication channels, inline facts and disabled synthesis alongside trigger facts. CLI skip prose follows the resolved presentation locale and persists that presentation for replay. The trigger whole-policy validator also accepts and strictly validates the new publication fields; shared fixtures cover policies containing both features.

The Worker retains separate base-SHA policy reads: trigger eligibility is decided before enqueueing with policy-error fallback, while publication controls are read by the Durable Object and fail closed before sandbox dispatch. The readers also have different file-size limits and error classifications, so sharing the later read would change behavior.

Skip summaries retain the resolved publication channels and inline policy even though no findings are produced. App PASS summaries that record a trigger skip finish neutral with Python skip prose; contradictory BLOCK/skip artifacts remain invalid, and skip handling cannot replace artifact or infrastructure failures.
