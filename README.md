# Open Orbital

This folder is the complete local project. Open this folder in Cursor or another agent's editor.

## Start here

1. Read **HANDOFF.md** and **AGENTS.md** before changing anything.
2. From any Terminal window, type **`Start OpenOrbital`** (new shells after this setup). That reuses a healthy server on port 8766, or starts one, then opens the Compute dashboard in your default browser. Alternatives: `Start-OpenOrbital`, double-click **Start Open Orbital.command**, or `sh outputs/observatory/run.sh`.
3. Compute is http://127.0.0.1:8766/lab ; Observe is http://127.0.0.1:8766 . If the server is already running, the command only opens the browser.
4. Read **outputs/observatory/README.md** for features, physics limitations and test results.

The application source is in `outputs/observatory/`. The unusual `outputs/` and `work/` layout was retained to preserve the working runtime, benchmark history, and saved experiments during relocation. Everything is now physically in this Desktop folder. The old Codex directory contains compatibility symlinks only.

Do not move source files independently without updating the root-relative paths in the launcher and server. This virtual environment and native library are specific to this Mac; see HANDOFF.md for rebuilding.

## Version history

This folder is a local Git repository. See **outputs/GIT_GUIDE.md** for the agent workflow, tracked files, and backup boundaries. Open this folder in Cursor to use its Source Control panel.
