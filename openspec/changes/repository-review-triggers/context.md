The owner measured clawroid/bori release PR #1772 being reviewed 22 times, once per bot push; #1743, #1749, #1751, and #1753 showed the same noise. Repository conventions are policy in `.rvw/`, so consumers name their own bot logins rather than rvw shipping a bot denylist. The packaged default therefore contains no bot logins and preserves today's behavior with an empty denylist and draft skipping.

Python and Worker policy fixtures are kept in `tests/fixtures/trigger-policy.json`; the
Worker test imports the same JSON through the repository's fixture copy used by parity
tests so parser and matcher behavior stays aligned.
