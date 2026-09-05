---
lane: manifests
tier: scope
schedule_hint: normal
severity_cap: blocker
validation: pending
when:
  paths:
  - '**/package.json'
  - 'package.json'
  - '**/package-lock.json'
  - 'package-lock.json'
  - '**/npm-shrinkwrap.json'
  - 'npm-shrinkwrap.json'
  - '**/yarn.lock'
  - 'yarn.lock'
  - '**/pnpm-lock.yaml'
  - 'pnpm-lock.yaml'
  - '**/bun.lock'
  - 'bun.lock'
  - '**/bun.lockb'
  - 'bun.lockb'
  - '**/pyproject.toml'
  - 'pyproject.toml'
  - '**/uv.lock'
  - 'uv.lock'
  - '**/poetry.lock'
  - 'poetry.lock'
  - '**/requirements*.txt'
  - 'requirements*.txt'
  - '**/Pipfile'
  - 'Pipfile'
  - '**/Pipfile.lock'
  - 'Pipfile.lock'
  - '**/go.mod'
  - 'go.mod'
  - '**/go.sum'
  - 'go.sum'
  - '**/Cargo.toml'
  - 'Cargo.toml'
  - '**/Cargo.lock'
  - 'Cargo.lock'
  - '**/Gemfile'
  - 'Gemfile'
  - '**/Gemfile.lock'
  - 'Gemfile.lock'
  - '**/composer.json'
  - 'composer.json'
  - '**/composer.lock'
  - 'composer.lock'
---

# manifests

Review newly added dependencies in changed manifests and lockfiles.
Lockfile-only churn is not a finding. Read source usage as supporting evidence;
this lane does not claim coverage of source-only dependency removals.

Allowed finding locations: changed files matching `when.paths` in this domain.
Other files in a mixed diff are supporting evidence only. An absent subject
produces no finding; a path match does not impose a new obligation.

## rule: deps/unused-added

A newly added direct dependency must have an actual consumer in its package. An unused
addition adds installation and maintenance burden without enabling behavior. Search all
package imports, scripts, plugins, configuration and build tooling before reporting it
as unused; transitive lock entries and implicit tool integrations are not unused merely
because source lacks an import.
