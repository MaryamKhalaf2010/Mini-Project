
#!/usr/bin/env python3
#  Echo server + MQTT subscriber → SQLite

import socket
import threading
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from paho.mqtt import client as mqtt

# TCP echo server config
TCP_HOST = "0.0.0.0"
TCP_PORT = 4401

# MQTT config
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC = "netstats/+/minute"   # receive all agents' minute stats

# SQLite config
DB_PATH = Path("netstats.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS minute_stats (
  agent_id        TEXT    NOT NULL,
  minute_utc      TEXT    NOT NULL, -- ISO8601 Z, e.g., 2025-09-09T12:34:00Z
  latency_min_ms  REAL    NOT NULL,
  latency_max_ms  REAL    NOT NULL,
  latency_avg_ms  REAL    NOT NULL,
  jitter_min_ms   REAL    NOT NULL,
  jitter_max_ms   REAL    NOT NULL,
  jitter_avg_ms   REAL    NOT NULL,
  sent            INTEGER NOT NULL,
  received        INTEGER NOT NULL,
  lost            INTEGER NOT NULL,
  PRIMARY KEY (agent_id, minute_utc)
);
CREATE INDEX IF NOT EXISTS idx_minute_stats_time ON minute_stats(minute_utc);
"""

UPSERT_SQL = """
INSERT INTO minute_stats (
  agent_id, minute_utc, latency_min_ms, latency_max_ms, latency_avg_ms,
  jitter_min_ms, jitter_max_ms, jitter_avg_ms, sent, received, lost
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(agent_id, minute_utc) DO UPDATE SET
  latency_min_ms=excluded.latency_min_ms,
  latency_max_ms=excluded.latency_max_ms,
  latency_avg_ms=excluded.latency_avg_ms,
  jitter_min_ms=excluded.jitter_min_ms,
  jitter_max_ms=excluded.jitter_max_ms,
  jitter_avg_ms=excluded.jitter_avg_ms,
  sent=excluded.sent,
  received=excluded.received,
  lost=excluded.lost;
"""
# initialize DB if not exists
def init_db():
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()

# TCP echo server handlers

def handle_conn(conn, addr):
    """Handle one TCP connection; echo each line back verbatim."""
    try:
        # Flush small frames immediately (avoid Nagle delays)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            # Echo per line (newline-delimited JSON)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                conn.sendall(line + b"\n")
    finally:
        conn.close()
        
# Start TCP echo server
def echo_server():
    """Blocking TCP echo server that accepts multiple clients (each in its own thread)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((TCP_HOST, TCP_PORT))
    server.listen(8)
    print(f"[TCP] Echo server listening on {TCP_HOST}:{TCP_PORT}")
    try:
        while True:
            conn, addr = server.accept()
            print(f"[TCP] Connected by {addr}")
            t = threading.Thread(target=handle_conn, args=(conn, addr), daemon=True)
            t.start()
    finally:
        server.close()

#  MQTT subscriber → SQLite DB

def on_connect(client, userdata, flags, reason_code, properties=None):
    rc_val = getattr(reason_code, "value", reason_code)
    sess = getattr(flags, "session_present", None)
    print(f"[MQTT] on_connect rc={rc_val}, session_present={sess}; subscribing '{MQTT_TOPIC}'")
    if rc_val == 0:
        client.subscribe(MQTT_TOPIC, qos=0)
    else:
        print(f"[MQTT] connect failed with rc={rc_val}")
        
# confirm subscription
def on_subscribe(client, userdata, mid, reason_codes, properties=None):
    print(f"[MQTT] subscribed mid={mid}, reason_codes={reason_codes}")
    
# process incoming messages , insert into SQLite DB
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        # Build row and UPSERT
        row = (
            payload["agent_id"],
            payload["time"],
            float(payload["latency_min_ms"]),
            float(payload["latency_max_ms"]),
            float(payload["latency_avg_ms"]),
            float(payload["jitter_min_ms"]),
            float(payload["jitter_max_ms"]),
            float(payload["jitter_avg_ms"]),
            int(payload["sent"]),
            int(payload["received"]),
            int(payload["lost"]),
        )
        with closing(sqlite3.connect(str(DB_PATH))) as conn:
            conn.execute(UPSERT_SQL, row)
            conn.commit()
        print(f"[DB] upserted {payload['agent_id']} @ {payload['time']}")
    except Exception as e:
        print(f"[MQTT] Bad message/DB error: {e} raw={msg.payload!r}")
        
# MQTT subscriber loop to run in main thread
def mqtt_subscriber_loop():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_forever()

def main():
    # initialize DB 
    init_db()
    # Start TCP echo server in a background thread
    t = threading.Thread(target=echo_server, daemon=True)
    t.start()
    # Run MQTT subscriber in the main thread
    try:
        mqtt_subscriber_loop()
    except KeyboardInterrupt:
        print("\n[Agent B] Stopping...")

if __name__ == "__main__":
    main()

