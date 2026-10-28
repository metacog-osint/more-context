"""Cloud Run function entry points.

- `ingest`: one 15-minute ingest cycle into the MC_BUCKET bucket. Deployed private; Cloud Scheduler calls it
  with an OIDC token. Codes alarm-triggered entity-days when MC_AI=on.
- `api`: the public read API with on-view coding under the monthly AI cap (pipeline/api.py). Deployed
  as its own function (`mc-api`), open to anyone.
"""
import json
import os
import time

import functions_framework

from pipeline import api as api_handler
from pipeline import instance
from pipeline.cycle import run_cycle
from pipeline.sinks import GCSSink

_sink = None


def _get_sink():
    global _sink
    if _sink is None:
        _sink = GCSSink(os.environ["MC_BUCKET"])
    return _sink


@functions_framework.http
def ingest(request):
    started = time.time()
    summary = run_cycle(_get_sink())
    summary["elapsed_s"] = round(time.time() - started, 1)
    # Searches refused: stop this instance once the response is out, so the next run gets a new address.
    summary["restart_instance"] = instance.restart_if_refused(summary)
    print(json.dumps({"severity": "INFO", "message": "mc-ingest cycle", "summary": summary}))
    return json.dumps(summary), 200, {"Content-Type": "application/json"}


@functions_framework.http
def api(request):
    headers = {"Content-Type": "application/json", **api_handler.CORS}
    if request.method == "OPTIONS":
        return "", 204, headers
    body = request.get_json(silent=True) if request.method == "POST" else None
    status, out = api_handler.handle(request.method, request.path, dict(request.args), body, _get_sink())
    if request.method == "POST":
        print(json.dumps({"severity": "INFO", "message": "mc-api code", "status": status,
                          "result": {k: out.get(k) for k in ("entity", "day", "coded", "cost_usd", "error")}}))
    return json.dumps(out, ensure_ascii=False), status, headers
