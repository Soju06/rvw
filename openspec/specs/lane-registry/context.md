# Lane registry context

## Purpose and scope

This capability owns the stable vocabulary and the name-indirection boundary between rvw code and the external runtime registry. Normative behavior is in [spec.md](spec.md); the registry itself remains outside this repository at `~/.hermes/review/`.

A planned Run expands across lane, replica, and diff chunk. `rvw plan` derives chunks from the same exclusion and whole-file planner as execution, so its total is `lanes x replicas x chunks`; a one-chunk target retains the historical lane x replica count.

## Key decisions and measured basis

- Scope (`diff`, `direct-deps`, or `repository`) and `requires_brief` are
  compatible optional lane metadata. Their defaults preserve the current
  registry behavior; this repository does not modify the external runtime
  registry to select real scope values.

- ADR-001 separates Rule, Lane, Layer, Runtime, and Run so review content, activation, execution mechanics, and publication policy do not collapse into one kind of document.
- ADR-002 fixes four increasingly specific tiers. Base is the structural always-on floor; project and scope use repository/path predicates; dynamic carries per-target intent.
- ADR-011 places the live registry at `~/.hermes/review/` and makes call sites refer to IDs. A lane document is YAML frontmatter plus its prompt body.
- `validation: pending` makes lane promotion explicit. The gate compares a closed-enum run with a free-rule-ID run and passes when the free union contains no rule outside the closed enum. The original parity experiment found five findings in each condition; a later 19-lane batch showed eight apparent site gaps but zero novel rule IDs, establishing those differences as replica variance rather than vocabulary recall loss.

## Constraints

- The registry is cross-repository and is versioned outside rvw.
- `Registry.activate` accepts repository and path predicates only; symbol predicates described historically are not implemented.
- Layer order is fixed, but the loader does not enforce that a lane belongs to only one layer. Duplicate lane IDs are de-duplicated by first activation in planning/discovery.
- Runtime profiles and publication policies are not lane content.

## Failure modes

- A moved path can make a scope predicate silently stop firing.
- A missing lane file fails resolution with the attempted path.
- Invalid YAML, unknown frontmatter keys, an empty rules list, or malformed delimiters fail lane loading.
- The current `doctor` command reports run health, not the registry-integrity and predicate-conflict audit proposed by ADR-011.

## Concrete example

```yaml
layers:
  - id: base
    tier: base
    lanes: [slop-hygiene, unscoped-sweep]
  - id: scope/frontend
    tier: scope
    when:
      paths: ["**/*.tsx"]
    lanes: [frontend/skeleton-parity]
```

A change to `web/page.tsx` activates both layers. `unscoped-sweep` resolves to `lanes/base/unscoped-sweep.md`; `frontend/skeleton-parity` resolves to `lanes/scope/frontend/skeleton-parity.md`.

## Historical deltas

ADR-002 mentioned symbol predicates and ADR-011 assigned registry integrity checks to `rvw doctor`; neither behavior exists in the current modules. The normative spec therefore covers repository/path activation, typed loading, and the implemented pending-validation visibility only.
