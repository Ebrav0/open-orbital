# Git and agent workflow

The repository root is `/Users/emmanuelbravo/Desktop/Open Orbital`.
Git records source snapshots locally. The first commit captures revision 3 as it exists now; it cannot reconstruct earlier agents’ edit history. No remote repository is configured.

## What is tracked

Application and benchmark source, local Three.js assets and license, requirements, helper scripts, documentation, and existing benchmark/test evidence are tracked. Installed runtimes, downloaded build sources, node_modules, live simulation data, caches, logs, and local environment secrets are ignored. Ignoring a file does not delete it.

Git is not a backup of experiments. Preserve `work/observatory-data/` separately, including frames, configurations, metadata, archived sources, and matching checkpoint pairs. A fresh clone needs its runtime rebuilt using HANDOFF.md; it does not contain the installed Python environment.

## Before an agent edits

```sh
cd "/Users/emmanuelbravo/Desktop/Open Orbital"
git status --short
git log -5 --oneline
```

Read AGENTS.md and HANDOFF.md. Preserve any uncommitted work from another agent. Use a descriptive branch for an independent change, for example `git switch -c fix/diagnostic-refresh`, only after understanding existing changes. Agents sharing this directory also share its checked-out branch; switching branches changes files for everyone. Use separate Git worktrees for concurrent work, with separate runtimes/data and ports as needed.

## Save a completed change

Review `git diff`, run checks appropriate to the change, update HANDOFF.md with results and unresolved issues, and stage only the files you intended to change:

```sh
git add path/to/changed-file
git diff --cached --stat
git diff --cached
git commit -m "Describe the concrete change"
git status --short
```

The path above is a placeholder. Do not stage unrelated changes or overwrite historical benchmark evidence. Name the acting agent/tool in the handoff when useful; commit author identity alone does not identify the agent.

## Inspect earlier code safely

```sh
git log --oneline
git show HEAD:outputs/observatory/worker.py
git diff HEAD -- outputs/observatory/worker.py
```

`git show` reads an earlier snapshot without changing working files. For an intentional rollback, review and use `git revert <commit>` to create a new reversing commit. Avoid destructive reset/clean commands, especially `git clean -fdx`, which can delete ignored simulation data and runtimes. Coordinate source changes with a running server; never restart or overwrite an active experiment merely to change Git branches.

## Cursor and remote backup

Open the repository root in Cursor; its Source Control panel uses this same local history. A GitHub remote is optional and has not been created. Local commits protect against code-edit mistakes, but a separate backup or remote is needed for disk-loss protection.
