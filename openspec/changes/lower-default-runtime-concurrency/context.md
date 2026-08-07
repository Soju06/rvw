# Runtime concurrency change context

On 2026-08-06, concurrent rvw runs saturated the `codex-lb` account pool. The local `account_stream_cap` admission limit triggered overload responses and 30-second retry sleeps, and some lane runs became INVALID before useful work completed.

The operational decision is to reduce the per-process runtime concurrency default from 16 to 8 while preserving an explicit positive override for operators who know the available account capacity. This limits discovery, adjudication, sampling, and stack-presence waves; it does not change replica counts, retry policy, model selection, schemas, or the external registry.
