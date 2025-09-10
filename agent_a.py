

# ======================================================
# Step 2 (active code)
# ======================================================

import socket, json, time
from statistics import mean

HOST = "127.0.0.1"
PORT = 4401
RATE_HZ = 2.0          # 2 probes/second
TIMEOUT_S = 2.0        # max wait for echo
PERIOD = 1.0 / RATE_HZ

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.settimeout(TIMEOUT_S)
client.connect((HOST, PORT))
print(f"[Agent A] Connected to Agent B {HOST}:{PORT}")

seq = 0
latencies = []
jitters = []
sent = received = 0
prev_rtt = None

# Track the current minute endpoint (e.g. 12:34:00Z)
current_minute = int(time.time() // 60) * 60

while True:
    now = time.time()

    # Minute rollover
    if now >= current_minute + 60 + TIMEOUT_S:
        # Finalize stats for the past minute
        latency_min = min(latencies) if latencies else 0
        latency_max = max(latencies) if latencies else 0
        latency_avg = mean(latencies) if latencies else 0
        jitter_min = min(jitters) if jitters else 0
        jitter_max = max(jitters) if jitters else 0
        jitter_avg = mean(jitters) if jitters else 0
        lost = sent - received

        result = {
            "time": time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(current_minute)),
            "latency_min_ms": round(latency_min, 3),
            "latency_max_ms": round(latency_max, 3),
            "latency_avg_ms": round(latency_avg, 3),
            "jitter_min_ms": round(jitter_min, 3),
            "jitter_max_ms": round(jitter_max, 3),
            "jitter_avg_ms": round(jitter_avg, 3),
            "sent": sent,
            "received": received,
            "lost": lost,
        }
        print(json.dumps(result))

        # Reset for the new minute
        current_minute += 60
        latencies.clear()
        jitters.clear()
        sent = received = 0
        prev_rtt = None

    # ---- Send probe ----
    t_send_ns = time.monotonic_ns()
    payload = {"seq": seq, "t_send_ns": t_send_ns}
    line = (json.dumps(payload) + "\n").encode()
    client.sendall(line)
    sent += 1

    # ---- Receive echo or timeout ----
    try:
        echo = client.recv(1024)
        recv_ns = time.monotonic_ns()
        data = json.loads(echo.decode().strip())
        if data["seq"] == seq and data["t_send_ns"] == t_send_ns:
            rtt_ms = (recv_ns - t_send_ns) / 1e6
            latencies.append(rtt_ms)
            received += 1
            if prev_rtt is not None:
                jitters.append(abs(rtt_ms - prev_rtt))
            prev_rtt = rtt_ms
    except socket.timeout:
        # counted as lost, nothing to add
        pass

    # Next probe
    seq = (seq + 1) & 0xFFFF
    time.sleep(PERIOD)

# ======================================================
# Step 1 (commented out, for reference)
# ======================================================

"""
# Agent A - Simple Probe Client
import socket
import json
import time

HOST = "127.0.0.1"   # Agent B host (localhost for now)
PORT = 4401

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((HOST, PORT))
print(f"[Agent A] Connected to Agent B {HOST}:{PORT}")

seq = 0
while True:
    # Record send time
    t_send_ns = time.monotonic_ns()
    payload = {
        "seq": seq,
        "t_send_ns": t_send_ns
    }
    line = (json.dumps(payload) + "\n").encode()

    # Send
    client.sendall(line)

    # Receive echo
    echo = client.recv(1024)
    recv_time_ns = time.monotonic_ns()

    # Parse echo
    data = json.loads(echo.decode().strip())
    rtt_ms = (recv_time_ns - data["t_send_ns"]) / 1e6

    print(f"[Agent A] Seq={data['seq']} RTT={rtt_ms:.3f} ms")

    seq = (seq + 1) & 0xFFFF  # wrap at 65535
    time.sleep(0.5)  # send 2 probes/sec
"""
