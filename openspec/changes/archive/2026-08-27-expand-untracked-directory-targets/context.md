# Untracked directory target context

The bug was reproduced while preparing an RVW self-review: archived OpenSpec
change directories were untracked and `resolve_target("uncommitted")` attempted
to read the directory itself as UTF-8. The error is target construction, not a
model/runtime failure.
