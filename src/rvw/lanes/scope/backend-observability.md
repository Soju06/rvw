---
lane: backend-observability
tier: scope
schedule_hint: normal
severity_cap: suggestion
when:
  paths:
  - '**/server/**'
  - 'server/**'
  - '**/backend/**'
  - 'backend/**'
  - '**/workers/**'
  - 'workers/**'
---

# backend-observability

Review diagnosis of backend operations under declared server/backend/worker
directories. Language suffixes and directories named api alone do not establish
backend ownership. Only report gaps that materially prevent incident diagnosis.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: backend/undiagnosable-design

Backend state transitions must leave enough evidence to reconstruct a failed operation
and identify the affected entity. Missing transition identity can make distinct
operation histories indistinguishable. Trace a concrete incident through the state
machine and show the transition or entity that cannot be recovered from recorded
evidence.

## rule: backend/logging-gap

Backend operation records must carry the correlation identifiers needed to join related
events. Missing request or entity identifiers can make otherwise recorded events
impossible to connect to an incident. Trace a multi-step operation through its records
and identify the missing join. Generic swallowed-error provenance is owned by hygiene
and sensitive-value exposure by security; do not report those classes here.
