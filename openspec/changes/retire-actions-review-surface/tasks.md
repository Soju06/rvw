## 1. Specification deltas

- [x] 1.1 Remove the reusable review workflow and job-as-check requirements from `container-ci-packaging` and rename the image GitHub CLI requirement.
- [x] 1.2 Rewrite the operation-modes, pr-gate, reporting, and release-automation requirements that named Actions as a review surface.
- [x] 1.3 Synchronize the main specs and adjacent contexts with the deltas and record the retirement decision and its measured basis.

## 2. Workflow, documentation, and ownership

- [x] 2.1 Delete `.github/workflows/rvw-review.yml` and its CODEOWNERS entry.
- [x] 2.2 Replace `docs/container-ci.md` with `docs/container-image.md` covering direct container runs, release publication, immutable pins, and the App as the automated surface.
- [x] 2.3 Point `README.md` at the two review surfaces and the container image guide.

## 3. Tests

- [x] 3.1 Delete the workflow-contract, step-script exit propagation, and step-summary contract tests that read the removed workflow.
- [x] 3.2 Replace the Actions guide test with a container image guide test and add a guard that no review workflow is published.
- [x] 3.3 Confirm the shared paths keep their tests: `rvw.container_entrypoint`, `rvw run`, three-adapter parity, and both Dockerfiles.

## 4. Verification

- [x] 4.1 Run Ruff lint and formatting, ty, the offline pytest suite, `openspec validate --specs`, and strict change validation.
- [x] 4.2 Grep for residual `rvw-review.yml`, `workflow_call`, and `pull_request_target` references and classify every remaining hit.
