#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent A (UDP) — Probe Client + Per-Minute Aggregation + MQTT Publisher (UNCONNECTED UDP)
- Sends JSON probes over UDP at RATE_HZ.
- Measures RTT, computes jitter/loss per minute (+TIMEOUT_S grace).
- Publishes minute aggregates to MQTT: netstats/<agent_id>/minute (QoS0).
"""

import json, socket, time, uuid
from statistics import mean
from pathlib import Path
from paho.mqtt import client as mqtt

#  Configration
HOST = "127.0.0.1"      # Agent B UDP host
PORT = 4401             # Agent B UDP port
RATE_HZ = 2.0           # 2 probes/sec
TIMEOUT_S = 2.0         # echo deadline
PERIOD = 1.0 / RATE_HZ

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
STATE_DIR = Path.home() / ".agent_a"

# create agent ID and store it in a file , return it if already exists
def load_or_create_agent_id(state_dir: Path = STATE_DIR) -> str:
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / "id"
    if f.exists():
        return f.read_text().strip()
    aid = str(uuid.uuid4())
    f.write_text(aid)
    return aid

#  MQTT (Paho v1/v2 compatible)to support older versions
def _make_mqtt_client():
    try:
        _ = mqtt.CallbackAPIVersion
        return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        return mqtt.Client()

# publish to MQTT broker evrey minute
def publish_mqtt(agent_id: str, payload: dict):
    topic = f"netstats/{agent_id}/minute"
    c = _make_mqtt_client()
    try:
        c.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        c.publish(topic, json.dumps(payload, separators=(",", ":")), qos=0, retain=False)
        c.disconnect()
    except Exception as e:
        print(f"[MQTT] publish failed: {e}")

#  UDP socket (UNCONNECTED) with recv timeout
def make_udp_socket(recv_timeout_s: float = 0.05) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(recv_timeout_s)  # non-blocking-ish
    print(f"[Agent A] Using UNCONNECTED UDP to {HOST}:{PORT} (recv timeout {recv_timeout_s}s)")
    return s

# to test connectivity, run agent_b.py first
agent_id = load_or_create_agent_id()
sock = make_udp_socket(0.05)
print(f"[Agent A] Ready (agent_id={agent_id})")

seq = 0
latencies, jitters = [], []
sent = received = lost = 0
prev_rtt = None

current_minute = int(time.time() // 60) * 60        # minute-aligned window (UTC-like)
in_flight = {}                                      # seq -> t_send_ns
next_send = time.monotonic()                        # fixed-rate scheduler

last_sweep_ns = time.monotonic_ns()
SWEEP_NS = int(0.25 * 1e9)                          # sweep losses every 250ms

while True:
    now_wall = time.time()
    now_mono = time.monotonic()

    # Finalize previous minute (+TIMEOUT_S grace)
    if now_wall >= current_minute + 60 + TIMEOUT_S:
        result = {
            "agent_id": agent_id,
            "time": time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(current_minute)),
            "latency_min_ms": round(min(latencies), 3) if latencies else 0.0,
            "latency_max_ms": round(max(latencies), 3) if latencies else 0.0,
            "latency_avg_ms": round(mean(latencies), 3) if latencies else 0.0,
            "jitter_min_ms":  round(min(jitters), 3) if jitters else 0.0,
            "jitter_max_ms":  round(max(jitters), 3) if jitters else 0.0,
            "jitter_avg_ms":  round(mean(jitters), 3) if jitters else 0.0,
            "sent": sent, "received": received, "lost": lost,
        }
        print(json.dumps(result))
        publish_mqtt(agent_id, result)

        current_minute += 60
        latencies.clear(); jitters.clear()
        sent = received = lost = 0
        prev_rtt = None

    # Fixed-rate SEND scheduler
    if now_mono >= next_send:
        # send probe with seq and t_send_ns
        t_send_ns = time.monotonic_ns()
        probe = {"agent_id": agent_id, "seq": seq, "t_send_ns": t_send_ns}
        frame = json.dumps(probe, separators=(",", ":")).encode("utf-8")

        sent += 1
        try:
            sock.sendto(frame, (HOST, PORT))
            in_flight[seq] = t_send_ns
        # on send error, count as lost and recreate socket
        except Exception as e:
            print(f"[Agent A] send error: {e}")
            lost += 1
            try: sock.close()
            except Exception: pass
            # recreate socket
            sock = make_udp_socket(0.05)
            prev_rtt = None
        # increment seq (16-bit wrap)
        seq = (seq + 1) & 0xFFFF
        # schedule next send
        next_send = now_mono + PERIOD

    # Non-blocking RECV: drain available echoes
    while True:
        try:
            # setting a larger buffer size to avoid truncation
            data, addr = sock.recvfrom(65535)
            recv_ns = time.monotonic_ns()
            obj = json.loads(data.decode("utf-8"))
            mseq = obj.get("seq")
            tsend = in_flight.pop(mseq, None)
            if tsend is not None:
                rtt_ms = (recv_ns - tsend) / 1e6
                # only count if within TIMEOUT_S
                if rtt_ms <= TIMEOUT_S * 1000.0:
                    latencies.append(rtt_ms)
                    if prev_rtt is not None:
                        jitters.append(abs(rtt_ms - prev_rtt))
                    prev_rtt = rtt_ms
                    received += 1
        # no more data to recv
        except socket.timeout:
            break
        # on recv error, recreate socket and abandon current batch
        except Exception as e:
            print(f"[Agent A] recv error: {e}")
            try: sock.close()
            except Exception: pass
            sock = make_udp_socket(0.05)
            prev_rtt = None
            break

    # Timeout sweep → mark overdue in-flight as lost
    now_ns = time.monotonic_ns()
    # every 250ms 
    if (now_ns - last_sweep_ns) >= SWEEP_NS:
        expired = [s for s, ts in list(in_flight.items())
                   if (now_ns - ts) >= int(TIMEOUT_S * 1e9)]
        # if expire , add to lost count
        if expired:
            for s in expired:
                in_flight.pop(s, None)
            lost += len(expired)
        last_sweep_ns = now_ns

    time.sleep(0.002)  # prevent busy spin
