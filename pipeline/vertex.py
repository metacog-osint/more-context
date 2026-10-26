"""Vertex AI (Gemini) client for story coding, plus a dry-run cost estimate.

Vertex AI is the only model provider for MORE CONTEXT. Every billable call needs Tom's approval, so
`Coder.generate` refuses to run without an explicit spend cap and stops once the running cost (from
Vertex's own usage counts) reaches it. `estimate_*` make no network calls.

Auth: on Cloud Run, the metadata server's token for the function's service account; locally,
`gcloud auth print-access-token`. Tokens are held in memory only and never logged.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import coding

PRICES = Path(__file__).resolve().parent.parent / "catalog" / "vertex_prices.json"
PROJECT = "context-484804"
DEFAULT_MODEL = "gemini-3.1-flash-lite"
ENDPOINT = ("https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/"
            "publishers/google/models/{model}:generateContent")
OUTPUT_TOKENS_PER_STORY = 140  # planning figure for one coding; calibrate on the first approved sample


class SpendNotApproved(RuntimeError):
    pass


def load_prices(path: Path = PRICES) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["models"]


def estimate_tokens(text: str) -> int:
    """Rough token count with no API call: ~4 ASCII chars per token, ~1 per CJK/Hangul/Kana char,
    ~2.5 per other non-ASCII char, plus 10%. Expect +-30%; Vertex's countTokens (free) can calibrate it."""
    n = 0.0
    for ch in text:
        if ord(ch) < 128:
            n += 0.25
        else:
            name = unicodedata.name(ch, "")
            n += 1.0 if name.startswith(("CJK", "HANGUL", "HIRAGANA", "KATAKANA")) else 0.4
    return int(n * 1.1) + 1


def cost(tokens_in: float, tokens_out: float, model: str = DEFAULT_MODEL, batch: bool = False,
         prices: dict | None = None) -> float:
    p = (prices or load_prices())[model]
    pin, pout = (p["batch_input"], p["batch_output"]) if batch else (p["input"], p["output"])
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout


@dataclass
class Plan:
    """What a coding run would send: one request per chunk of stories for one entity."""
    requests: list[dict] = field(default_factory=list)  # {"entity", "story_ids", "prompt"}
    system: str = ""

    @property
    def stories(self) -> int:
        return sum(len(r["story_ids"]) for r in self.requests)

    def tokens(self, thinking_per_request: int = 0) -> tuple[int, int]:
        sys_t = estimate_tokens(self.system)
        schema_t = estimate_tokens(json.dumps(coding.RESPONSE_SCHEMA))
        tin = sum(sys_t + schema_t + estimate_tokens(r["prompt"]) for r in self.requests)
        tout = self.stories * OUTPUT_TOKENS_PER_STORY + len(self.requests) * thinking_per_request
        return tin, tout


def plan_coding(stories: list[dict], catalog: dict, per_request: int = 25,
                charters: dict[str, list[dict]] | None = None) -> Plan:
    """Group stories by entity and chunk them into requests. Stories need story_id, entity, title."""
    entities = {e["id"]: e for e in catalog["zones"] + catalog["topics"]}
    others_of = {eid: [o for o in entities.values() if o["id"] != eid] for eid in entities}
    by_entity: dict[str, list[dict]] = {}
    for s in stories:
        by_entity.setdefault(s["entity"], []).append(s)
    plan = Plan(system=coding.instructions())
    for eid, group in sorted(by_entity.items()):
        for chunk in coding.chunks(group, per_request):
            plan.requests.append({
                "entity": eid,
                "story_ids": [s["story_id"] for s in chunk],
                "prompt": coding.build_prompt(entities[eid], chunk, others_of[eid], (charters or {}).get(eid)),
            })
    return plan


def request_body(system: str, prompt: str, stories: int, thinking_level: str | None = None) -> dict:
    gen = {
        "temperature": 0,
        "maxOutputTokens": stories * 220 + 512,
        "responseMimeType": "application/json",
        "responseSchema": coding.RESPONSE_SCHEMA,
    }
    if thinking_level:
        gen["thinkingConfig"] = {"thinkingLevel": thinking_level}
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
    }


def parse_response(resp: dict) -> tuple[dict | None, dict, str]:
    """(parsed JSON answer or None, usage counts, finish reason). Thought parts are skipped."""
    usage = resp.get("usageMetadata") or {}
    counts = {"in": usage.get("promptTokenCount", 0), "out": usage.get("candidatesTokenCount", 0),
              "thinking": usage.get("thoughtsTokenCount", 0)}
    cands = resp.get("candidates") or []
    if not cands:
        return None, counts, "NO_CANDIDATES"
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    try:
        return json.loads(text), counts, cands[0].get("finishReason", "")
    except json.JSONDecodeError:
        return None, counts, cands[0].get("finishReason", "") or "BAD_JSON"


def access_token() -> str:
    if os.environ.get("K_SERVICE"):  # Cloud Run
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["access_token"]
    gcloud = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not gcloud:
        raise RuntimeError("gcloud not found; run `gcloud auth login` first")
    out = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError("gcloud auth print-access-token failed; run `gcloud auth login`")
    return out.stdout.strip()


def _post(url: str, body: dict, token: str, timeout: float = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class Coder:
    """Runs a Plan against Vertex under a hard spend cap (USD, from Vertex's reported token counts)."""

    def __init__(self, model: str = DEFAULT_MODEL, project: str = PROJECT, spend_cap_usd: float | None = None,
                 thinking_level: str | None = None, transport=None, token_fn=access_token, prices: dict | None = None):
        if not spend_cap_usd or spend_cap_usd <= 0:
            raise SpendNotApproved("Vertex calls need an approved spend cap (spend_cap_usd > 0)")
        self.model, self.project, self.cap = model, project, spend_cap_usd
        self.thinking_level = thinking_level
        self.transport = transport or _post
        self.token_fn = token_fn
        self.prices = prices or load_prices()
        self.spent = 0.0
        self.usage = {"in": 0, "out": 0, "thinking": 0, "requests": 0}

    def run(self, plan: Plan, charter_ids: dict[str, set[str]] | None = None, pause_s: float = 0.5):
        """Yield (request, codings, problems) per request; stop before a request once the cap is reached."""
        token, token_at = None, 0.0
        url = ENDPOINT.format(project=self.project, model=self.model)
        for req in plan.requests:
            if self.spent >= self.cap:
                yield req, [], [f"stopped: spend cap ${self.cap:.2f} reached"]
                return
            if token is None or time.time() - token_at > 2400:
                token, token_at = self.token_fn(), time.time()
            body = request_body(plan.system, req["prompt"], len(req["story_ids"]), self.thinking_level)
            try:
                resp = self.transport(url, body, token)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                yield req, [], [f"HTTP {e.code}: {detail}"]
                if e.code in (400, 401, 403, 404):
                    return  # a setup problem; repeating it would only fail again
                continue
            answer, counts, finish = parse_response(resp)
            self.usage["requests"] += 1
            for k in ("in", "out", "thinking"):
                self.usage[k] += counts[k]
            self.spent += cost(counts["in"], counts["out"] + counts["thinking"], self.model, prices=self.prices)
            if answer is None:
                yield req, [], [f"no usable answer (finish {finish})"]
            else:
                codings, problems = coding.validate(answer, req["story_ids"], (charter_ids or {}).get(req["entity"]))
                if finish and finish != "STOP":
                    problems.append(f"finish reason {finish}")
                yield req, [{**c, "entity": req["entity"], "model": self.model} for c in codings], problems
            time.sleep(pause_s)
