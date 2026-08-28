## ADDED Requirements

### Requirement: Uncommitted targets expand untracked directories safely

An uncommitted target MUST expand an untracked directory reported by Git into
sorted regular non-symlink files beneath the worktree. Each member MUST appear
in `changed_paths` and be rendered through the ordinary untracked-file diff
path. The resolver MUST not read the directory itself as a text file or follow
symlinks outside the worktree.

#### Scenario: OpenSpec archive directory is untracked

- **WHEN** Git status reports an untracked directory containing Markdown files
- **THEN** the uncommitted target includes each Markdown file in its diff and
  changed paths without raising `IsADirectoryError`
