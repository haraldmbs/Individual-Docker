import sys
import time
import urllib.request
import http.client
import socket

def test_web_redirect(landing_port, expected_content):
    print(f"Testing Web Redirect on landing port {landing_port}...")
    try:
        # 1. Connect to Landing Port
        conn = http.client.HTTPConnection("127.0.0.1", landing_port, timeout=10)
        conn.request("GET", "/")
        resp = conn.getresponse()
        
        print(f"Landing Response: {resp.status}")
        if resp.status != 302:
            print(f"Failed: Expected 302 Redirect, got {resp.status}")
            return False
            
        location = resp.getheader("Location")
        print(f"Redirect Location: {location}")
        
        if not location:
            print("Failed: No Location header")
            return False
            
        # Parse new port
        new_url = location
        if "http://localhost:" in new_url:
            new_port = int(new_url.split(":")[-1].replace("/", ""))
        else:
            print(f"Failed: Unexpected location format {new_url}")
            return False
            
        print(f"Instance Port: {new_port}")
        
        # 2. Connect to Instance Port
        time.sleep(1)
        
        try:
            with urllib.request.urlopen(new_url) as response:
                 content = response.read().decode('utf-8')
                 if expected_content in content:
                     print("Instance Content Verified.")
                     return True
                 else:
                     print("Failed: Content mismatch")
                     print(content)
                     return False
        except Exception as e:
            print(f"Failed to connect to instance: {e}")
            return False

    except Exception as e:
        print(f"Web Redirect Test Failed: {e}")
        return False

def test_ssh_direct(port):
    print(f"Testing SSH Direct on port {port}...")
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=10) as s:
            data = s.recv(1024)
            print(f"Received: {data[:50]}")
            if data.startswith(b"SSH-"):
                print("SSH Test Passed: SSH banner received.")
                return True
            else:
                print("SSH Test Failed: Did not receive SSH banner.")
                return False
    except Exception as e:
        print(f"SSH Test Failed: {e}")
        return False

if __name__ == "__main__":
    time.sleep(5) 
    
    web_passed = test_web_redirect(8080, "CTF{web_proxy_master}")
    ssh_passed = test_ssh_direct(2223)
    
    if web_passed and ssh_passed:
        print("Mixed Mode Test Passed.")
        sys.exit(0)
    else:
        print("Tests Failed.")
        sys.exit(1)
