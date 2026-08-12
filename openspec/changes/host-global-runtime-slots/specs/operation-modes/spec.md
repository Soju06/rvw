## ADDED Requirements

### Requirement: Runtime executions honor the host-global concurrency contract

Runtime-executing commands MUST bound total in-flight runtime executions across all rvw processes on one host with a file-lock slot gate shared through a host-local slot directory, defaulting to 12 slots. The cap MUST be configurable via `RVW_HOST_CONCURRENCY`, where `0` disables the gate and a non-integer or negative value MUST be rejected before runtime execution. Slots MUST be released when the owning execution completes, fails, or its process terminates, and a slot root that is a symlink or foreign-owned MUST fail closed. On cancellation or another exceptional unwind, the entire spawned runtime process group MUST be terminated, with escalation to `SIGKILL` after a bounded grace period, and the wrapper MUST be reaped before its host slot can be released. A `SIGKILL` escalation MUST be recorded in the run log. On Linux, each spawned runtime wrapper MUST request a parent-death `SIGTERM`, applied exec-side by the command wrapper, so a runtime child does not outlive the rvw process whose slot the kernel released. Linux execution MUST fail closed with a clear runtime error when the required `setpriv` executable is unavailable. This child-lifetime coupling is not guaranteed on non-Linux platforms.

The gate MUST require atomic `O_NOFOLLOW` support and fail at construction when it is unavailable. The ambient parent selected from `XDG_RUNTIME_DIR` MUST be validated without changing its permissions or rejecting group and other permission bits. Each rvw-owned slot directory (`rvw-slots` and `c{cap}`), including a pre-existing directory, MUST be set to mode 0700 and re-verified through its opened descriptor before use. Slot files MUST be opened relative to the validated slot-directory descriptor while that descriptor remains open for acquisition, and descriptor-based validation MUST fail closed if ownership or directory type is unsafe, or if an rvw-owned directory's normalized mode is unsafe.

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

#### Scenario: Cancellation terminates the runtime process tree

- **GIVEN** a runtime wrapper has spawned a runtime child while holding a host slot
- **WHEN** execution is cancelled and the child does not exit during the graceful termination period
- **THEN** the runtime process group is sent `SIGKILL`, the escalation is recorded in the run log, and no process in the group outlives the host slot

#### Scenario: Ambient runtime directory has permissive permissions

- **WHEN** an owner-matched `XDG_RUNTIME_DIR` has group or other permissions
- **THEN** the gate validates it without changing those permissions and remains usable

#### Scenario: Existing rvw-owned slot directory has permissive permissions

- **WHEN** an owner-matched `rvw-slots` or `c{cap}` directory already exists with group or other permissions
- **THEN** the gate sets it to mode 0700 and verifies that mode through the opened directory descriptor before acquiring a slot

#### Scenario: Validated slot directory path is replaced

- **WHEN** a slot acquisition begins after the slot-directory descriptor has been validated
- **THEN** every candidate slot file is opened relative to that held descriptor rather than by re-resolving the validated path

#### Scenario: Atomic symlink protection is unavailable

- **WHEN** the platform does not expose `O_NOFOLLOW`
- **THEN** host-slot gate construction fails with a clear runtime error before any slot path is used
