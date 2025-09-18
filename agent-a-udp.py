#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent A (UDP) — Probe Client + Per-Minute Aggregation + MQTT Publisher

WHAT THIS PROGRAM DOES
- Sends small JSON “probe” packets over **UDP** to Agent B at a fixed rate (RATE_HZ).
- Measures **RTT** on echoed packets, derives **jitter**, and aggregates stats in **1-minute windows**.
- After each minute (with a **+TIMEOUT_S grace** so on-time late echoes can arrive), publishes one
  JSON record to **MQTT** on topic:  netstats/<agent_id>/minute  (QoS 0, no retain).

"""

import json, socket, time, uuid
from statistics import mean
from pathlib import Path
from paho.mqtt import client as mqtt

# Configuration 
HOST = "127.0.0.1"      # Agent B UDP host
PORT = 4401             # Agent B UDP port
RATE_HZ = 2.0           # 2 probes/sec
TIMEOUT_S = 2.0         # echo deadline for "on-time" receives
PERIOD = 1.0 / RATE_HZ

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
STATE_DIR = Path.home() / ".agent_a"

# create or load unique agent ID
def load_or_create_agent_id(state_dir: Path = STATE_DIR) -> str:
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / "id"
    if f.exists():
        return f.read_text().strip()
    aid = str(uuid.uuid4())
    f.write_text(aid)
    return aid

# MQTT (Paho v1/v2 compatible) establish client 
def _make_mqtt_client():
    # Support both paho-mqtt v1.x and v2.x without breaking
    try:
        _ = mqtt.CallbackAPIVersion
        return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        return mqtt.Client()
    
# publish to MQTT broker
def publish_mqtt(agent_id: str, payload: dict):
    topic = f"netstats/{agent_id}/minute"
    c = _make_mqtt_client()
    try:
        c.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        c.publish(topic, json.dumps(payload, separators=(",", ":")), qos=0, retain=False)
        c.disconnect()
    except Exception as e:
        print(f"[MQTT] publish failed: {e}")

# UDP socket setup to send/receive probes
def make_udp_socket(recv_timeout_s: float = 0.05) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(recv_timeout_s)  # short timeout → non-blocking-ish poll
    print(f"[Agent A] Using UNCONNECTED UDP to {HOST}:{PORT} (recv timeout {recv_timeout_s}s)")
    return s

# test connectivity, run agent_b.py first
agent_id = load_or_create_agent_id()
sock = make_udp_socket(0.05)
print(f"[Agent A] Ready (agent_id={agent_id})")

seq = 0
latencies, jitters = [], []
sent = 0           # number of probes we attempted this minute
received = 0       # number of echoes that arrived within TIMEOUT_S this minute
# NOTE: there is NO running 'lost' counter anymore — we derive it at finalize.
prev_rtt = None

current_minute = int(time.time() // 60) * 60  # minute-aligned window
in_flight = {}                                # seq -> t_send_ns (tracks outstanding probes)
next_send = time.monotonic()                  # fixed-rate scheduler tick

last_sweep_ns = time.monotonic_ns()
SWEEP_NS = int(0.25 * 1e9)                    # sweep every 250ms (for memory hygiene ONLY)

# loop forever: fixed-rate SEND, non-blocking RECV, minute FINALIZE
while True:
    now_wall = time.time()
    now_mono = time.monotonic()

    # Minute finalize WITH +TIMEOUT_S grace so on-time late echoes can still be counted.
    if now_wall >= current_minute + 60 + TIMEOUT_S:
        # OPTION A: compute lost exactly once here
        computed_lost = max(0, sent - received)

        result = {
            "agent_id": agent_id,
            "time": time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(current_minute)),
            "latency_min_ms": round(min(latencies), 3) if latencies else 0.0,
            "latency_max_ms": round(max(latencies), 3) if latencies else 0.0,
            "latency_avg_ms": round(mean(latencies), 3) if latencies else 0.0,
            "jitter_min_ms":  round(min(jitters), 3) if jitters else 0.0,
            "jitter_max_ms":  round(max(jitters), 3) if jitters else 0.0,
            "jitter_avg_ms":  round(mean(jitters), 3) if jitters else 0.0,
            "sent": sent,
            "received": received,
            "lost": computed_lost,  # ← derived; we removed all mid-minute lost+= increments
        }
        print(json.dumps(result))
        publish_mqtt(agent_id, result)

        # Reset per-minute accumulators for the next window
        current_minute += 60
        latencies.clear(); jitters.clear()
        sent = 0; received = 0
        prev_rtt = None
        # We do NOT clear in_flight here; the sweep below keeps it tidy.
        # (Even if some old seqs linger, they won't affect loss math anymore.)

    # Fixed-rate SEND
    if now_mono >= next_send:
        t_send_ns = time.monotonic_ns()
        probe = {"agent_id": agent_id, "seq": seq, "t_send_ns": t_send_ns}
        frame = json.dumps(probe, separators=(",", ":")).encode("utf-8")

        sent += 1  # count attempt as 'sent' even if a send error occurs (loss accounted at finalize)
        try:
            sock.sendto(frame, (HOST, PORT))
            in_flight[seq] = t_send_ns
        except Exception as e:
            # WHY WE REMOVED 'lost += 1' HERE:
            # In Option A, send failures are naturally included in `sent - received`
            # at finalize, so incrementing 'lost' here would double-count.
            print(f"[Agent A] send error: {e}")
            try:
                sock.close()
            except Exception:
                pass
            sock = make_udp_socket(0.05)
            prev_rtt = None

        seq = (seq + 1) & 0xFFFF
        next_send = now_mono + PERIOD

    # Non-blocking RECV: process any echoes that are ready
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            recv_ns = time.monotonic_ns()
            obj = json.loads(data.decode("utf-8"))
            mseq = obj.get("seq")
            tsend = in_flight.pop(mseq, None)
            if tsend is not None:
                rtt_ms = (recv_ns - tsend) / 1e6
                if rtt_ms <= TIMEOUT_S * 1000.0:
                    # on-time echo → count as received, update latency/jitter
                    latencies.append(rtt_ms)
                    if prev_rtt is not None:
                        jitters.append(abs(rtt_ms - prev_rtt))
                    prev_rtt = rtt_ms
                    received += 1
                else:
                    # WHY WE DO NOTHING FOR LATE ECHO HERE:
                    # Late (> TIMEOUT_S) does NOT increment 'received', so at finalize
                    # it will be counted as 'lost = sent - received'. Adding 'lost += 1'
                    # here would double-count relative to finalize.
                    pass
        except socket.timeout:
            break
        except Exception as e:
            print(f"[Agent A] recv error: {e}")
            try:
                sock.close()
            except Exception:
                pass
            sock = make_udp_socket(0.05)
            prev_rtt = None
            break

    # Timeout SWEEP — memory hygiene ONLY (no loss math here in Option A)
    now_ns = time.monotonic_ns()
    if (now_ns - last_sweep_ns) >= SWEEP_NS:
        expired = [s for s, ts in list(in_flight.items())
                   if (now_ns - ts) >= int(TIMEOUT_S * 1e9)]
        if expired:
            for s in expired:
                in_flight.pop(s, None)
            # WHY WE REMOVED 'lost += len(expired)' HERE:
            # Option A computes loss solely at finalize (sent - received).
            # Incrementing here would double-count against finalize.
        last_sweep_ns = now_ns

    time.sleep(0.002)  # prevent busy spin
