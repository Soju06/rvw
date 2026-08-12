## ADDED Requirements

### Requirement: Runtime executions honor the host-global concurrency contract

Runtime-executing commands MUST bound total in-flight runtime executions across all rvw processes on one host with a file-lock slot gate shared through a host-local slot directory, defaulting to 12 slots. The cap MUST be configurable via `RVW_HOST_CONCURRENCY`, where `0` disables the gate and a non-integer or negative value MUST be rejected before runtime execution. Slots MUST be released when the owning execution completes, fails, or its process terminates, and a slot root that is a symlink or foreign-owned MUST fail closed. On Linux, each spawned runtime wrapper MUST request a parent-death `SIGTERM` and MUST terminate itself if its parent changed before that request took effect, so a runtime child does not outlive the rvw process whose slot the kernel released. This child-lifetime coupling is not guaranteed on non-Linux platforms.

The gate MUST require atomic `O_NOFOLLOW` support and fail at construction when it is unavailable. Each owner-matched slot directory, including a pre-existing directory, MUST be set to mode 0700 and re-verified through its opened descriptor before use. Slot files MUST be opened relative to the validated slot-directory descriptor while that descriptor remains open for acquisition, and descriptor-based validation MUST fail closed if ownership, directory type, or mode is unsafe.

#### Scenario: Two processes share the host cap

- **GIVEN** `RVW_HOST_CONCURRENCY` is 12 on one host
- **WHEN** two rvw review processes each run with process concurrency 8
- **THEN** their combined in-flight runtime executions never exceed 12

#### Scenario: Operator disables the gate

- **WHEN** a runtime-executing command starts with `RVW_HOST_CONCURRENCY=0`
- **THEN** runtime executions are bounded only by the per-process concurrency

#### Scenario: Invalid cap is rejected

- **WHEN** a runtime-executing command starts with `RVW_HOST_CONCURRENCY=abc`
- **THEN** the command fails with a usage error before any runtime execution

#### Scenario: Killed process frees its slots

- **WHEN** a process holding host slots is terminated without cleanup
- **THEN** its slots become acquirable by other processes without manual intervention

#### Scenario: Killed Linux parent terminates its runtime child

- **GIVEN** an rvw process on Linux has spawned a runtime wrapper while holding a host slot
- **WHEN** the rvw process receives `SIGKILL`
- **THEN** the kernel releases its slot and sends `SIGTERM` to the runtime wrapper so the wrapper and runtime terminate instead of overlapping replacement work

#### Scenario: Existing slot directory has permissive permissions

- **WHEN** an owner-matched slot directory already exists with group or other permissions
- **THEN** the gate sets it to mode 0700 and verifies that mode through the opened directory descriptor before acquiring a slot

#### Scenario: Validated slot directory path is replaced

- **WHEN** a slot acquisition begins after the slot-directory descriptor has been validated
- **THEN** every candidate slot file is opened relative to that held descriptor rather than by re-resolving the validated path

#### Scenario: Atomic symlink protection is unavailable

- **WHEN** the platform does not expose `O_NOFOLLOW`
- **THEN** host-slot gate construction fails with a clear runtime error before any slot path is used
