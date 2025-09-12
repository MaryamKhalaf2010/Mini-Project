#!/usr/bin/env python3
# Flask viewer for Mini-Project (templates split)

from __future__ import annotations
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, jsonify, request, render_template

DB_PATH = Path("netstats.db")

app = Flask(__name__)

def q(sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only query and return a list of dict rows."""
    if not DB_PATH.exists():
        return []
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

@app.get("/")
def index():
    # Renders templates/index.html
    return render_template("index.html")

@app.get("/api/agents")
def api_agents():
    rows = q("SELECT DISTINCT agent_id FROM minute_stats ORDER BY agent_id")
    return jsonify({"agents": [r["agent_id"] for r in rows]})

@app.get("/api/series")
def api_series():
    agent_id = request.args.get("agent_id", "")
    try:
        minutes = int(request.args.get("minutes", "120"))
    except ValueError:
        minutes = 120
    minutes = max(5, min(1440, minutes))

    # default to most recent agent if none provided
    if not agent_id:
        last = q("SELECT agent_id FROM minute_stats ORDER BY minute_utc DESC LIMIT 1")
        if not last:
            return jsonify({"rows": [], "agent_id": "", "since": ""})
        agent_id = last[0]["agent_id"]

    # compute lower bound (aligned to minute) and fetch rows
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    since = now - timedelta(minutes=minutes)
    since_iso = since.isoformat(timespec="minutes").replace("+00:00", "Z")

    rows = q(
        """
        SELECT minute_utc, latency_avg_ms, jitter_avg_ms, sent, received, lost
        FROM minute_stats
        WHERE agent_id = ? AND minute_utc >= ?
        ORDER BY minute_utc ASC
        """,
        (agent_id, since_iso),
    )
    return jsonify({"rows": rows, "agent_id": agent_id, "since": since_iso})

if __name__ == "__main__":
    # bind to 0.0.0.0 so your Windows browser can reach it from WSL
    app.run(host="0.0.0.0", port=5051, debug=True)
