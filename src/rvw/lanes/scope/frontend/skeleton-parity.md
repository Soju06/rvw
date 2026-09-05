---
lane: frontend/skeleton-parity
tier: scope
schedule_hint: light
severity_cap: warning
when:
  paths:
  - '**/*.tsx'
  - '*.tsx'
  - '**/*.jsx'
  - '*.jsx'
  - '**/*.vue'
  - '*.vue'
  - '**/*.svelte'
  - '*.svelte'
---

# frontend/skeleton-parity

When the changed code involves components that have skeleton/placeholder
loading states, verify the skeleton still matches the real UI. Return PASS if
no skeleton UI exists near the changed components.

- `skeleton/shape-drift` — the skeleton's structure (row counts, block layout,
  aspect ratios, column arrangement) no longer matches the loaded UI it stands
  in for.
- `skeleton/update-missed` — this change adds/removes/reshapes a visible
  element in the real component but its skeleton counterpart was not updated —
  the classic feature-add-forgot-the-skeleton defect. Also the reverse:
  skeleton updated, real UI change reverted/absent.

Locate the skeleton by convention (`*Skeleton`, `*.skeleton.*`, `isLoading`
branches, Suspense fallbacks) and compare structure, not pixels.

Allowed finding locations: changed UI files matching `when.paths`. Other files
in mixed diffs are supporting evidence only.

## rule: skeleton/shape-drift

The rule is defined by the lane guidance above.

## rule: skeleton/update-missed

The rule is defined by the lane guidance above.
