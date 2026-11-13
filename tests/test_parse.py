"""Plan parsing across languages. Run from the repo root: python3 -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mods", "agent-plans", "hook"))
from plan import parse_markdown_plan  # noqa: E402

# One plan per language: a service section, two explicit stages, a verification section.
PLANS = {
    "en": ("Context", "Step 1. Schema", "Step 2. API", "Verification"),
    "ru": ("Контекст", "Этап 1. Схема", "Этап 2. API", "Проверка"),
    "es": ("Antecedentes", "Paso 1. Esquema", "Paso 2. API", "Verificación"),
    "pt": ("Resumo", "Etapa 1. Esquema", "Etapa 2. API", "Testes"),
    "fr": ("Contexte", "Étape 1. Schéma", "Étape 2. API", "Vérification"),
    "de": ("Hintergrund", "Schritt 1. Schema", "Schritt 2. API", "Überprüfung"),
    "zh": ("背景", "步骤一：数据结构", "步骤二：接口", "验证"),
    "ja": ("概要", "ステップ1：スキーマ", "ステップ2：API", "検証"),
}


def plan(*heads):
    return "# Title\n" + "".join(f"\n## {h}\n- point\n" for h in heads)


def stages(text):
    return [s["text"] for s in parse_markdown_plan(text)[1]]


class Languages(unittest.TestCase):
    def test_explicit_stages(self):
        for lang, (service, s1, s2, verify) in PLANS.items():
            with self.subTest(lang):
                # The overview-like section in between is dropped as a non-stage once stages are explicit.
                self.assertEqual(stages(plan(service, s1, "Notes", s2, verify)), [s1, s2, verify])

    def test_service_sections_without_explicit_stages(self):
        for lang, (service, *_rest) in PLANS.items():
            with self.subTest(lang):
                self.assertEqual(stages(plan(service, "Alpha", "Beta")), ["Alpha", "Beta"])

    def test_cjk_numbering(self):
        self.assertEqual(stages(plan("第一阶段 准备", "第2步 实现", "その他")), ["第一阶段 准备", "第2步 实现"])
        self.assertEqual(stages(plan("1、准备", "2、实现", "其他")), ["1、准备", "2、实现"])


class Traps(unittest.TestCase):
    def test_container_heading_is_not_a_stage(self):
        # "Steps" / "手順" hold the stages one level down.
        for container in ("Steps", "Шаги", "Pasos", "手順", "步骤"):
            with self.subTest(container):
                text = f"# T\n## Context\n- c\n## {container}\n### 1. A\n- a\n### 2. B\n- b\n"
                self.assertEqual(stages(text), ["1. A", "2. B"])

    def test_words_inside_other_words(self):
        # "Partnership", "Phasenplan", "问题修复" (bug fixes) are work, not stages or service sections.
        self.assertEqual(stages(plan("Partnership", "Phasenplan", "问题修复")), ["Partnership", "Phasenplan", "问题修复"])

    def test_code_blocks_are_skipped(self):
        text = "# T\n## Step 1. Run\n```\n## Step 9. Not a stage\n- not a point\n```\n- point\n"
        self.assertEqual(parse_markdown_plan(text)[1], [{"text": "Step 1. Run", "status": "pending", "items": ["point"]}])


if __name__ == "__main__":
    unittest.main()
