"""Story coding: what Gemini is asked to say about each story, and how its answer is checked.

One request codes up to `per_request` stories for one zone or topic, so the instructions are paid once per
batch, not once per story. The model sees only what MORE CONTEXT has: a representative headline (any
language), the languages and outlet count, and the source groups. It must code only what the headline
states. Nothing in this module calls Vertex; see pipeline/vertex.py.

Event types are PLOVER's 18 (draft v0.8, https://github.com/openeventdata/PLOVER), with quads assigned
locally, plus NONE for stories that report no event (analysis, profiles, markets, history).
"""
from __future__ import annotations

import json

SCHEMA_VERSION = "code-v0.1"

QUADS = {
    "verbal_cooperation": ["AGREE", "CONSULT", "SUPPORT", "CONCEDE"],
    "material_cooperation": ["COOPERATE", "AID", "RETREAT", "INVESTIGATE"],
    "verbal_conflict": ["DEMAND", "DISAPPROVE", "REJECT", "THREATEN", "SANCTION"],
    "material_conflict": ["PROTEST", "CRIME", "MOBILIZE", "COERCE", "ASSAULT"],
}
QUAD_OF = {t: q for q, ts in QUADS.items() for t in ts}
EVENT_TYPES = [t for ts in QUADS.values() for t in ts] + ["NONE"]

# One line each, summarised from the PLOVER v0.8 draft for the prompt.
EVENT_HELP = {
    "AGREE": "agree to or sign an agreement, ceasefire or deal",
    "CONSULT": "meet, visit, hold talks or calls",
    "SUPPORT": "praise, endorse or state support",
    "CONCEDE": "yield in words: accept terms, offer a concession, apologise",
    "COOPERATE": "act jointly: joint exercises or operations, information sharing",
    "AID": "provide humanitarian, military or economic aid",
    "RETREAT": "withdraw forces, release detainees, ease restrictions",
    "INVESTIGATE": "open or conduct an investigation, inquiry or trial",
    "DEMAND": "demand or call for an action",
    "DISAPPROVE": "criticise, accuse or condemn",
    "REJECT": "refuse a proposal, demand or agreement",
    "THREATEN": "threaten force, sanctions or other harm",
    "SANCTION": "impose sanctions, embargoes, expulsions or cut ties",
    "PROTEST": "demonstrations, rallies, strikes",
    "CRIME": "criminal acts outside armed conflict",
    "MOBILIZE": "deploy or mobilise forces, raise alert levels, hold drills alone",
    "COERCE": "arrests, seizures, blockades, repression, forced displacement",
    "ASSAULT": "use of force: strikes, shelling, drone or missile attacks, fighting, killings",
    "NONE": "no event: analysis, opinion, profile, markets, history",
}
RELEVANCE = ["on", "off", "unclear"]
DIRECTION = ["escalating", "de-escalating", "neutral"]
FRAMES = ["military_action", "civilian_harm", "blame_adversary", "diplomacy", "legal_accountability",
          "security_threat", "domestic_politics", "economic_impact", "other"]
ACTOR_KINDS = ["government", "military", "armed_group", "civilians", "international_org", "ngo_or_media",
               "business", "other"]
CONFIDENCE = ["low", "moderate", "high"]

_ACTOR = {
    "type": "OBJECT", "nullable": True,
    "properties": {
        "name": {"type": "STRING"},
        "country": {"type": "STRING", "nullable": True, "description": "ISO 3166-1 alpha-3, or null"},
        "kind": {"type": "STRING", "enum": ACTOR_KINDS},
    },
    "required": ["name", "kind"],
}
_STORY = {
    "type": "OBJECT",
    "properties": {
        "story_id": {"type": "STRING"},
        "relevance": {"type": "STRING", "enum": RELEVANCE},
        "belongs_to": {"type": "STRING", "nullable": True, "description": "another entity id, when the story is about that one instead"},
        "event_type": {"type": "STRING", "enum": EVENT_TYPES},
        "source_actor": _ACTOR,
        "target_actor": _ACTOR,
        "place": {"type": "STRING", "nullable": True},
        "country": {"type": "STRING", "nullable": True, "description": "ISO 3166-1 alpha-3 of the place, or null"},
        "direction": {"type": "STRING", "enum": DIRECTION},
        "killed": {"type": "INTEGER", "nullable": True},
        "wounded": {"type": "INTEGER", "nullable": True},
        "casualty_source": {"type": "STRING", "nullable": True, "description": "who the headline says gave the figure"},
        "indicator_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
        "frame": {"type": "STRING", "enum": FRAMES},
        "confidence": {"type": "STRING", "enum": CONFIDENCE},
        "gist": {"type": "STRING", "description": "the headline's claim in plain English, 25 words or fewer"},
    },
    "required": ["story_id", "relevance", "event_type", "direction", "indicator_ids", "frame", "confidence", "gist"],
}
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"stories": {"type": "ARRAY", "items": _STORY}},
    "required": ["stories"],
}

INSTRUCTIONS = """You code news stories for a conflict-monitoring system that uses publicly available reporting.
Each story is one representative headline, in any language, that an automatic rule assigned to the zone or
topic below. The rule is often wrong, so judge relevance first.

Rules:
- Use only what the headline states. Do not add facts from memory or guess at article text.
- relevance: "on" if the story is about the zone's conflict, security or political-military situation (for a
  topic: about that strategic theme, not a company's routine business); "off" if the place or term is incidental
  or the subject is something else (domestic politics elsewhere, business, sport, entertainment, crime, weather,
  history); "unclear" if the headline cannot settle it. If the story is about another listed entity, give its id
  in belongs_to.
- event_type: the main event the headline reports, one of:
{events}
  Use NONE when the headline reports no event. Code off-topic stories too, briefly.
- source_actor does the action; target_actor receives it. Use null when the headline names no one.
- direction: relative to this zone's conflict. escalating = adds force, threat or hostility; de-escalating =
  talks, ceasefire, withdrawal, release, aid; neutral = neither or not an event.
- killed / wounded: only numbers the headline states, else null. Never estimate. casualty_source: who the
  headline credits for the figure, else null.
- indicator_ids: only ids from the indicator list below that the headline clearly reports; [] if none or no list.
- frame: how the headline presents the event.
- confidence: your confidence in this coding, given only a headline: low, moderate or high.
- gist: the headline's claim in plain English, 25 words or fewer, neutral wording.
- Return every story, in the order given, with its story_id unchanged."""


def instructions() -> str:
    events = "\n".join(f"  {t}: {EVENT_HELP[t]}" for t in EVENT_TYPES)
    return INSTRUCTIONS.format(events=events)


def entity_block(entity: dict, others: list[dict], indicators: list[dict] | None = None) -> str:
    lines = [f"Zone or topic: {entity['id']} ({entity['name']})", f"Scope: {entity.get('profile', '')}"]
    if indicators:
        lines.append("Indicators:")
        lines += [f"  {i['id']}: {i['text']}" for i in indicators]
    else:
        lines.append("Indicators: none yet")
    lines.append("Other entities (for belongs_to): " + "; ".join(f"{o['id']} ({o['name']})" for o in others))
    return "\n".join(lines)


def story_line(s: dict) -> dict:
    """The fields the model sees for one story."""
    return {
        "story_id": s["story_id"],
        "headline": s.get("title") or "",
        "languages": s.get("languages", []),
        "outlets": s.get("outlets"),
        "groups": sorted(s.get("groups") or {}),
    }


def build_prompt(entity: dict, stories: list[dict], others: list[dict], indicators: list[dict] | None = None) -> str:
    body = "\n".join(json.dumps(story_line(s), ensure_ascii=False) for s in stories)
    return f"{entity_block(entity, others, indicators)}\n\nStories (one JSON object per line):\n{body}"


def chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def validate(answer: dict, story_ids: list[str], indicator_ids: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """Keep well-formed codings for the requested stories; list every problem found."""
    problems, out = [], []
    got = answer.get("stories") if isinstance(answer, dict) else None
    if not isinstance(got, list):
        return [], ["no stories array"]
    wanted = set(story_ids)
    seen = set()
    enums = {"relevance": RELEVANCE, "event_type": EVENT_TYPES, "direction": DIRECTION, "frame": FRAMES,
             "confidence": CONFIDENCE}
    for c in got:
        sid = c.get("story_id") if isinstance(c, dict) else None
        if sid not in wanted or sid in seen:
            problems.append(f"unexpected or repeated story_id {sid!r}")
            continue
        bad = [k for k, allowed in enums.items() if c.get(k) not in allowed]
        for k in ("killed", "wounded"):
            v = c.get(k)
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                bad.append(k)
        if bad:
            problems.append(f"{sid}: bad {', '.join(bad)}")
            continue
        ids = [i for i in c.get("indicator_ids") or [] if indicator_ids and i in indicator_ids]
        if len(ids) != len(c.get("indicator_ids") or []):
            problems.append(f"{sid}: dropped indicator ids not in the charter")
        seen.add(sid)
        out.append({**c, "indicator_ids": ids, "quad": QUAD_OF.get(c["event_type"]), "schema": SCHEMA_VERSION})
    missing = wanted - seen
    if missing:
        problems.append(f"{len(missing)} stories not coded")
    return out, problems
