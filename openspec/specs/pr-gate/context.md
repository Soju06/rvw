# PR gate context

## Purpose and scope

This capability replaces a prose-and-copy-paste PR gate sequence with one artifact-backed command. It owns anchor capture and revalidation, isolated checkout, exact review invocation count, coverage and disposition validation, verdict rendering, and COMMENT-only publication. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- Six apifuse dogfood rounds found unbound shell variables, captured-but-unchecked SHAs, count-only disposition checks, missing coverage checks, double review ambiguity, and manual 40-character SHA relay.
- Target mode performs one review with one replica by default and writes `gate-plan.json`, including the replica and planner-derived chunk counts. Explicit `--replicas N` enables heavy verification. Coverage validation compares the exact lane x replica x chunk Cartesian product rather than relying on aggregate counts. When findings need a human decision, `gate-dispositions.yaml` contains the deterministic group keys and resume mode consumes the same run without invoking models again.
- The repository-admin permission returned by GitHub is the verifiable owner authority for blocker acceptance. rvw records that actor and the human reason but does not decide or publish an approval.
- `accepted` and `must_fix` are deliberately small disposition states. The latter keeps the gate blocked; the former records explicit risk acceptance subject to blocker authority.
- Gate publication reuses the ordinary publish implementation, so COMMENT hardcoding, dry-run default, inline selection, and the bounded bulk 422 fallback have one code path.

## Constraints

- Gate targets GitHub pull requests and requires working `gh` and `git` commands plus authenticated repository access.
- The checkout clone fetches GitHub's `refs/pull/<number>/head` before detaching at the captured SHA so fork pull requests do not depend on the base branch advertising the commit.
- Finding IDs include hunk identity and are valid only while both persisted anchors remain current.
- Resume requires the ordinary run stages and `gate-plan.json` written by target mode.
- A coverage failure identifies the missing, unexpected, or invalid replica-chunk identity from persisted artifacts.

## Failure modes

- A large repository makes disposable cloning more expensive than reusing a checkout; isolation is favored over speed for the gate path.
- GitHub installations without the pull-request ref namespace cannot use the current checkout provisioner.
- Repository-admin authority may be narrower than an organization's informal owner group; configurable authority sources are outside this version.
- `accepted` records a human judgment and cannot prove the judgment was substantively correct.

## Concrete example

```bash
rvw gate --target 1134
# edit /tmp/rvw/<run-id>/gate-dispositions.yaml
rvw gate --run <run-id> \
  --dispositions /tmp/rvw/<run-id>/gate-dispositions.yaml
```

The first command reviews once and exits 1 when actionable findings need dispositions. The second command revalidates the PR anchors and saved coverage, produces `gate-verdict.json` and `gate-verdict.md`, and writes a dry-run COMMENT payload without repeating review.

## Historical deltas

Before this capability, checkout ownership and anchor freshness were external concerns, and ordinary publish had no pre-publication stale-target guard. Those limitations remain for standalone `review` and `publish`; `gate` adds the stronger composed contract without changing their behavior.
