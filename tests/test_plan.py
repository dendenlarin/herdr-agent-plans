"""Tests for hook/plan.py. Run from the repo root: python3 -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "mods", "agent-plans", "hook", "plan.py")
sys.path.insert(0, os.path.dirname(HOOK))
from plan import parse_markdown_plan  # noqa: E402


def stages(text):
    return [s["text"] for s in parse_markdown_plan(text)[1]]


class Parse(unittest.TestCase):
    def test_explicit_stages_and_verification(self):
        text = "# T\n## Context\n- c\n## Step 1. Schema\n- a\n## Notes\n## Step 2. API\n## Verification\n- v\n"
        self.assertEqual(stages(text), ["Step 1. Schema", "Step 2. API", "Verification"])
        text = "# T\n## Контекст\n## Этап 1. Схема\n## Этап 2. API\n## Проверка\n"
        self.assertEqual(stages(text), ["Этап 1. Схема", "Этап 2. API", "Проверка"])

    def test_sections_without_explicit_stages(self):
        self.assertEqual(stages("# T\n## Context\n## Schema\n## API\n"), ["Schema", "API"])

    def test_container_heading_expands(self):
        for container in ("Steps", "Шаги"):
            with self.subTest(container):
                text = f"# T\n## Context\n## {container}\n### 1. A\n- a\n### 2. B\n"
                self.assertEqual(stages(text), ["1. A", "2. B"])

    def test_code_blocks_are_skipped(self):
        text = "# T\n## Step 1. Run\n```\n## Step 9. Not a stage\n- not a point\n```\n- point\n"
        self.assertEqual(parse_markdown_plan(text)[1],
                         [{"text": "Step 1. Run", "status": "pending", "items": ["point"]}])

    def test_numbered_list_without_headings(self):
        self.assertEqual(stages("# T\n1. First.\n2. Second\n"), ["First", "Second"])


class Hook(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.plans = os.path.join(self.home.name, "data", "agent-plans")
        self.env = {**os.environ, "HERDR_APP_HOME": self.home.name, "HC_TERMINAL_ID": "t1"}

    def tearDown(self):
        self.home.cleanup()

    def run_hook(self, event):
        r = subprocess.run([sys.executable, HOOK, "claude"], input=json.dumps(event),
                           capture_output=True, text=True, env=self.env, check=True)
        return r.stdout

    def test_approved_plan_lists_parsed_stages(self):
        out = self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "ExitPlanMode", "session_id": "s",
                             "tool_input": {"plan": "# T\n## Step 1. Schema\n## Step 2. API\n"}})
        text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1. Step 1. Schema\n2. Step 2. API\n", text)
        self.assertIn(" set --title ", text)
        self.assertIn(" next", text)

    def test_old_plans_are_pruned(self):
        os.makedirs(self.plans)
        old, fresh = os.path.join(self.plans, "t9.json"), os.path.join(self.plans, "t8.json")
        for path in (old, fresh):
            with open(path, "w") as f:
                f.write("{}")
        week_ago = time.time() - 8 * 86400
        os.utime(old, (week_ago, week_ago))
        self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "TodoWrite", "session_id": "s",
                       "tool_input": {"todos": [{"content": "a", "status": "pending"}]}})
        self.assertEqual(sorted(n for n in os.listdir(self.plans) if n.endswith(".json")), ["t1.json", "t8.json"])

    def plan(self):
        with open(os.path.join(self.plans, "t1.json")) as f:
            return [s["status"] for s in json.load(f)["steps"]]

    def cli(self, *args):
        return subprocess.run([sys.executable, HOOK, *args], capture_output=True, text=True,
                              env=self.env, check=True).stdout

    def approve(self, session="s"):
        self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "ExitPlanMode", "session_id": session,
                       "tool_input": {"plan": "# T\n## Step 1. A\n## Step 2. B\n## Verification\n"}})

    def test_stop_finishes_only_the_last_open_stage(self):
        self.approve()
        stop = {"hook_event_name": "Stop", "session_id": "s"}
        self.run_hook(stop)  # stage 1 still open: nothing to finish
        self.assertEqual(self.plan(), ["in_progress", "pending", "pending"])
        self.cli("next"), self.cli("next")
        self.run_hook({**stop, "session_id": "other"})  # another session's Stop leaves it alone
        self.assertEqual(self.plan(), ["completed", "completed", "in_progress"])
        self.run_hook(stop)
        self.assertEqual(self.plan(), ["completed", "completed", "completed"])

    def test_stop_leaves_todos_alone(self):
        self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "TodoWrite", "session_id": "s",
                       "tool_input": {"todos": [{"content": "a", "status": "in_progress"}]}})
        self.run_hook({"hook_event_name": "Stop", "session_id": "s"})
        self.assertEqual(self.plan(), ["in_progress"])

    def test_codex_stop_finishes_last_stage(self):
        run = lambda e: subprocess.run([sys.executable, HOOK, "codex"], input=json.dumps(e), text=True,
                                       env=self.env, check=True)
        run({"hook_event_name": "Stop", "session_id": "s",
             "last_assistant_message": "<proposed_plan>\n# T\n## Step 1. A\n## Step 2. B\n</proposed_plan>"})
        self.cli("next")
        run({"hook_event_name": "Stop", "session_id": "s2", "last_assistant_message": "Done."})
        self.assertEqual(self.plan(), ["completed", "completed"])

    def test_done_and_toggle(self):
        self.approve()
        self.env.pop("HC_TERMINAL_ID")
        self.cli("--terminal", "t1", "toggle", "1")  # the current stage done, the next one current
        self.assertEqual(self.plan(), ["completed", "in_progress", "pending"])
        self.cli("--terminal", "t1", "toggle", "1")  # back to not done; stage 2 stays current
        self.assertEqual(self.plan(), ["pending", "in_progress", "pending"])
        self.cli("--terminal", "t1", "done")
        self.assertEqual(self.plan(), ["completed", "completed", "completed"])
        self.cli("--terminal", "t1", "toggle", "3")  # reopened last stage becomes current
        self.assertEqual(self.plan(), ["completed", "completed", "in_progress"])
        self.cli("--terminal", "t1", "clear")
        self.assertFalse(os.path.exists(os.path.join(self.plans, "t1.json")))


class Connect(unittest.TestCase):
    def test_older_hook_set_is_outdated(self):
        import plan
        with tempfile.TemporaryDirectory() as d:
            plan.CLAUDE_CFG = os.path.join(d, "settings.json")
            plan.CODEX_HOME, plan.CODEX_CFG = d, os.path.join(d, "config.toml")
            plan.claude_set(True), plan.codex_set(True)
            st = plan.hook_status()
            self.assertTrue(st["claude"]["connected"] and st["codex"]["connected"])
            self.assertFalse(st["claude"]["outdated"] or st["codex"]["outdated"])
            with open(plan.CLAUDE_CFG) as f:
                cfg = json.load(f)
            del cfg["hooks"]["Stop"]  # as connected before Stop was added
            with open(plan.CLAUDE_CFG, "w") as f:
                json.dump(cfg, f)
            self.assertTrue(plan.hook_status()["claude"]["outdated"])
            plan.claude_set(True)
            self.assertFalse(plan.hook_status()["claude"]["outdated"])

    def test_codex_tables_inside_our_markers_survive(self):
        import plan
        with tempfile.TemporaryDirectory() as d:
            plan.CODEX_HOME, plan.CODEX_CFG = d, os.path.join(d, "config.toml")
            with open(plan.CODEX_CFG, "w") as f:
                f.write('model = "x"\n')
            plan.codex_set(True)
            with open(plan.CODEX_CFG) as f:
                text = f.read()
            # Codex rewrites its config and appends its own tables before our end marker.
            foreign = '[hooks.state]\n\n[mcp_servers.repl]\ncommand = "node"\n'
            text = text.replace(plan.CODEX_END, foreign + plan.CODEX_END)
            with open(plan.CODEX_CFG, "w") as f:
                f.write(text)
            self.assertFalse(plan.hook_status()["codex"]["outdated"])
            plan.codex_set(False)
            with open(plan.CODEX_CFG) as f:
                text = f.read()
            self.assertNotIn(plan.MARK, text)
            self.assertNotIn(plan.CODEX_END, text)
            self.assertIn('model = "x"', text)
            self.assertIn('[mcp_servers.repl]\ncommand = "node"', text)


if __name__ == "__main__":
    unittest.main()
