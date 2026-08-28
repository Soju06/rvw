# Bounded discovery retry and scope context

This change implements only deterministic safety controls supported by existing
runtime artifacts. It does not select cheaper runtime profiles because the
required golden-set comparison has not occurred. The actual registry remains
outside this repository and is not modified here.

An all-invalid retry previously re-sent a full lane/chunk replica wave for
timeouts and cancellation-shaped failures. The 2026-08-27 incident showed that
unfinished sessions dominated cost, so an identical retry is not an acceptable
default for non-correctable failures.
