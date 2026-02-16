import socket
import sys
import time

HOST = '127.0.0.1'
PORT = 2222

try:
    print(f"Connecting to {HOST}:{PORT}...")
    with socket.create_connection((HOST, PORT), timeout=10) as s:
        print("Connected.")
        
        # Read initial banner (Deploying challenge...)
        data = s.recv(1024)
        print(f"Received: {data.decode('utf-8', errors='ignore')}")
        
        # Wait a bit for the container to start if needed
        time.sleep(2)
        
        # Challenge output (loop in alpine)
        data = s.recv(1024)
        print(f"Received challenge output: {data.decode('utf-8', errors='ignore')}")
        
    print("Test passed: Connection successful and data received.")
except Exception as e:
    print(f"Test failed: {e}")
    sys.exit(1)
