# Agent Plans for Herdr

Your coding agent's plan, right beside it.

Approve a plan in **Claude Code** plan mode or **Codex** Plan Mode, and its stages show up in a **Plan** panel next to Files and Changes: what's done, what the agent is on now, what each stage contains. Each space keeps its own panel open or closed.

No daemon, no plan files in your repos — two small hooks and a panel.

## How it works

| | Plan comes from | Progress |
| --- | --- | --- |
| **Claude Code** | the plan you approve in plan mode (also `TodoWrite`, `TaskCreate` / `TaskUpdate`) | Claude marks each stage done with `plan.py next` |
| **Codex** | the `<proposed_plan>` of Plan Mode (also `update_plan`) | Codex marks stages with its `update_plan` tool |

The hooks remind the agent how to mark stages, once per plan. Plans are tied to the agent's Herdr terminal, so several agents in one repo never mix up.

## Install

Needs Herdr 0.1.13+, `python3`, and Claude Code and/or Codex.

**1. Add the mod.** Ask the agent running in Herdr:

```text
Read ~/.config/herdr-app/AGENTS.md, then add this mod: https://github.com/dendenlarin/herdr-agent-plans
```

Or copy `mods/agent-plans/` to `~/.config/herdr-app/mods/` yourself.

**2. Add the Plan button.** Herdr's own layouts are read-only, so use the included one:

```sh
cp layouts/main-plans.json ~/.config/herdr-app/layouts/
herdr-app do layout.switch '{"name":"main-plans"}'
```

<details>
<summary>Using your own layout instead</summary>

Wrap the `tabs` block in a row with the button:

```json
{ "id": "tab-bar", "type": "row", "size": { "px": 42 }, "resizable": false, "children": [
  { "id": "tabs", "type": "block", "window_drag": true, "content": { "mod": "tabs" } },
  { "id": "plans-button", "type": "block", "size": { "px": 72 }, "window_drag": true,
    "content": { "mod": "agent-plans", "props": { "button": true } } } ] }
```

and add a third child to the `panel-body` stack:

```json
{ "id": "plans", "type": "block", "content": { "mod": "agent-plans" } }
```
</details>

**3. Connect the hooks.** Add the entries below. Each one does nothing if the mod is removed. In Codex, approve them once in `/hooks`.

<details>
<summary>Claude Code — <code>~/.claude/settings.json</code>, inside <code>"hooks"</code></summary>

```json
"PostToolUse": [{ "matcher": "ExitPlanMode|TodoWrite|TaskCreate|TaskUpdate",
  "hooks": [{ "type": "command", "timeout": 5,
    "command": "P=\"${HERDR_APP_HOME:-$HOME/.config/herdr-app}/mods/agent-plans/hook/plan.py\"; [ -f \"$P\" ] && python3 \"$P\" claude || true" }] }],
"TaskCreated":   [{ "hooks": [{ "type": "command", "timeout": 5, "command": "<same command>" }] }],
"TaskCompleted": [{ "hooks": [{ "type": "command", "timeout": 5, "command": "<same command>" }] }]
```
</details>

<details>
<summary>Codex — <code>~/.codex/config.toml</code></summary>

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
</details>

## What it touches

- **Writes** one file per agent terminal: `~/.config/herdr-app/data/agent-plans/<terminal>.json`. Nothing in your repos.
- **Reads** the hook input from Claude Code and Codex. The panel also checks your two agent configs for the hook entries.
- **Tells the agent**, once per plan, how to mark stages.
- No network, no background process.

## Uninstall

Delete the hook entries, `mods/agent-plans/`, `data/agent-plans/` and the layout (or its two blocks).

## Good to know

- Only this computer's agents are shown.
- A stage is marked when the agent says so: if it forgets, the panel lags behind.
- Want a whole-project map instead? See [agenttrail](https://github.com/sodiumsun/agenttrail).

MIT License
