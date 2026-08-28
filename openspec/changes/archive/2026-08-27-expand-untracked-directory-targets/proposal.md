## Why

`rvw review --target uncommitted` reads every `??` status entry as a text file.
Git may report an untracked directory such as an OpenSpec archive directory,
causing `Path.read_text()` to raise `IsADirectoryError` before planning or
reviewing the actual changes.

## What Changes

- Expand each untracked directory into sorted regular files below the worktree.
- Include those files in both the uncommitted diff and `changed_paths`.
- Do not follow symlinks while expanding an untracked directory.

## Non-Goals

- Changing tracked-diff handling, PR/commit targets, or binary-file rendering.
- Reviewing ignored files or paths outside the worktree.
