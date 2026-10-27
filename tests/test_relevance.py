import json
import tempfile
import unittest
from pathlib import Path

from pipeline import relevance
from pipeline.match import load_catalog


class FoldAndTermTests(unittest.TestCase):
    def test_fold_drops_case_and_accents(self):
        self.assertEqual(relevance.fold("Ucrânia İsrail Vénézuéla"), relevance.fold("ucrania israil venezuela"))

    def test_whole_word_unless_star(self):
        m = relevance.TermMatcher({"Z": ["iran*", "mali"]})
        self.assertTrue(m.hit("Z", "Iranian navy drills"))
        self.assertTrue(m.hit("Z", "Irán responde"))
        self.assertFalse(m.hit("Z", "Miranda wins in Tirana"))  # 'iran' inside a word
        self.assertTrue(m.hit("Z", "Troops in Mali"))
        self.assertFalse(m.hit("Z", "Malibu fire"))  # 'mali' is whole-word only

    def test_multi_word_and_hyphen(self):
        m = relevance.TermMatcher({"T": ["nord stream", "critical mineral*"]})
        self.assertTrue(m.hit("T", "Nord-Stream-Prozess beginnt"))
        self.assertTrue(m.hit("T", "Why critical minerals matter"))
        self.assertFalse(m.hit("T", "Critical thinking about minerals"))

    def test_scripts_without_word_boundaries(self):
        m = relevance.TermMatcher({"A": ["غزة", "乌克兰", "북한*"]})
        self.assertTrue(m.hit("A", "قصف على غزة اليوم"))
        self.assertTrue(m.hit("A", "وفي غزة"))  # Arabic prefix letter attached
        self.assertTrue(m.hit("A", "俄乌克兰谈判"))
        self.assertTrue(m.hit("A", "북한의 미사일 발사"))  # particle after the noun

    def test_unknown_entity_never_hits(self):
        self.assertFalse(relevance.TermMatcher({"A": ["x"]}).hit("B", "x"))

    def test_catalog_terms_compile_and_cover_entities(self):
        m = relevance.TermMatcher()
        cat = load_catalog()
        ids = {e["id"] for e in cat["zones"] + cat["topics"]}
        retired = {r["id"] for r in cat.get("retired", [])}  # kept so older labelled sets still score
        self.assertEqual(set(m.rx), ids | retired)
        self.assertTrue(m.hit("01_Ukraine_Conflict", "Зеленський заявив"))
        self.assertTrue(m.hit("10_Israel_Gaza_Lebanon", "İsrail'de seçim"))


def row(entity, draw, label, articles=1, title="t"):
    return {"id": f"{entity}:{title}", "entity": entity, "draw": draw, "label": label,
            "articles": articles, "title": title, "url": "https://x.com/a"}


class ScoreTests(unittest.TestCase):
    def test_weights_scale_random_draw_to_population(self):
        rows = [row("Z", "top", "on"), row("Z", "random", "off"), row("Z", "random", "on")]
        w = relevance.weights(rows, {"entities": {"Z": {"stories": 21}}})
        self.assertEqual(w, [1.0, 10.0, 10.0])

    def test_precision_retention_weighted(self):
        rows = [row("Z", "top", "on", 5), row("Z", "random", "off"), row("Z", "random", "on"), row("Z", "random", "unclear")]
        w = relevance.weights(rows, {"entities": {"Z": {"stories": 7}}})  # random weight 2
        keep = [True, False, True, True]
        o = relevance.score(rows, w, keep)["overall"]
        self.assertEqual(o["stories"]["precision"], 1.0)   # kept: on 1 + on 2; the off story was dropped
        self.assertEqual(o["stories"]["off_removed"], 1.0)
        self.assertEqual(o["stories"]["retention"], 1.0)
        everything = relevance.score(rows, w, [True] * 4)["overall"]
        self.assertEqual(everything["stories"]["precision"], round(3 / 5, 3))      # on 1+2, off 2
        self.assertEqual(everything["articles"]["precision"], round(7 / 9, 3))     # on 5+2, off 2
        self.assertEqual(everything["unclear_share"], round(2 / 7, 3))

    def test_evaluate_refuses_unlabelled(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "set.jsonl"
            p.write_text(json.dumps(row("Z", "top", None)) + "\n", encoding="utf-8")
            (Path(d) / "set.population.json").write_text(json.dumps({"source": "s", "entities": {"Z": {"stories": 1}}}))
            with self.assertRaises(ValueError):
                relevance.evaluate(p, iters=0)

    def test_model_codings_become_methods(self):
        rows = [row("Z", "top", "on", title="a"), row("Z", "top", "off", title="b"), row("Z", "top", "on", title="c")]
        codings = {"Z:a": {"relevance": "on"}, "Z:b": {"relevance": "on"}, "Z:c": {"relevance": "unclear"}}
        m = relevance.methods(relevance.TermMatcher({"Z": ["zzz"]}), codings)
        self.assertEqual([m["gemini_on"](r) for r in rows], [True, True, False])
        self.assertEqual([m["gemini_on_or_unclear"](r) for r in rows], [True, True, True])
        self.assertEqual(relevance.agreement(rows + [row("Z", "top", "off", title="d")], codings),
                         {"off>missing": 1, "off>on": 1, "on>on": 1, "on>unclear": 1})

    def test_committed_set_is_fully_labelled(self):
        rows, pop = relevance.load_set(Path(__file__).resolve().parent.parent / "catalog" / "eval" / "relevance_v1.jsonl")
        self.assertEqual(len(rows), 278)
        self.assertTrue(all(r["label"] in ("on", "off", "unclear") for r in rows))
        self.assertTrue({r["entity"] for r in rows} <= set(pop["entities"]))


if __name__ == "__main__":
    unittest.main()
