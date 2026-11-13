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


if __name__ == "__main__":
    unittest.main()
