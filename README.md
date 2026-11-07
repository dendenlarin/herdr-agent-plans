# Agent Plans for Herdr

A [Herdr](https://herdr.dev) mod that shows your coding agent's plan beside it. Approve a plan in **Claude Code plan mode** or **Codex Plan Mode**, and its stages appear in a **Plan** panel next to Files and Changes: which stage is done, which one the agent is on, and what each stage contains. One panel per space; Herdr remembers per space whether it is open.

It is deliberately small: no daemon, no `PLAN.md` convention, nothing written to your repositories. Hooks in Claude Code and Codex write one JSON file per terminal; the panel reads those files.

## What you see

- **Plan** button at the right end of the tab bar, after Files and Changes. It opens and closes the Plan panel, like the built-in buttons.
- In the panel, for the shown space:
  - the agent (Claude or Codex, its tab, a status pill: working, needs you, done, idle, closed);
  - the plan's title, `2 of 5` and a progress bar;
  - one card per stage: a green check when done, a spinner on the current one, an empty ring for the rest. One stage is open at a time (the current one by default); click another to open it and fold the previous one. An open stage lists its points;
  - when several agents in the space have plans, chips at the top switch between them; the focused agent is shown by default.
- With no plan yet, the panel says so, and warns when the hooks are not connected.

## Where plans come from

| Agent | Source | Progress |
| --- | --- | --- |
| Claude Code | `ExitPlanMode` (the plan you approve in plan mode); also `TodoWrite` and `TaskCreate`/`TaskUpdate` when your Claude Code has them | Right after approval the hook tells Claude to run `plan.py next` after each stage |
| Codex | The `<proposed_plan>` block Codex prints in Plan Mode, read by the `Stop` hook; also `update_plan` | On the first prompt after the plan, the hook asks Codex to track stages with its `update_plan` tool (stage names match the plan), with `plan.py next` as a fallback |

Stages are the plan's `## ` headings. When the plan has explicit stages (`## Step 1`, `## Phase 2`, `## 3. …`), reference sections (Context, Notes, Risks…) are skipped and the verification section is kept. A stage's points are its top-level list items. Without `## ` headings, the top-level numbered list is used.

Progress depends on the agent: if it forgets to mark a stage, the panel shows the old stage. The plan is tied to the terminal through `HC_TERMINAL_ID`, so two agents in one repository never overwrite each other. Agents started outside Herdr are ignored.

## Install

Requirements: Herdr app 0.1.13 or later, `python3` on `PATH`, Claude Code and/or Codex with hooks.

### 1. The mod

Ask the agent running in Herdr:

```text
Read ~/.config/herdr-app/AGENTS.md, then add this mod: https://github.com/dendenlarin/herdr-agent-plans
```

By hand: copy `mods/agent-plans/` to `~/.config/herdr-app/mods/agent-plans/` and run `herdr-app check ~/.config/herdr-app/mods/agent-plans`.

### 2. The Plan button and panel

Herdr's shipped layouts are read-only, so the mod needs a layout that has its two blocks:

- **Use the included layout**: copy `layouts/main-plans.json` to `~/.config/herdr-app/layouts/` and run `herdr-app do layout.switch '{"name":"main-plans"}'`. It is Herdr's `main` (0.1.13) plus the two blocks below.
- **Or add them to your own layout** (a clone of `main`):
  - wrap the `tabs` block in a row with the button:
    ```json
    { "id": "tab-bar", "type": "row", "size": { "px": 42 }, "resizable": false, "children": [
      { "id": "tabs", "type": "block", "window_drag": true, "content": { "mod": "tabs" } },
      { "id": "plans-button", "type": "block", "size": { "px": 72 }, "window_drag": true,
        "content": { "mod": "agent-plans", "props": { "button": true } } } ] }
    ```
  - add a third child to the `panel-body` stack: `{ "id": "plans", "type": "block", "content": { "mod": "agent-plans" } }`.

The button adds `plans` to the shared `workspace.panels` list, so Herdr's tab bar remembers the open panel per space, as it does for Files and Changes.

### 3. The hooks

These are the only changes outside the mod folder. Each command does nothing if the mod is not installed.

**Claude Code**, `~/.claude/settings.json`, inside `"hooks"`:

```json
"PostToolUse": [{ "matcher": "ExitPlanMode|TodoWrite|TaskCreate|TaskUpdate",
  "hooks": [{ "type": "command", "timeout": 5,
    "command": "P=\"${HERDR_APP_HOME:-$HOME/.config/herdr-app}/mods/agent-plans/hook/plan.py\"; [ -f \"$P\" ] && python3 \"$P\" claude || true" }] }],
"TaskCreated":   [{ "hooks": [{ "type": "command", "timeout": 5, "command": "<same command>" }] }],
"TaskCompleted": [{ "hooks": [{ "type": "command", "timeout": 5, "command": "<same command>" }] }]
```

**Codex**, `~/.codex/config.toml`:

```toml
# Herdr Agent Plans
[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = 'P="${HERDR_APP_HOME:-$HOME/.config/herdr-app}/mods/agent-plans/hook/plan.py"; [ -f "$P" ] && python3 "$P" codex || true'
timeout = 5

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = '<same command>'
timeout = 5

[[hooks.PostToolUse]]
matcher = "^update_plan$"
[[hooks.PostToolUse.hooks]]
type = "command"
command = '<same command>'
timeout = 5
```

Codex runs new hooks only after you trust them: open Codex and review them in `/hooks`.

## What it reads and writes

- **Writes**: `~/.config/herdr-app/data/agent-plans/<terminal>.json` (the plan: title, stages, statuses, points). Nothing in your repositories. With `AGENT_PLANS_DEBUG=1` in the agent's environment, the hook also keeps the last 200 raw hook inputs in `data/agent-plans/.log/events.jsonl` (they can contain prompt and plan text).
- **Reads**: the hook input from Claude Code and Codex (and the plan file Claude Code names, if the plan is not inline). The panel reads the plan files, `~/.claude/settings.json` and `~/.codex/config.toml` (only to check that the hooks are connected), and Herdr's live agent and terminal data.
- **Network**: none. **Programs**: none from the panel; the hooks run `python3`.
- **Agent context**: once per plan, the hook adds one short instruction for marking stages (shown above).

## Agent commands

Agents (or you, in a Herdr terminal) can drive the plan directly:

```sh
P=~/.config/herdr-app/mods/agent-plans/hook/plan.py
python3 $P next                      # current stage done, next one current
python3 $P mark 3 done               # done | doing | todo
python3 $P set --title "Fix login" "doing:Find the cause" "todo:Fix token refresh" "todo:Run tests"
python3 $P show
python3 $P clear
```

Codex's default sandbox may block writes outside the workspace; that is why Codex is asked to use `update_plan` (its hooks run outside the sandbox). To let `plan.py next` work from Codex too, add `~/.config/herdr-app/data/agent-plans` to `sandbox_workspace_write.writable_roots`.

## Uninstall

Remove the hook entries above, the two layout blocks (or `layouts/main-plans.json`), `mods/agent-plans/` and `data/agent-plans/`.

## Compared with agenttrail

[agenttrail](https://github.com/sodiumsun/agenttrail) draws a live map of a whole project from `PLAN.md`, git and agent logs, served by a local Node daemon, with a Herdr mod as one of its views. Agent Plans is narrower: the plan one agent approved, beside that agent, from hooks only.

## Limits

- This computer only: plans of agents on other machines are not shown.
- Codex Plan Mode and `update_plan` are the only Codex sources; a plan written as plain text outside Plan Mode is not picked up.
- Plans of closed terminals stay visible for 30 minutes.

## License

MIT
