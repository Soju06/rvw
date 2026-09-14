# Design

The controller derives `scope` from the already parsed three-dot hunks. `changed` means `hunk_for_line` succeeds, `unchanged_in_file` means the file is present in the diff but the line is outside every hunk, and `outside_diff` means the file is absent. File-level findings use changed when their file is in the diff and outside_diff otherwise. A collapse group takes the strongest member scope in the order changed, unchanged_in_file, outside_diff.

The model-facing `Severity` enum remains unchanged. A controller-only `EffectiveSeverity` adds informational severity for demoted findings. Raw severity remains audit provenance. `demotion_reason` is exactly `unchanged_in_file` or `outside_diff`; changed findings have no demotion. Legacy artifacts without scope evidence default to changed. Optional base-history disclosure is omitted so missing refs remain fail-open.
