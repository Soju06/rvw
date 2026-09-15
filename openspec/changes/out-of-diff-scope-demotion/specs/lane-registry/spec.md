## ADDED Requirements

### Requirement: Out-of-diff scope demotion

Packaged lane prompts MUST instruct agents to anchor defects caused by a change at the changed line that causes them when the manifestation is in pre-existing code.

#### Scenario: Demoted blocker remains visible

- **WHEN** a blocker is outside the changed hunks
- **THEN** it remains visible for audit with informational effective severity and cannot block or create an inline thread

## MODIFIED Requirements

### Requirement: Rules respect the lane blast radius

Every rule MUST apply to 100 percent of files in its declared activation domain. Base rules MUST express technology- and domain-neutral properties. A scoped subject that is absent MUST produce no finding. Narrower language, platform, artifact, and tool obligations MUST reside in accurately activated scope or project lanes. Scope prompts MUST restrict finding locations to their domain when a target has mixed paths. Rules MUST express an observable property, consequence, and verification method; process, style, approval, and required co-change mandates MUST be excluded. Packaged lanes MUST be deployer-neutral. Project rules MUST retain only deltas beyond base checks. Rule moves, removals, and ID changes MUST be documented.

#### Scenario: Frontend files do not activate backend checks

- **WHEN** changes contain only `apps/web/src/hooks/use-session.ts`, `apps/web/src/api/client.js`, or a TSX component
- **THEN** backend-observability does not activate

#### Scenario: Root tool and language scopes

- **WHEN** changes touch `tools/search.py` or `search_tool.py`
- **THEN** agent-tools and lang-python activate while base contracts retains only generic modeling rules
