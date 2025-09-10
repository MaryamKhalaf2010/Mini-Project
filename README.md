# Mini Project – Step 1: TCP Echo Test

This is the first step of the **Mini Project**.  
It demonstrates a basic **TCP echo test** between two agents:

- **Agent B (server)**: Listens on port `4401` and echoes back whatever it receives.
- **Agent A (client)**: Sends JSON probe packets, receives echoes, and measures **round-trip time (RTT)**.

---

##  How It Works
1. Agent A sends a JSON probe every 0.5 seconds:
   ```json
   {
     "seq": 0,
     "t_send_ns": 1234567890
   }
   ```
2. Agent B echoes back the same JSON.
3. Agent A measures **RTT (latency)**:
   ```
   RTT = time_received - t_send_ns
   ```
4. Results are printed in the terminal.

---

##  How to Run

### Start Agent B (Echo Server)
```bash
python agent_b_echo.py
```

Expected output:
```
[Agent B] Echo server listening on 0.0.0.0:4401
[Agent B] Connected by ('127.0.0.1', 54321)
```

---

### Start Agent A (Client)
```bash
python agent_a_client.py
```

Expected output:
```
[Agent A] Connected to Agent B 127.0.0.1:4401
[Agent A] Seq=0 RTT=0.600 ms
[Agent A] Seq=1 RTT=0.420 ms
[Agent A] Seq=2 RTT=0.515 ms
...
```

---

##  Screenshots

### Agent B (Server)
![Agent B running](screenshots/agent-b.png)

### Agent A (Client)
![Agent A running](screenshots/agent-a.png)

---

---

##  What We Achieved
- Established a persistent **TCP connection** between Agent A and Agent B.
- Implemented a simple **echo server**.
- Measured **RTT (latency)** for each probe.

---

## Step 2 — Per-Minute Aggregation
Run:
```bash
python agent_a.py
```

After each minute (+2s grace), Agent A prints an aggregate JSON:

```json
{"time":"2025-09-10T12:55:00Z","latency_min_ms":0.106,"latency_max_ms":0.909,"latency_avg_ms":0.286,"jitter_min_ms":0.001,"jitter_max_ms":0.755,"jitter_avg_ms":0.136,"sent":92,"received":92,"lost":0}
```

##  Screenshots
### Agent A (Client)
![Agent A running](screenshots/agent-a-step2.png)

## Step 3 — MQTT Integration

**Goal:** Agent A publishes per-minute stats to MQTT; Agent B subscribes.

- Agent A publishes to:  
  `netstats/<agent_id>/minute`
- Agent B subscribes to:  
  `netstats/+/minute`

### Setup

Install requirements:
```bash
pip install -r requirements.txt
```

Start Mosquitto broker:
```bash
sudo systemctl start mosquitto
```

###  How to Run

#### Agent B (Echo + MQTT subscriber)
```bash
python agent_b.py
```
Expected:
```
[TCP] Echo server listening on 0.0.0.0:4401
[MQTT] Connected rc=0; subscribing to 'netstats/+/minute'
```

#### Agent A (Probes + Aggregator + MQTT publisher)
```bash
python agent_a.py
```
Expected once per minute:
```json
{
  "agent_id": "9815a8dc-136c-460f-9eb6-8fe938d8923b",
  "time": "2025-09-10T14:07:00Z",
  "latency_min_ms": 0.122,
  "latency_max_ms": 0.945,
  "latency_avg_ms": 0.286,
  "jitter_min_ms": 0.0,
  "jitter_max_ms": 0.707,
  "jitter_avg_ms": 0.113,
  "sent": 116,
  "received": 116,
  "lost": 0
}
```
