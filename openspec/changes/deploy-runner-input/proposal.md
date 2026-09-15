## Why

The reusable deploy workflow forces `ubuntu-latest`, so a consumer whose
GitHub-hosted runner billing is gated cannot deploy using its available runners.
Consumers need to select the deploy runner while existing callers retain the default.

## What Changes

- Add optional string input `runs_on`, defaulting to `ubuntu-latest`, and use it
  directly for the deploy job's runner.
- Document the single-label contract and a Blacksmith caller example; label
  arrays and runner groups are unsupported.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cloud-app-platform`: Allow callers to select the reusable deployment runner.

## Impact

Only `.github/workflows/rvw-deploy.yml`, `cloud/README.md`, and the associated
OpenSpec artifacts change. Existing callers keep `ubuntu-latest`. No dependency,
Python, Terraform, Wrangler, other workflow, or consumer repository changes.
