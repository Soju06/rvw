## 1. Contract and regression coverage

- [x] 1.1 Add strict cloud-app-platform and container-ci-packaging deltas for pinned,
  checksum-verified, minimum-compatible GitHub CLI installations.
- [x] 1.2 Add an offline failing regression test for both Dockerfile contracts.

## 2. Image implementation and source of truth

- [x] 2.1 Replace distribution GitHub CLI packages in both images with the exact official
  release, pinned checksum verification, `/usr/local/bin/gh`, and build-time version gate.
- [x] 2.2 Synchronize both main specifications and record the measured failure and
  upstream compatibility evidence in capability context.

## 3. Verification and delivery

- [x] 3.1 Strict-validate the OpenSpec change and run all repository, cloud, workflow, and
  deployer-neutral verification gates.
- [x] 3.2 Build the cloud image, inspect its GitHub CLI version and help output, and remove
  the temporary local tag.
- [x] 3.3 Review the final diff and confirm the branch is ready for delivery to `main`.
