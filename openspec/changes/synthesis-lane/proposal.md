## Why

Published reviews expose dense stage prose without explaining the PR's purpose or what to do first. Inline findings disappear from the body even though the summary counts them, making required changes easy to miss.

## What Changes

- Add a bounded, artifact-derived synthesis pass after adjudication with strict JSON, one validation retry, and nonfatal fallback.
- Publish localized overview and finding explanations, retain every finding in the body, and collapse evidence in synthesized inline items.
- Add repository presentation voice settings with matching Python and Worker validation.
- Persist synthesis telemetry, expose it in check facts, retain operator report overrides, and neutralize diagnostic placeholders.

## Capabilities

### New Capabilities

- `synthesis`: Artifact-derived explanatory synthesis, fidelity validation, bounded execution and fallback.

### Modified Capabilities

- `lane-registry`: Strict base-revision reviewer voice configuration.
- `reporting`: Reader-first publication, body/inline agreement, diagnostic synthesis precedence, voice configuration and summary facts.
- `runtime-contract`: Synthesis telemetry in shared execution contracts with legacy compatibility.
- `cloud-app-platform`: Worker voice parsing and synthesis fact consumption.

## Impact

Ordinary pipeline, artifact store, publication renderers, locale catalogs, strict schemas, Python CLI summary producers, and Worker presentation/contract/check consumers. Discovery and adjudication prompts, runtime defaults, event policy, thread identity/reconciliation, special gate/stack publication, external registry and deployment surfaces remain outside scope.
