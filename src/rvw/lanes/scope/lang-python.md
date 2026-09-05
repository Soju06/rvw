---
lane: lang-python
tier: scope
schedule_hint: normal
severity_cap: blocker
validation: pending
when:
  paths:
  - '**/*.py'
  - '*.py'
---

# lang-python

Review unsafe Python checker bypasses in annotated code. Untyped code alone
is not a defect.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: slop/typing-bypass

Annotated Python values must satisfy the shape promised to their consumers. A # type:
ignore, unchecked typing.cast or widening to Any can conceal an actual mismatch. Trace
the runtime value past the bypass to the incompatible operation and show the violated
guarantee; a cast backed by runtime validation or an explained checker limitation is not
itself a defect.
