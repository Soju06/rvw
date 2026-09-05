---
lane: ci-integrity
tier: scope
schedule_hint: normal
severity_cap: blocker
validation: pending
when:
  paths:
  - '.github/**'
  - '.gitlab-ci.yml'
  - 'Jenkinsfile'
  - '**/.circleci/**'
  - '.circleci/**'
---

# ci-integrity

Review committed automation gates for truthful pass/fail results. Findings
belong to gate execution and artifact selection, not workflow prose or templates.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: test-ci/fail-open-gate

A correctness gate must propagate a failing check to the job result. continue-on-error,
swallowed failures and pipes masking exit codes can accept a broken change. Trace an
actual nonzero exit through the committed workflow and show how the required gate still
succeeds.

## rule: test-ci/wrong-artifact

A gate must check the revision and artifact it claims to validate. A stale build, wrong
checkout or invalid cache can pass while the target is broken. Trace checkout, build,
cache keys and test inputs to identify the different artifact actually checked.
