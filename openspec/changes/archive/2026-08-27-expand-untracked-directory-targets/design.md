## Decision

Keep the correction inside `target.py`, the sole owner of uncommitted target
construction. A helper expands a status path only when it is a directory,
returns sorted regular non-symlink files relative to the target worktree, and
then reuses the existing `_untracked_diff` renderer for every file. This
preserves ordinary untracked-file and binary behavior while making directory
status entries reviewable.

The top-level directory itself is replaced in `changed_paths` by its concrete
file members. Predicates therefore see the source files that will actually
reach prompts instead of a directory placeholder.
