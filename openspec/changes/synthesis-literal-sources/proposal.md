## Why

Correct Korean synthesis for PR 1781 fell back twice because ordinary acronyms, PR terminology, composed source locations and whitespace-normalized evidence were treated as inventions. Fidelity must distinguish these legitimate explanations from invented or mutated identifiers and paths.

## What Changes

- Check inventions only in backticked spans and bare paths; retain broader technical-token protection for language checking.
- Include persisted PR title/body in every prose field's source set, including retained artifact replay.
- Accept source code with collapsed whitespace and source paths composed with established finding/evidence line numbers.
- Explain the searched source categories in one-line literal retry diagnostics and retain both live Korean outputs as offline regressions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `synthesis`: Correct literal fidelity, PR source scope and retry diagnostics without changing runtime or language policy.

## Impact

`src/rvw/synthesis.py`, retained validation in `src/rvw/store.py`, deterministic synthesis tests/fixtures, and synchronized synthesis specifications/context. The 300-second budget, one retry, fallback reasons, schemas, language thresholds and forbidden vocabulary remain unchanged.
