#!/usr/bin/env python3
"""Agent Plans for Herdr: hook and CLI that keep each agent's plan in one JSON file.

Hooks (JSON on stdin, always exit 0, never block the agent):
  plan.py claude   Claude Code: PostToolUse(ExitPlanMode|TodoWrite|TaskCreate|TaskUpdate),
                   TaskCreated, TaskCompleted
  plan.py codex    Codex: Stop (<proposed_plan> in the last message), UserPromptSubmit,
                   PostToolUse(update_plan)

CLI for agents (the terminal comes from $HC_TERMINAL_ID):
  plan.py next                      current stage done, the next one becomes current
  plan.py mark <n> done|doing|todo  set stage n (from 1)
  plan.py set --title "T" "doing:step" "todo:step" ...
  plan.py clear
  plan.py show

Connecting the hooks (used by the Plan panel's agent chips):
  plan.py status                    {"claude": {"present", "connected"}, "codex": {...}}
  plan.py connect claude|codex      add the hooks (backup: <config>.bak-agent-plans)
  plan.py disconnect claude|codex   remove exactly these hooks

Data: $HERDR_APP_HOME (default ~/.config/herdr-app) /data/agent-plans/<terminal>.json
Debug log of raw hook input: set AGENT_PLANS_DEBUG=1 -> data/agent-plans/.log/events.jsonl
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOME = os.environ.get("HERDR_APP_HOME") or os.path.expanduser("~/.config/herdr-app")
PLANS = os.path.join(HOME, "data", "agent-plans")
LOG = os.path.join(PLANS, ".log", "events.jsonl")
LOG_KEEP = 200
SELF = os.path.abspath(__file__)

# Every status maps to one of three words.
STATUS = {
    "pending": "pending", "todo": "pending", "open": "pending",
    "in_progress": "in_progress", "doing": "in_progress", "active": "in_progress",
    "completed": "completed", "done": "completed", "complete": "completed",
}


# ---------- storage ----------

def terminal():
    """The hc terminal address. Without it the agent is not running in Herdr: nowhere to show a plan."""
    t = os.environ.get("HC_TERMINAL_ID")
    return t.replace("/", "_") if t else None


def codex_terminal(data):
    """Codex terminal without HC_TERMINAL_ID: Codex runs hooks in a shared background app-server, not a process
    in the terminal. Look for live Codex terminals in the same folder; if several, the one whose title
    matches the thread name. Ambiguous -> None (better no plan than someone else's)."""
    hc = shutil.which("hc") or os.path.expanduser("~/.local/bin/hc")
    run = lambda *a: json.loads(subprocess.run([hc, *a, "--json"], capture_output=True, text=True, timeout=3).stdout)
    cwd = os.path.realpath(data.get("cwd") or "")
    found = []
    for t in run("ls").get("terminals", []):
        if "/" in t["address"] or t.get("state") != "live" or t.get("agent") != "codex":
            continue
        info = run("get", t["address"])
        fg = (info.get("foreground") or {}).get("cwd") or info.get("cwd") or ""
        if os.path.realpath(fg) == cwd:
            found.append(info)
    if len(found) == 1:
        return found[0]["address"]
    name = thread_name(data)
    # Title like "⠏ <thread name> | <project>"; the name may be cut short.
    title = lambda t: norm(re.sub(r"^\W+", "", (t.get("title") or "").split(" | ")[0]))
    match = [t for t in found if name and len(title(t)) >= 8 and (name.startswith(title(t)) or title(t).startswith(name))]
    if len(match) != 1:
        # A new thread may have no name yet; the hook runs mid-turn, so the terminal is working.
        match = [t for t in found if (t.get("status") or {}).get("state") == "working"]
    return match[0]["address"] if len(match) == 1 else None


def thread_name(data):
    """Codex thread name by session id from <CODEX_HOME>/session_index.jsonl (last entry)."""
    tp = data.get("transcript_path") or ""
    home = tp.split(os.sep + "sessions" + os.sep)[0] if os.sep + "sessions" + os.sep in tp else os.path.expanduser("~/.codex")
    name = None
    try:
        with open(os.path.join(home, "session_index.jsonl"), encoding="utf-8") as f:
            for line in f:
                if data.get("session_id", "-") in line:
                    name = json.loads(line).get("thread_name") or name
    except Exception:
        pass
    return norm(name) if name else None


def path_for(key):
    return os.path.join(PLANS, key + ".json")


def load(key):
    try:
        with open(path_for(key), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save(key, plan):
    os.makedirs(PLANS, exist_ok=True)
    plan["terminal"] = key
    plan["updated"] = int(time.time() * 1000)
    # Atomic write: the panel never sees half a file.
    fd, tmp = tempfile.mkstemp(dir=PLANS, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path_for(key))


def debug_log(kind, data):
    if not os.environ.get("AGENT_PLANS_DEBUG"):
        return
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        lines = []
        if os.path.exists(LOG):
            with open(LOG, encoding="utf-8") as f:
                lines = f.readlines()[-(LOG_KEEP - 1):]
        lines.append(json.dumps({"t": int(time.time()), "src": kind, "hc": os.environ.get("HC_TERMINAL_ID"),
                                 "data": data}, ensure_ascii=False) + "\n")
        with open(LOG, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except Exception:
        pass


def as_obj(v):
    """tool_input / tool_response may arrive as a JSON string."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v if isinstance(v, (dict, list)) else {}


def emit_context(event, text):
    """Add a hint to the agent's context (Claude and Codex read the same format)."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def reminder(app):
    cmd = f'python3 "{SELF}" next'
    if app == "codex":
        return ("Herdr Agent Plans shows this approved plan's stages in the Plan panel. "
                "Track progress with your update_plan tool, using the stage names from the plan, "
                f"and mark a stage completed as soon as it is done. If update_plan is unavailable, run: {cmd}")
    return ("Herdr Agent Plans shows this approved plan's stages in the Plan panel. "
            f"Each time you finish a stage, immediately run: {cmd}  "
            "(marks the current stage done and starts the next one).")


# ---------- markdown plan parsing ----------

# Plan sections that are not work stages.
SKIP_SECTIONS = ("context", "контекст", "background", "предыстория", "итог", "summary", "вопросы",
                 "questions", "риски", "risks", "ссылки", "links", "notes", "заметки", "overview", "обзор")
STAGE = re.compile(r"^(этап|шаг|фаза|часть|step|phase|stage|part|milestone)\b|^\d+[.)]?\s", re.I)
VERIFY = re.compile(r"^(проверка|верификация|тест|verification|verify|testing|validation|test plan)", re.I)


def clean(s):
    return re.sub(r"\*\*|`|(?<![\w])_|_(?![\w])", "", s).strip()


def short(item):
    """"**Lead.** details..." -> "Lead"; else up to the end of the sentence or ";", at most 110."""
    m = re.match(r"^\*\*(.+?)\*\*", item)
    if m:
        return clean(m.group(1)).rstrip(".:")
    t = clean(item)
    t = re.split(r"(?<=[.!?])\s|;\s", t, maxsplit=1)[0].rstrip(".")
    return t if len(t) <= 110 else t[:107].rstrip() + "…"


def parse_markdown_plan(text):
    """Title: the first "# ". Stages: "## " headings minus service sections; if there are explicit
    stages ("Step 1", "Phase 2", "3. ..."), only those and the verification section stay. A stage's points are
    its top-level list. Without "## ", stages come from the numbered list."""
    title, sections, numbered, cur = "", [], [], None
    for line in (text or "").splitlines():
        m = re.match(r"^#\s+(.+)", line)
        if m and not title:
            title = m.group(1).strip()
            continue
        m = re.match(r"^##\s+(.+)", line)
        if m:
            cur = {"head": m.group(1).strip(), "items": []}
            sections.append(cur)
            continue
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.+)", line)  # top-level item, not indented
        if m:
            if cur is not None:
                cur["items"].append(m.group(1).strip())
            elif re.match(r"^\d", line):
                numbered.append(m.group(1).strip())
    work = [s for s in sections
            if not s["head"].lower().startswith(SKIP_SECTIONS)
            and not any(w in s["head"].lower() for w in ("context", "контекст"))]
    if any(STAGE.match(s["head"]) for s in work):
        work = [s for s in work if STAGE.match(s["head"]) or VERIFY.match(s["head"])]
    if work:
        steps = [{"text": clean(s["head"]), "status": "pending", "items": [short(i) for i in s["items"][:12]]}
                 for s in work[:20]]
    else:
        steps = [{"text": short(n), "status": "pending", "items": []} for n in numbered[:20]]
    return clean(title), steps


def plan_from_markdown(key, app, session, text, source):
    title, steps = parse_markdown_plan(text)
    if not steps:
        return False
    steps[0]["status"] = "in_progress"
    save(key, {"app": app, "session": session, "source": source, "title": title, "steps": steps})
    return True


def norm(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


# ---------- Codex ----------

PROPOSED = re.compile(r"<proposed_plan>\s*\n(.*?)\n\s*</proposed_plan>", re.S)
# An approved Codex plan starts a new thread with this message and the full plan text.
IMPLEMENT = "A previous agent produced the plan below"


def codex_needs_terminal(data):
    """Look up the terminal only for events that write something: Stop only with a plan in it."""
    if data.get("hook_event_name") == "Stop":
        return bool(PROPOSED.search(data.get("last_assistant_message") or ""))
    return True


def from_codex(data, key):
    event = data.get("hook_event_name")
    session = data.get("session_id")

    if event == "Stop":
        # Codex Plan Mode returns the plan to approve as a <proposed_plan> block in its last message.
        m = PROPOSED.findall(data.get("last_assistant_message") or "")
        if m:
            plan_from_markdown(key, "codex", session, m[-1], "plan-mode")
        return

    if event == "UserPromptSubmit":
        prompt = data.get("prompt") or ""
        if IMPLEMENT in prompt[:400]:
            # Thread that implements an approved plan: the plan is in the message itself.
            plan_from_markdown(key, "codex", session, prompt, "plan-mode")
        # First prompt after the plan: remind once how to mark stages.
        # The plan is keyed by terminal: Codex starts a new thread with a new id to implement it.
        plan = load(key)
        if (plan and plan.get("app") == "codex"
                and plan.get("source") == "plan-mode" and not plan.get("reminded")
                and any(s["status"] != "completed" for s in plan["steps"])):
            plan["reminded"] = True
            save(key, plan)
            emit_context("UserPromptSubmit", reminder("codex"))
        return

    if data.get("tool_name") == "update_plan":
        inp = as_obj(data.get("tool_input"))
        new = [{"text": s.get("step", ""), "status": STATUS.get(s.get("status"), "pending")}
               for s in inp.get("plan", []) if isinstance(s, dict)]
        if not new:
            return
        old = load(key) or {}
        if old.get("app") == "codex" and old.get("steps"):
            # Stages match the Plan Mode plan: copy statuses only, keep the points.
            by_name = {norm(s["text"]): s for s in old["steps"]}
            if all(norm(s["text"]) in by_name for s in new):
                for s in new:
                    by_name[norm(s["text"])]["status"] = s["status"]
                save(key, old)
                return
        save(key, {"app": "codex", "session": session, "source": "update_plan",
                   "title": old.get("title", "") if old.get("app") == "codex" else "",
                   "note": inp.get("explanation") or "", "steps": new})


# ---------- Claude Code ----------

def from_claude(data, key):
    event = data.get("hook_event_name")
    tool = data.get("tool_name")
    session = data.get("session_id")
    inp = as_obj(data.get("tool_input"))
    resp = as_obj(data.get("tool_response"))
    old = load(key) or {}
    if old.get("session") != session:
        old = {}  # new session in the same terminal: start the plan over

    if tool == "ExitPlanMode":
        # Approved plan: markdown in tool_input.plan, else the file at planFilePath.
        text = inp.get("plan") or ""
        path = inp.get("planFilePath") or find_key(resp, "planFilePath") or find_key(resp, "filePath")
        if not text and path:
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                pass
        if plan_from_markdown(key, "claude-code", session, text, "plan-mode"):
            emit_context("PostToolUse", reminder("claude"))
        return

    if tool == "TodoWrite":
        steps = [{"text": t.get("content", ""), "status": STATUS.get(t.get("status"), "pending"),
                  "active": t.get("activeForm")} for t in inp.get("todos", []) if isinstance(t, dict)]
        save(key, {"app": "claude-code", "session": session, "source": "todos",
                   "title": old.get("title", ""), "steps": steps})
        return

    # Task tools: TaskCreate / TaskUpdate and the TaskCreated / TaskCompleted events.
    if old.get("source") not in (None, "tasks"):
        old = {"title": old.get("title", "")}  # don't mix tasks with a plan-mode plan
    tasks = old.get("tasks", {})
    if tool == "TaskCreate" or event == "TaskCreated":
        text = inp.get("subject") or data.get("task_subject") or ""
        tid = find_id(resp) or data.get("task_id")
        if not tid:
            # One task can arrive twice (event and PostToolUse): without an id, merge by text.
            tid = next((k for k, v in tasks.items() if v.get("text") == text), None) \
                or max([int(k) for k in tasks if k.isdigit()] or [0]) + 1
        tid = str(tid)
        prev = tasks.get(tid, {})
        tasks[tid] = {"text": text or prev.get("text", ""), "status": prev.get("status", "pending"),
                      "active": inp.get("activeForm") or prev.get("active")}
    elif tool == "TaskUpdate" or event == "TaskCompleted":
        tid = str(inp.get("taskId") or inp.get("task_id") or data.get("task_id") or "")
        if not tid:
            return
        t = tasks.setdefault(tid, {"text": "", "status": "pending"})
        status = "completed" if event == "TaskCompleted" else inp.get("status")
        if status == "deleted":
            tasks.pop(tid, None)
        else:
            if status:
                t["status"] = STATUS.get(status, t["status"])
            for src, dst in (("subject", "text"), ("activeForm", "active")):
                if inp.get(src):
                    t[dst] = inp[src]
            if data.get("task_subject") and not t["text"]:
                t["text"] = data["task_subject"]
    else:
        return
    order = sorted(tasks, key=lambda k: (not k.isdigit(), int(k) if k.isdigit() else 0, k))
    save(key, {"app": "claude-code", "session": session, "source": "tasks", "title": old.get("title", ""),
               "tasks": tasks, "steps": [dict(tasks[k], id=k) for k in order]})


def find_key(obj, name):
    if isinstance(obj, dict):
        if isinstance(obj.get(name), str):
            return obj[name]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            r = find_key(v, name)
            if r:
                return r
    return None


def find_id(obj):
    """Id of the created task in the tool response (the format is undocumented)."""
    if isinstance(obj, dict):
        for k in ("taskId", "task_id", "id"):
            if isinstance(obj.get(k), (str, int)) and str(obj[k]).strip():
                return obj[k]
        for v in obj.values():
            r = find_id(v)
            if r:
                return r
    return None


# ---------- connecting hooks ----------

HOOK_CMD = ('P="${HERDR_APP_HOME:-$HOME/.config/herdr-app}/mods/agent-plans/hook/plan.py"; '
            '[ -f "$P" ] && python3 "$P" %s || true')
MARK = "agent-plans/hook/plan.py"
CLAUDE_CFG = os.path.expanduser("~/.claude/settings.json")
CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
CODEX_CFG = os.path.join(CODEX_HOME, "config.toml")
CODEX_BEGIN, CODEX_END = "# >>> agent-plans (Herdr Agent Plans)", "# <<< agent-plans"
CLAUDE_EVENTS = {"PostToolUse": "ExitPlanMode|TodoWrite|TaskCreate|TaskUpdate", "TaskCreated": None, "TaskCompleted": None}
CODEX_EVENTS = {"Stop": None, "UserPromptSubmit": None, "PostToolUse": "^update_plan$"}


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_with_backup(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and not os.path.exists(path + ".bak-agent-plans"):
        shutil.copy2(path, path + ".bak-agent-plans")
    tmp = path + ".tmp-agent-plans"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def hook_status():
    return {
        "claude": {"present": os.path.isdir(os.path.dirname(CLAUDE_CFG)), "connected": MARK in read(CLAUDE_CFG)},
        "codex": {"present": os.path.isdir(CODEX_HOME), "connected": MARK in read(CODEX_CFG)},
    }


def claude_set(on):
    text = read(CLAUDE_CFG)
    cfg = json.loads(text) if text.strip() else {}
    hooks = cfg.setdefault("hooks", {})
    # Remove our entries first (if any); leave everyone else's alone.
    for event in list(hooks):
        groups = [g for g in hooks[event] if MARK not in json.dumps(g)]
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if on:
        for event, matcher in CLAUDE_EVENTS.items():
            group = {"hooks": [{"type": "command", "command": HOOK_CMD % "claude", "timeout": 5}]}
            if matcher:
                group = {"matcher": matcher, **group}
            hooks.setdefault(event, []).append(group)
    if not hooks:
        del cfg["hooks"]
    write_with_backup(CLAUDE_CFG, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def codex_set(on):
    text = read(CODEX_CFG)
    # Our block strictly between the markers; the rest of the config stays as is.
    text = re.sub(r"\n*" + re.escape(CODEX_BEGIN) + r".*?" + re.escape(CODEX_END) + r"\n?", "\n", text, flags=re.S)
    if on:
        cmd = HOOK_CMD % "codex"
        block = [CODEX_BEGIN]
        for event, matcher in CODEX_EVENTS.items():
            block += [f"[[hooks.{event}]]"] + ([f'matcher = "{matcher}"'] if matcher else [])
            block += [f"[[hooks.{event}.hooks]]", 'type = "command"', f"command = '{cmd}'", "timeout = 5", ""]
        block[-1] = CODEX_END
        text = text.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
    write_with_backup(CODEX_CFG, text)


# ---------- CLI ----------

def cli(argv):
    cmd = argv[0] if argv else ""
    key = terminal()
    if cmd in ("", "-h", "--help", "help"):
        print(__doc__)
        return
    if cmd == "status":
        print(json.dumps(hook_status()))
        return
    if cmd in ("connect", "disconnect") and len(argv) == 2 and argv[1] in ("claude", "codex"):
        (claude_set if argv[1] == "claude" else codex_set)(cmd == "connect")
        print(json.dumps(hook_status()))
        return
    if not key:
        sys.exit("agent-plans: HC_TERMINAL_ID is not set; run this inside a Herdr terminal")
    if cmd == "clear":
        try:
            os.remove(path_for(key))
        except FileNotFoundError:
            pass
        return
    if cmd == "show":
        print(json.dumps(load(key), ensure_ascii=False, indent=1))
        return
    if cmd == "set":
        title, steps, rest = "", [], argv[1:]
        while rest:
            a = rest.pop(0)
            if a == "--title" and rest:
                title = rest.pop(0)
                continue
            st, sep, text = a.partition(":")
            if not sep or st.strip() not in STATUS:
                st, text = "todo", a
            steps.append({"text": text.strip(), "status": STATUS[st.strip()], "items": []})
        old = load(key) or {}
        save(key, {"app": old.get("app") or "agent", "session": old.get("session"), "source": "manual",
                   "title": title, "steps": steps})
        return
    plan = load(key)
    if not plan or not plan.get("steps"):
        sys.exit("agent-plans: no plan for this terminal yet")
    steps = plan["steps"]
    if cmd == "next":
        cur = next((i for i, s in enumerate(steps) if s["status"] == "in_progress"), None)
        if cur is not None:
            steps[cur]["status"] = "completed"
        nxt = next((i for i, s in enumerate(steps) if s["status"] == "pending"), None)
        if nxt is not None:
            steps[nxt]["status"] = "in_progress"
    elif cmd == "mark" and len(argv) >= 3 and argv[1].isdigit() and argv[2] in STATUS:
        i = int(argv[1]) - 1
        if not 0 <= i < len(steps):
            sys.exit(f"agent-plans: stage {argv[1]} does not exist (1..{len(steps)})")
        steps[i]["status"] = STATUS[argv[2]]
    else:
        sys.exit(__doc__)
    save(key, plan)
    done = sum(s["status"] == "completed" for s in steps)
    print(f"agent-plans: {done}/{len(steps)} done")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode in ("codex", "claude"):
        try:
            data = json.loads(sys.stdin.read() or "{}")
            debug_log(mode, data)
            if mode == "claude":
                key = terminal()
                if key:
                    from_claude(data, key)
            elif codex_needs_terminal(data):
                key = terminal() or codex_terminal(data)
                if key:
                    from_codex(data, key)
        except Exception as e:  # a hook must never break the agent
            debug_log(mode + "-error", {"error": repr(e)})
        sys.exit(0)
    cli(sys.argv[1:])


if __name__ == "__main__":
    main()
