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
