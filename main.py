"""Cloud Run function entry point: one 15-minute ingest cycle into the MC_BUCKET Cloud Storage bucket.

Deployed private (no unauthenticated access); Cloud Scheduler calls it with an OIDC token.
"""
import json
import os
import time

import functions_framework

from pipeline.cycle import run_cycle
from pipeline.sinks import GCSSink


@functions_framework.http
def ingest(request):
    started = time.time()
    summary = run_cycle(GCSSink(os.environ["MC_BUCKET"]))
    summary["elapsed_s"] = round(time.time() - started, 1)
    print(json.dumps({"severity": "INFO", "message": "mc-ingest cycle", "summary": summary}))
    return json.dumps(summary), 200, {"Content-Type": "application/json"}
