import json
import unittest
from unittest.mock import patch

from app import agent_blocks, orchestrator, report_skill
from app.tools import Toolbox, specs_for


class Trace:
    def __init__(self, calls, missing=None):
        self.calls = calls
        self.missing = missing or []


class Store:
    def metric_facet(self, _term):
        return "style"

    def latest_day(self):
        return "2026-09-10"

    def top_terms(self, facet=None, limit=10, facets=None):
        return [{"canonical": "고프코어", "facet": "style", "temp": 82,
                 "raw_count": 120}]


class Gate:
    def facet_of(self, _term):
        return "style"


NODE = {
    "available": True, "canonical": "고프코어", "facet_name": "스타일",
    "temp": 82, "temp_band": "높음", "raw_count": 120, "pct_rank": 91,
    "sources": [], "associations": [], "evidence": [],
}


def design(modules, **overrides):
    spec = {
        "title": "고프코어 흐름", "accent": "violet", "surface": "soft",
        "density": "airy", "modules": modules,
    }
    spec.update(overrides)
    return {"tool": "compose_report", "args": spec,
            "result": {"ok": True, "skill": "generative-report-v1", "spec": spec}}


class ReportSkillTest(unittest.TestCase):
    def test_compose_report_is_exposed_as_an_orchestrator_tool(self):
        self.assertIn("compose_report", [s.get("name") for s in specs_for({})])

    def test_tool_sanitizes_design_without_accepting_html(self):
        box = Toolbox(Store(), Gate())
        out = box.t_compose_report(
            "<script>긴 제목</script>", "unknown", "paper", "balanced",
            [{"kind": "metric", "term": "고프코어", "presentation": "hero",
              "span": 99, "emphasis": "strong"},
             {"kind": "made-up", "term": None, "presentation": "card",
              "span": 6, "emphasis": "normal"}],
        )
        self.assertEqual(out["spec"]["accent"], "coral")
        self.assertEqual(out["spec"]["modules"][0]["span"], 12)
        self.assertEqual(len(out["spec"]["modules"]), 1)

    def test_canvas_follows_model_composition_not_named_variant(self):
        catalog = [
            {"id": "metric:고프코어", "kind": "metric", "term": "고프코어",
             "block": {"type": "rank", "rows": []}},
            {"id": "direction:고프코어", "kind": "direction", "term": "고프코어",
             "block": {"type": "kpis", "items": []}},
        ]
        trace = Trace([design([
            {"kind": "direction", "term": "고프코어", "presentation": "hero",
             "span": 8, "emphasis": "strong"},
            {"kind": "metric", "term": "고프코어", "presentation": "list",
             "span": 4, "emphasis": "quiet"},
        ])])
        canvas = report_skill.build(catalog, trace)
        self.assertEqual(canvas["type"], "generative_report")
        self.assertNotIn("variant", canvas)
        self.assertEqual([m["kind"] for m in canvas["modules"]], ["direction", "metric"])
        self.assertEqual([m["span"] for m in canvas["modules"]], [8, 4])

    def test_unknown_content_reference_is_not_invented(self):
        catalog = [{"id": "metric:고프코어", "kind": "metric", "term": "고프코어",
                    "block": {"type": "rank", "rows": []}}]
        trace = Trace([design([{"kind": "metric", "term": "없는상품",
                                "presentation": "hero", "span": 12,
                                "emphasis": "strong"}])])
        canvas = report_skill.build(catalog, trace)
        self.assertEqual(canvas["source"], "fallback")
        self.assertEqual(canvas["modules"][0]["id"], "metric:고프코어")

    def test_missing_data_cannot_be_hidden_by_design(self):
        catalog = [
            {"id": "metric:고프코어", "kind": "metric", "term": "고프코어",
             "block": {"type": "rank", "rows": []}},
            {"id": "missing:고프코어:0", "kind": "missing", "term": "고프코어",
             "block": {"type": "note", "text": "가격 자료 없음"}},
        ]
        trace = Trace([design([{"kind": "metric", "term": "고프코어",
                                "presentation": "hero", "span": 12,
                                "emphasis": "strong"}])])
        canvas = report_skill.build(catalog, trace)
        self.assertEqual([m["kind"] for m in canvas["modules"]], ["metric", "missing"])

    def test_layout_numbers_do_not_become_verified_facts(self):
        box = Toolbox(Store(), Gate())
        box.run("compose_report", {
            "title": "보기", "accent": "coral", "surface": "paper",
            "density": "balanced", "modules": [{"kind": "metric", "term": "고프코어",
            "presentation": "hero", "span": 12, "emphasis": "strong"}]})
        self.assertNotIn("12", box.trace.numbers())

    @patch("app.orchestrator.llm.respond")
    def test_orchestrator_enforces_design_before_releasing_prepared_answer(self, respond):
        report_args = {
            "title": "지금 뜨는 흐름", "accent": "coral", "surface": "paper",
            "density": "balanced", "modules": [{"kind": "ranking", "term": None,
            "presentation": "hero", "span": 12, "emphasis": "strong"}],
        }
        respond.side_effect = [
            {"_raw": {"output": [{"type": "function_call", "call_id": "c1",
              "name": "rank_terms", "arguments": json.dumps({"facet": None, "limit": 5})}]},
             "text": ""},
            {"_raw": {"output": [{"type": "message"}]}, "text": "고프코어가 가장 높아요."},
            {"_raw": {"output": [{"type": "function_call", "call_id": "c2",
              "name": "compose_report", "arguments": json.dumps(report_args, ensure_ascii=False)}]},
             "text": ""},
        ]
        result = orchestrator.run("요즘 뭐가 핫해?", store=Store(), gate=Gate())
        self.assertEqual(result.answer, "고프코어가 가장 높아요.")
        self.assertIn("compose_report", [c["tool"] for c in result.trace.calls])
        self.assertEqual(respond.call_count, 3)

    @patch("app.agent_blocks.report.build_term", return_value=NODE)
    def test_agent_blocks_binds_only_real_metric_to_generated_canvas(self, _build):
        calls = [
            {"tool": "get_metric", "args": {"term": "고프코어", "axes": ["온도"]},
             "result": {"term": "고프코어", "has_metric": True, "as_of": "2026-09-10"}},
            design([{"kind": "metric", "term": "고프코어", "presentation": "hero",
                     "span": 12, "emphasis": "strong"}]),
        ]
        blocks = agent_blocks.build(Trace(calls), Store(), Gate())
        self.assertEqual(blocks[0]["type"], "generative_report")
        self.assertEqual(blocks[0]["source"], "model")
        self.assertEqual(blocks[0]["modules"][0]["block"]["type"], "rank")


if __name__ == "__main__":
    unittest.main()
