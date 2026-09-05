# Lane authoring

A lane owns one concern and one declared review scope. Its tier sets the blast
radius, not its importance or implementation language.

| Tier | Blast radius |
| --- | --- |
| `base` | Every consumer repository; technology- and domain-neutral properties only. |
| `project` | Repository-owned rules in `.rvw/lanes/`; narrow with `when.paths`. |
| `scope` | A code domain selected by accurate path predicates. |
| `dynamic` | This target's declared intent, not reusable technology policy. |

Every rule must hold for **100% of files in its declared domain**. A property's
subject can be absent: that means no finding, not a new obligation. Split rules
that need a different domain, platform, language, or artifact role. A prose
“only when” guard does not repair an overbroad predicate.

`when.paths` activates a lane for the target; it does not filter the supplied
diff. State allowed finding locations in the prompt. In a mixed diff, read
outside those locations only for supporting evidence. Never turn a nearby
unrelated file into another domain's finding location.

Write substantive guidance under each `## rule: <id>` heading. A rule contains:

- An observable property that must hold.
- Why violating it causes a concrete problem.
- How to verify that problem using code and its consumers.

Good: “A failed transfer must not be returned as successful. Otherwise a caller
can discard the only retry opportunity. Trace a failed operation through its
result and show the caller receiving success.”

Bad: “Add tests in the same commit and ask the owner before changing behavior.”
This asserts an author's workflow rather than a defect in the reviewed result.

Keep style, approval, co-change, file organization, and process mandates out of
code lanes. Check actual contrast and behavior; missing measurement notes or
paperwork do not establish a failure. There is no fifth policy/process tier.

Packaged lanes must contain no consumer-specific names, domains, account IDs,
paths, or artifacts. Repository lanes may name their local contracts. Before
adding a project rule, compare its defect class against **all base rules** and
active scopes. Keep only the project-specific delta and identify one owner of
each overlapping finding. Preserve IDs when moving rules and record moves,
removals, and justified language twins in [lane-changelog.md](lane-changelog.md).

Paths use case-sensitive `fnmatchcase` matching after normalizing `\\` to `/`
and resolving `.` segments. `*` and `**` can cross directory separators; this is
not shell globbing or gitignore. A leading `**/` also matches zero directories:
`**/*.py` matches both `main.py` and `src/main.py`. Explicit root twins such as
`['**/*.py', '*.py']` remain valid and make older registry intent clear. Interior
`src/**/x.py` does not gain a zero-directory match. Lists use OR semantics.
Braces are rejected: use `['**/*.ts', '**/*.tsx']`, never `**/*.{ts,tsx}`.

Do not infer frontend/backend ownership from `.ts`, `.js`, `.py`, or `.go`.
The backend lane declares `server`, `backend`, and `workers` directory
conventions; an `api` directory can contain a browser client. Tool lanes declare
`tools`, `tool`, `toolpacks`, and tool-named TS/Python conventions. Repositories
with different layouts need accurate project predicates. Test integrity and CI
integrity are separate domains. Manifests cannot select source-only dependency
removals without a declared package boundary.

A lane is a single Markdown document, for example:

```yaml
---
lane: local/result-contract
tier: project
schedule_hint: normal
when:
  paths: ['src/results/**']
---
```

Follow the delimiter with a purpose and nonempty `## rule: local/result-contract`
section. Do not also declare `rules:`. Unknown metadata is rejected.
`schedule_hint` is only an LPT ordering hint: `heavy`, `normal` (default), then
`light`. It is not a price, quota, severity, or execution budget. `cost` accepts
the same values with a deprecation warning for one release; do not supply both.

Run structural and mechanical scope checks before proposing a lane:

```sh
uv run rvw lanes lint --scope
uv run rvw lanes lint --scope --path .rvw/lanes
uv run rvw lanes lint .rvw/lanes --scope --json
```

Scope lint scans preambles and rule prose for forbidden domain terms. Base
markers include component/hook/render/CSS/a11y, HTTP handler/migration/transaction,
checked-language idioms, and LLM tool/tool schema. Frontend scopes flag
server/database terms; backend scopes flag UI terms. Exact project heading IDs
and normalized first sentences are compared against base rules, including when
`--path` selects only project files. Diagnostics carry source locations and
stable reasons; a violation fails the opted-in check. Syntax lint still works
without `--scope`. A clean result is a mechanical check, not semantic proof.

For a legitimate generic example, explain why the term does not narrow the rule,
then add an exact exception: `<!-- lint-allow: SQL -->` on the affected line.
For a reviewed recurring term, frontmatter accepts:

```yaml
lint:
  allow-scope-terms: [SQL]
```

Use the smallest exception and explain it nearby. Exceptions waive term alarms;
they do not justify a known scope violation or a duplicated base rule. Run the
same lint again and inspect activation on root, nested, unrelated, and mixed
paths. Validate specifications with `openspec validate --specs`.
