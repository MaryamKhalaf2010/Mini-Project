
# Active code (Step 3): Echo server + MQTT subscriber

import socket
import threading
import json
import paho.mqtt.client as mqtt

# --- TCP echo server config ---
TCP_HOST = "0.0.0.0"
TCP_PORT = 4401

# --- MQTT config ---
MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC = "netstats/+/minute"   # receive all agents' minute stats


def handle_conn(conn, addr):
    """Handle one TCP connection; echo each line back verbatim."""
    try:
        # Read line-by-line so Agent A gets back exactly what it sent
        buf = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            # Echo per line (newline-delimited JSON)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                # Echo it back with newline (exactly what we got)
                conn.sendall(line + b"\n")
    finally:
        conn.close()


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


# ---------- MQTT subscriber ----------

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[MQTT] Connected rc={reason_code}; subscribing to '{MQTT_TOPIC}'")
    client.subscribe(MQTT_TOPIC, qos=0)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        # Pretty print one line (keep it compact)
        print(f"[MQTT] {msg.topic} -> {json.dumps(payload)}")
    except Exception as e:
        print(f"[MQTT] Bad message: {e} raw={msg.payload!r}")


def mqtt_subscriber_loop():
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    # Blocking loop; Ctrl+C to exit
    client.loop_forever()


def main():
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

# Step 1 (Simple TCP Echo Server)


"""
import socket

HOST = "0.0.0.0"   # Listen on all network interfaces
PORT = 4401

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(1)
print(f"[Agent B] Echo server listening on {HOST}:{PORT}")

conn, addr = server.accept()
print(f"[Agent B] Connected by {addr}")

while True:
    data = conn.recv(1024)
    if not data:
        break
    conn.sendall(data)   # Echo back exactly what was received
"""