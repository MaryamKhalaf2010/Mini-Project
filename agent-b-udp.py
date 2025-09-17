#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent B (UDP) — Echo server + MQTT subscriber → SQLite
- UDP echo server (background thread): verbatim echo of incoming datagrams.
- MQTT subscriber (main thread): consumes minute aggregates and UPSERTs into SQLite.
"""

import socket, threading, json, sqlite3
from contextlib import closing
from pathlib import Path
from paho.mqtt import client as mqtt

# Configration
UDP_HOST = "0.0.0.0"
UDP_PORT = 4401

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC = "netstats/+/minute"   # all agents’ minute topics

DB_PATH = Path("netstats.db")

# add  Schema for SQLite
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS minute_stats (
  agent_id        TEXT    NOT NULL,
  minute_utc      TEXT    NOT NULL, -- e.g., 2025-09-09T12:34:00Z
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
# add UPSERT , if there is a conflict with the primary key (agent_id, minute_utc), it will update the existing record instead of inserting a new one.

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

#  DB init if not exists , create a new SQLite database (or open existing) and set up the schema if it doesn't already exist.
def init_db() -> None:
    with closing(sqlite3.connect(str(DB_PATH))) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA_SQL)
        conn.commit()

#  UDP Echo Server (runs forever) 
def udp_echo_server() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_HOST, UDP_PORT))
    print(f"[UDP] Echo server listening on {UDP_HOST}:{UDP_PORT}")
    try:
        while True:  # << the crucial loop so it doesn't exit after one datagram
            try:
                data, addr = sock.recvfrom(2048)     # small JSON probes
                sock.sendto(data, addr)              # echo exact bytes back
                # optional debug:
                # print(f"[UDP] echoed {len(data)} bytes to {addr}")
            except Exception as e:
                print(f"[UDP] echo error: {e}")
    finally:
        sock.close()

#  MQTT subscriber → SQLite to handle MQTT events
def on_connect(client, userdata, flags, reason_code=None, properties=None):
    rc_val = getattr(reason_code, "value", reason_code)
    sess = getattr(flags, "session_present",
                   flags.get("session present") if isinstance(flags, dict) else None)
    print(f"[MQTT] on_connect rc={rc_val}, session_present={sess}; subscribing '{MQTT_TOPIC}'")
    if rc_val in (0, None):  # None covers Paho 1.x signature
        client.subscribe(MQTT_TOPIC, qos=0)
    else:
        print(f"[MQTT] connect failed rc={rc_val}")
# handle subscribe ack to confirm subscription to  MQTT_TOPIC
def on_subscribe(client, userdata, mid, reason_codes, properties=None):
    print(f"[MQTT] subscribed mid={mid}, reason_codes={reason_codes}")
    
# process incoming messages , insert into SQLite DB
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
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
        # insert into SQLite DB
        with closing(sqlite3.connect(str(DB_PATH))) as conn:
            conn.execute(UPSERT_SQL, row)
            conn.commit()
        print(f"[DB] upserted {payload['agent_id']} @ {payload['time']}")
    except Exception as e:
        print(f"[MQTT] Bad message/DB error: {e} raw={msg.payload!r}")
# make MQTT client to handle different Paho versions
def make_mqtt_client():
    # Paho 2.x supports CallbackAPIVersion; fall back to default if not present
    try:
        _ = mqtt.CallbackAPIVersion
        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        c = mqtt.Client()
    # set callbacks
    c.on_connect = on_connect
    c.on_message = on_message
    c.on_subscribe = on_subscribe
    return c
# MQTT subscriber loop to run in main thread 
def mqtt_subscriber_loop() -> None:
    c = make_mqtt_client()
    c.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    c.loop_forever()

# test connectivity, run agent_b.py first
def main() -> None:
    init_db()
    t = threading.Thread(target=udp_echo_server, daemon=True)
    t.start()
    try:
        mqtt_subscriber_loop()
    except KeyboardInterrupt:
        print("\n[Agent B] Stopping...")

if __name__ == "__main__":
    main()
