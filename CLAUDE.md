# Notes for Claude

Work on pywr-next (pywr 2.x) support is recorded in
[docs/claude/pywr-next-dialect.md](docs/claude/pywr-next-dialect.md): the branches and
worktrees, the decisions made, the architecture map, verified pywr-next facts, how to run
the tests, open issues and a log of every commit with its decisions. **Read it first
instead of re-reading the codebase.**

Rules while working on this branch (`pywr-next-dialect`, PR #42):

- Every commit adds its entry (hash, issue, decisions) to section 9 of that file, in the
  same commit, and updates sections 3, 7 and 8 when they change.
- Do not touch `/home/stephen/git/pywr/editor` (the user's `dark-mode` checkout with
  uncommitted work). Work in `/home/stephen/git/pywr/editor-next`.
- Run tests with `QT_QPA_PLATFORM=offscreen`.
- Every commit also updates the memory note `project_pywr_next_dialect.md` (and its
  `MEMORY.md` line). A Claude Code hook (`~/.claude/hooks/worklog-commit-guard.sh`) blocks
  `git commit` here until both the work log and the memory note are updated; it affects
  no other repository.
