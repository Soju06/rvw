## ADDED Requirements

### Requirement: Runtime-executing commands expose a no-output timeout

The `review`, `run`, `auto`, `gate`, and `stack review` commands MUST expose `--no-output-timeout`, MUST reject values below 1 or above 1800 before runtime execution, MUST fall back to `RVW_NO_OUTPUT_SECONDS` and then to 660 seconds when the option is omitted, MUST reject a present environment value that is not a positive integer before any runtime work (finalizing `process.json` as `invalid_configuration` with exit 2 for `run` and `auto`, and exiting 2 as a user error otherwise), and MUST propagate the effective value to every discovery, adjudication, expanded, and stack-presence runtime they start. `run` and `auto` MUST record the effective value in `process.json` under `runtime.no_output_seconds`, in the canonical command as `--no-output-timeout <seconds>`, and in `environment.txt`.

#### Scenario: Default is recorded

- **WHEN** `rvw run` is invoked without `--no-output-timeout` and without `RVW_NO_OUTPUT_SECONDS`
- **THEN** every runtime it starts uses a 660-second watchdog and `process.json` records `runtime.no_output_seconds: 660`

#### Scenario: Explicit option is recorded

- **WHEN** `rvw run` is invoked with `--no-output-timeout 120`
- **THEN** every runtime it starts uses 120 seconds, the canonical command contains `--no-output-timeout 120`, and `environment.txt` contains `no_output_seconds=120`

#### Scenario: Environment supplies the value

- **WHEN** `review`, `run`, `auto`, `gate`, or `stack review` is invoked without the option while `RVW_NO_OUTPUT_SECONDS` is `90`
- **THEN** every runtime it starts uses a 90-second watchdog

#### Scenario: Environment value is malformed

- **WHEN** `RVW_NO_OUTPUT_SECONDS` is `bad` or `0`
- **THEN** `run` and `auto` finalize `process.json` with `invalid_configuration` and exit 2, and `review`, `gate`, and `stack review` exit 2 naming the variable before any runtime work

#### Scenario: Operator supplies zero

- **WHEN** `review`, `run`, `auto`, `gate`, or `stack review` is invoked with `--no-output-timeout 0` or `--no-output-timeout 1801`
- **THEN** CLI validation rejects the invocation before any runtime work starts
