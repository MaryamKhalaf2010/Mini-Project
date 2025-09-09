# Agent B - Simple Echo Server
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
