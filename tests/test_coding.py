import json
import unittest

from pipeline import coding, vertex
from pipeline.match import load_catalog


def good(sid, **kw):
    c = {"story_id": sid, "relevance": "on", "event_type": "ASSAULT", "direction": "escalating",
         "indicator_ids": [], "frame": "military_action", "confidence": "moderate", "gist": "Strike reported",
         "killed": 3, "wounded": None}
    c.update(kw)
    return c


class CodingTests(unittest.TestCase):
    def test_plover_has_18_types_in_four_quads(self):
        self.assertEqual(len(coding.QUAD_OF), 18)
        self.assertEqual(coding.EVENT_TYPES[-1], "NONE")
        self.assertEqual(set(coding.EVENT_HELP), set(coding.EVENT_TYPES))

    def test_validate_keeps_good_and_reports_bad(self):
        answer = {"stories": [good("a"), good("b", event_type="BOMBING"), good("a"), good("z"), good("c", killed=-1)]}
        out, problems = coding.validate(answer, ["a", "b", "c", "d"])
        self.assertEqual([c["story_id"] for c in out], ["a"])
        self.assertEqual(out[0]["quad"], "material_conflict")
        joined = " | ".join(problems)
        for text in ("b: bad event_type", "repeated story_id 'a'", "story_id 'z'", "c: bad killed", "3 stories not coded"):
            self.assertIn(text, joined)

    def test_validate_drops_unknown_indicator_ids(self):
        out, problems = coding.validate({"stories": [good("a", indicator_ids=["UKR-W01", "MADE-UP"])]}, ["a"], {"UKR-W01"})
        self.assertEqual(out[0]["indicator_ids"], ["UKR-W01"])
        self.assertTrue(any("dropped indicator" in p for p in problems))

    def test_prompt_carries_profile_and_headline(self):
        cat = load_catalog()
        ent = cat["zones"][0]
        p = coding.build_prompt(ent, [{"story_id": "s1", "title": "Удар по Харкову", "languages": ["ukr"], "outlets": 2}],
                                cat["zones"][1:3])
        self.assertIn(ent["profile"], p)
        self.assertIn('"headline": "Удар по Харкову"', p)
        self.assertIn("Indicators: none yet", p)
        self.assertIn("ASSAULT: use of force", coding.instructions())


class VertexTests(unittest.TestCase):
    def test_token_estimate_counts_scripts_differently(self):
        self.assertLess(vertex.estimate_tokens("a" * 400), vertex.estimate_tokens("乌" * 400))

    def test_plan_chunks_by_entity(self):
        stories = [{"story_id": f"s{i}", "entity": "01_Ukraine_Conflict", "title": "x"} for i in range(30)]
        stories.append({"story_id": "t", "entity": "13_Sudan", "title": "y"})
        plan = vertex.plan_coding(stories, load_catalog(), per_request=25)
        self.assertEqual([len(r["story_ids"]) for r in plan.requests], [25, 5, 1])
        self.assertEqual(plan.stories, 31)

    def test_request_body_uses_schema(self):
        b = vertex.request_body("sys", "prompt", 10, thinking_level="minimal")
        g = b["generationConfig"]
        self.assertEqual(g["responseSchema"], coding.RESPONSE_SCHEMA)
        self.assertEqual(g["thinkingConfig"], {"thinkingLevel": "minimal"})
        self.assertNotIn("thinkingConfig", vertex.request_body("s", "p", 1)["generationConfig"])

    def test_parse_skips_thought_parts(self):
        resp = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "thinking...", "thought": True}, {"text": json.dumps({"stories": []})}]}}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 5}}
        ans, counts, finish = vertex.parse_response(resp)
        self.assertEqual(ans, {"stories": []})
        self.assertEqual(counts, {"in": 100, "out": 20, "thinking": 5})
        self.assertEqual(finish, "STOP")

    def test_coder_needs_a_cap(self):
        with self.assertRaises(vertex.SpendNotApproved):
            vertex.Coder(spend_cap_usd=None)
        with self.assertRaises(vertex.SpendNotApproved):
            vertex.Coder(spend_cap_usd=0)

    def test_coder_stops_at_cap_and_counts_thinking(self):
        stories = [{"story_id": f"s{i}", "entity": "13_Sudan", "title": "RSF drone strike"} for i in range(4)]
        plan = vertex.plan_coding(stories, load_catalog(), per_request=1)
        calls = []

        def fake(url, body, token):
            calls.append(url)
            sid = json.loads(body["contents"][0]["parts"][0]["text"].splitlines()[-1])["story_id"]
            return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({"stories": [good(sid)]})}]}}],
                    "usageMetadata": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 0, "thoughtsTokenCount": 0}}

        coder = vertex.Coder(spend_cap_usd=0.5, transport=fake, token_fn=lambda: "tok",
                             prices={"gemini-3.1-flash-lite": {"input": 0.25, "output": 1.5, "batch_input": 0, "batch_output": 0}})
        results = list(coder.run(plan, pause_s=0))
        self.assertEqual(len(calls), 2)  # $0.25 each; the third request is refused at $0.50
        self.assertIn("spend cap", results[-1][2][0])
        self.assertEqual(results[0][1][0]["entity"], "13_Sudan")
        self.assertIn("locations/global/publishers/google/models/gemini-3.1-flash-lite:generateContent", calls[0])


if __name__ == "__main__":
    unittest.main()
