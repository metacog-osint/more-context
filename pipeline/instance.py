"""Shut this Cloud Run instance down after a run whose saved searches were refused (28 Oct 2026).

Google News refuses some Cloud Run egress addresses, and a warm instance keeps its address: on 28 Oct every run on
one healthy instance was refused, while about 4 in 10 fresh instances got through. So after a refused run the server
is stopped once the response has gone out, and the next run (15 minutes later) starts on a new instance.

The request runs in a gunicorn worker; stopping only the worker would make gunicorn start another in the same
instance, so the signal goes to the parent (the gunicorn server). Graceful: it lets the finished request flush.
Only on Cloud Run (K_SERVICE set): run locally, the parent process could be your shell.
"""
from __future__ import annotations

import os
import signal
import threading

DELAY_S = 3


def restart_if_refused(summary: dict, env=None, ppid=None, start=None) -> bool:
    """Schedule the server's shutdown when this run's searches were refused. Returns whether it was scheduled."""
    env = os.environ if env is None else env
    if not (summary.get("rss") or {}).get("searches_refused") or not env.get("K_SERVICE"):
        return False
    parent = os.getppid() if ppid is None else ppid
    if parent <= 0 or parent == os.getpid():
        return False
    if start is None:
        def start(delay, fn, args):
            t = threading.Timer(delay, fn, args)
            t.daemon = True
            t.start()
    start(DELAY_S, os.kill, (parent, signal.SIGTERM))
    return True
