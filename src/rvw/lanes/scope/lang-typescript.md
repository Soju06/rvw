---
lane: lang-typescript
tier: scope
schedule_hint: normal
severity_cap: blocker
validation: pending
when:
  paths:
  - '**/*.ts'
  - '*.ts'
  - '**/*.tsx'
  - '*.tsx'
---

# lang-typescript

Review unsafe TypeScript checker bypasses, including TSX. Casts and suppressions
with demonstrated runtime guarantees are valid.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: slop/typing-bypass

TypeScript values must satisfy the shape promised to their consumers. An as any cast,
double assertion, @ts-ignore or @ts-expect-error can conceal a real mismatch rather than
fix it. Trace the value past the bypass to an unsafe access or assignment and show the
violated guarantee; do not report a justified suppression or cast merely because it
exists.
