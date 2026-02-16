import asyncio
import json
import logging
import uuid
import os
import subprocess
import signal
import socket
import time
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
CHALLENGES_CONFIG_FILE = 'challenges.json'
CHALLENGES_DIR = 'challenges'

def load_config():
    with open(CHALLENGES_CONFIG_FILE, 'r') as f:
        return json.load(f)

# --- Challenge & Container Management ---

async def start_challenge(session_id, challenge_config):
    """
    Starts a challenge using docker compose.
    Returns the IP address of the container and the target port.
    """
    folder = challenge_config['folder']
    compose_file = os.path.join(CHALLENGES_DIR, folder, 'docker-compose.yml')
    project_name = f"ctf_{folder}_{session_id}"
    
    logger.info(f"[{session_id}] Starting challenge {folder}...")

    # Start the challenge
    cmd = [
        "docker", "compose", 
        "-p", project_name, 
        "-f", compose_file, 
        "up", "-d"
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        logger.error(f"[{session_id}] Failed to start challenge: {stderr.decode()}")
        raise Exception("Failed to start challenge environment")

    # Get the container IP
    target_service = challenge_config.get('target_service', 'challenge')
    
    inspect_cmd = [
        "docker", "compose",
        "-p", project_name,
        "-f", compose_file,
        "ps", "-q", target_service
    ]
    
    process = await asyncio.create_subprocess_exec(
        *inspect_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    container_id = stdout.decode().strip()
    
    if not container_id:
        logger.error(f"[{session_id}] Could not find container for service {target_service}")
        raise Exception("Service not found")

    get_ip_cmd = [
        "docker", "inspect",
        "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        container_id
    ]
    
    process = await asyncio.create_subprocess_exec(
        *get_ip_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    container_ip = stdout.decode().strip()
    
    if not container_ip:
        logger.error(f"[{session_id}] Could not get IP for container {container_id}")
        raise Exception("Could not determine container IP")

    get_net_cmd = [
        "docker", "inspect",
        "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}",
        container_id
    ]
    process = await asyncio.create_subprocess_exec(
        *get_net_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    network_name = stdout.decode().strip()
    
    if network_name:
        my_hostname = socket.gethostname()
        logger.info(f"[{session_id}] Attaching myself ({my_hostname}) to network {network_name}...")
        connect_cmd = ["docker", "network", "connect", network_name, my_hostname]
        proc = await asyncio.create_subprocess_exec(*connect_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        
    logger.info(f"[{session_id}] Challenge started at {container_ip}")
    return container_ip, network_name

async def stop_challenge(session_id, challenge_config, network_name=None):
    """
    Stops and removes the challenge environment.
    """
    if network_name:
        try:
            my_hostname = socket.gethostname()
            logger.info(f"[{session_id}] Disconnecting from network {network_name}...")
            cmd = ["docker", "network", "disconnect", network_name, my_hostname]
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            await proc.communicate()
        except Exception as e:
            logger.error(f"[{session_id}] Error disconnecting network: {e}")

    folder = challenge_config['folder']
    compose_file = os.path.join(CHALLENGES_DIR, folder, 'docker-compose.yml')
    project_name = f"ctf_{folder}_{session_id}"
    
    logger.info(f"[{session_id}] Stopping challenge...")
    
    cmd = [
        "docker", "compose",
        "-p", project_name,
        "-f", compose_file,
        "down", "-v", "--remove-orphans"
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await process.communicate()
    logger.info(f"[{session_id}] Challenge stopped.")

# --- Session & Port Management (Redirect Mode) ---

class ChallengeMode:
    LIVE = "live"
    REDIRECT = "redirect"

class Session:
    def __init__(self, session_id, port, challenge_config, container_ip, network_name):
        self.session_id = session_id
        self.port = port
        self.config = challenge_config
        self.container_ip = container_ip
        self.network_name = network_name
        self.created_at = time.time()
        self.last_active = time.time()
        self.timeout = challenge_config.get('timeout', 300) # Default 5 mins

    def is_expired(self):
        return (time.time() - self.last_active) > self.timeout

    def touch(self):
        self.last_active = time.time()

class PortManager:
    def __init__(self, start, end):
        self.available_ports = deque(range(start, end + 1))
        # LRU-like behavior: failed/expired usage puts port back at end

    def get_port(self):
        if not self.available_ports:
            return None
        return self.available_ports.popleft()

    def return_port(self, port):
        self.available_ports.append(port)

class Orchestrator:
    def __init__(self):
        self.config = load_config()
        self.sessions = {} # port -> Session
        self.port_managers = {} # challenge_folder -> PortManager
        
        # Initialize Port Managers for redirect challenges
        for challenge in self.config:
            if challenge.get('mode') == ChallengeMode.REDIRECT:
                pr = challenge.get('port_range')
                if pr and len(pr) == 2:
                    self.port_managers[challenge['folder']] = PortManager(pr[0], pr[1])
                else:
                    logger.error(f"Challenge {challenge['folder']} is redirect mode but missing valid port_range")

    async def cleanup_task(self):
        """Periodically checks for expired sessions."""
        while True:
            await asyncio.sleep(10)
            expired_ports = []
            for port, session in self.sessions.items():
                if session.is_expired():
                    logger.info(f"[{session.session_id}] Session expired on port {port}. Cleaning up.")
                    await stop_challenge(session.session_id, session.config, session.network_name)
                    
                    # Return port to manager
                    folder = session.config['folder']
                    if folder in self.port_managers:
                       self.port_managers[folder].return_port(port)
                    
                    expired_ports.append(port)
            
            for port in expired_ports:
                del self.sessions[port]

    # --- Live Mode Handler ---
    
    async def handle_live_connection(self, reader, writer, challenge_config):
        session_id = str(uuid.uuid4())[:8]
        logger.info(f"[{session_id}] New LIVE connection.")
        target_port = challenge_config['target_port']
        container_ip = None
        network_name = None

        try:
            if challenge_config.get('banner', True):
                writer.write(b"Deploying challenge environment... please wait.\n")
                await writer.drain()
            else:
                logger.info(f"[{session_id}] Banner disabled.")

            container_ip, network_name = await start_challenge(session_id, challenge_config)

            # Retry connect
            retries = 5
            container_reader, container_writer = None, None
            for i in range(retries):
                try:
                    container_reader, container_writer = await asyncio.open_connection(
                        container_ip, target_port
                    )
                    break
                except (ConnectionRefusedError, OSError):
                    if i == retries - 1: raise
                    await asyncio.sleep(1)
            
            await self.proxy_data(reader, writer, container_reader, container_writer)

        except Exception as e:
            logger.error(f"[{session_id}] Error: {e}")
            try:
                writer.write(f"Error: {e}\n".encode())
                await writer.drain()
            except: pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except: pass
            if container_ip:
                await stop_challenge(session_id, challenge_config, network_name)

    # --- Redirect Mode Handlers ---

    async def handle_landing_connection(self, reader, writer, challenge_config):
        """
        Handles connection to the main 'Landing' port.
        Spins up instance -> Redirects user to assigned port.
        """
        session_id = str(uuid.uuid4())[:8]
        folder = challenge_config['folder']
        pm = self.port_managers.get(folder)
        
        if not pm:
            logger.error(f"[{session_id}] No PortManager for {folder}")
            writer.close()
            return

        assigned_port = pm.get_port()
        if not assigned_port:
            logger.warning(f"[{session_id}] No ports available for {folder}")
            response = "HTTP/1.1 503 Service Unavailable\r\n\r\nNo slots available. Try again later."
            writer.write(response.encode())
            await writer.drain()
            writer.close()
            return

        # Check if port is already in use (zombie session?)
        if assigned_port in self.sessions:
             # Should be cleaned up by loop, but force cleanup if race condition
             old_session = self.sessions[assigned_port]
             await stop_challenge(old_session.session_id, old_session.config, old_session.network_name)
             del self.sessions[assigned_port]

        try:
            # Wait for request data to verify this is a real HTTP request (not speculative TCP)
            # Peek or read. Since we are redirecting, we can consume it.
            try:
                data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"[{session_id}] Client timeout waiting for request. Closing.")
                writer.close()
                pm.return_port(assigned_port)
                return

            if not data or len(data) < 5: # Minimal checks
                logger.warning(f"[{session_id}] Empty or invalid request. Closing.")
                writer.close()
                pm.return_port(assigned_port)
                return
            
            # Simple check for HTTP method.
            # Convert first few bytes to string safely
            preview = data[:10].decode('utf-8', errors='ignore')
            if not (preview.startswith('GET') or preview.startswith('POST') or preview.startswith('HEAD')):
                logger.warning(f"[{session_id}] Non-HTTP request detected: {preview}. Closing.")
                writer.close()
                pm.return_port(assigned_port)
                return

            logger.info(f"[{session_id}] Starting session on port {assigned_port}")
            container_ip, network_name = await start_challenge(session_id, challenge_config)
            
            session = Session(session_id, assigned_port, challenge_config, container_ip, network_name)
            self.sessions[assigned_port] = session
            
            # Construct Redirect response
            # Note: In a real scenario we need the public hostname.
            # For POC we assume Host header or localhost
            
            # We can try to read the Host header from the request, but simple:
            # Send relative redirect? No, port changes.
            # We will send a generic redirect to the same host but new port.
            
            # Read first line to consume request method (optional but good practice)
            # data = await reader.read(1024) 
            
            # A simple HTTP Redirect
            host = "localhost" # Default
            # Attempt to peek host? Complex for raw TCP. 
            # We will rely on user using localhost or relative path logic if browser supports it?
            # Browsers need absolute URI for port change usually.
            
            logger.info(f"[{session_id}] Redirecting to port {assigned_port}")
            redirect_response = (
                f"HTTP/1.1 302 Found\r\n"
                f"Location: http://{host}:{assigned_port}/\r\n"
                f"Content-Length: 0\r\n"
                f"Connection: close\r\n\r\n"
            )
            writer.write(redirect_response.encode())
            await writer.drain()
            
        except Exception as e:
            logger.error(f"[{session_id}] Error starting session: {e}")
            pm.return_port(assigned_port)
            writer.write(b"HTTP/1.1 500 Internal Server Error\r\n\r\nError starting instance.")
        finally:
            writer.close()


    async def handle_instance_connection(self, reader, writer, port, challenge_config):
        """
        Handles connection to one of the pool ports.
        validates session -> Proxies.
        """
        session = self.sessions.get(port)
        
        if not session:
            # Invalid or expired session. Redirect back to Landing.
            landing_port = challenge_config['port']
            logger.info(f"[Port {port}] No active session. Redirecting to landing {landing_port}")
            redirect_response = (
                f"HTTP/1.1 302 Found\r\n"
                f"Location: http://localhost:{landing_port}/\r\n"
                f"Connection: close\r\n\r\n"
            )
            writer.write(redirect_response.encode())
            await writer.drain()
            writer.close()
            return
            
        # Session exists
        session.touch()
        target_port = challenge_config['target_port']
        
        try:
             # Connect to container
            container_reader, container_writer = await asyncio.open_connection(
                session.container_ip, target_port
            )
            await self.proxy_data(reader, writer, container_reader, container_writer, session)
        except Exception as e:
            logger.error(f"[{session.session_id}] Proxy error: {e}")
            writer.close()

    async def proxy_data(self, reader, writer, container_reader, container_writer, session=None):
        async def forward(src, dst, update_session=False):
            try:
                while True:
                    data = await src.read(4096)
                    if not data: break
                    if update_session and session: session.touch()
                    dst.write(data)
                    await dst.drain()
            except: pass
            finally:
                try: dst.close()
                except: pass

        await asyncio.gather(
            forward(reader, container_writer, update_session=True),
            forward(container_reader, writer)
        )

    # --- Main Loop ---

    async def shutdown(self):
        logger.info("Shutting down Orchestrator...")
        
        # Stop all active sessions
        tasks = []
        for port, session in self.sessions.items():
            logger.info(f"Using shutdown to stop session {session.session_id} on port {port}")
            tasks.append(stop_challenge(session.session_id, session.config, session.network_name))
        
        if tasks:
            await asyncio.gather(*tasks)
        
        logger.info("Shutdown complete.")

    async def start(self):
        servers = []
        logger.info("Starting Orchestrator...")
        
        # 1. Start Cleanup Task
        cleanup_task = asyncio.create_task(self.cleanup_task())

        # 2. Bind Ports
        for challenge in self.config:
            # Main Port Binding
            port = challenge['port']
            mode = challenge.get('mode', ChallengeMode.LIVE)
            
            if mode == ChallengeMode.LIVE:
                # Closure to capture specific challenge config
                async def live_cb(r, w, c=challenge):
                    await self.handle_live_connection(r, w, c)
                servers.append(await asyncio.start_server(live_cb, '0.0.0.0', port))
                logger.info(f"Listening on {port} (LIVE) for {challenge['folder']}")

            elif mode == ChallengeMode.REDIRECT:
                # Landing Port
                async def active_cb(r, w, c=challenge):
                    await self.handle_landing_connection(r, w, c)
                servers.append(await asyncio.start_server(active_cb, '0.0.0.0', port))
                logger.info(f"Listening on {port} (REDIRECT LANDING) for {challenge['folder']}")

                # Instance Pool Ports
                pr = challenge.get('port_range')
                if pr:
                    for p in range(pr[0], pr[1] + 1):
                        async def pool_cb(r, w, p_num=p, c=challenge):
                            await self.handle_instance_connection(r, w, p_num, c)
                        servers.append(await asyncio.start_server(pool_cb, '0.0.0.0', p))
                    logger.info(f"Listening on {pr[0]}-{pr[1]} (POOL) for {challenge['folder']}")

        logger.info("Starting TaskGroup...")
        
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def signal_handler():
            logger.info("Signal received, initiating shutdown...")
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, signal_handler)
            except NotImplementedError:
                # Signal handling might not work on Windows in certain loops/threads
                # Fallback to KeyboardInterrupt in main
                pass

        async with asyncio.TaskGroup() as tg:
            for server in servers:
                tg.create_task(server.serve_forever())
            
            # Wait for stop signal
            await stop_event.wait()
            
            # Cancel servers
            logger.info("Stopping servers...")
            for server in servers:
                server.close()
                await server.wait_closed()
            
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

            # Run shutdown cleanup
            await self.shutdown()
            # TaskGroup will wait for other tasks, but we handled them.

if __name__ == "__main__":
    orc = Orchestrator()
    try:
        # On Windows, add_signal_handler is not implemented for ProactorEventLoop (default)
        # We need to rely on KeyboardInterrupt for local run, or careful handling.
        # However, docker sends SIGTERM.
        # For now, let's try standard run.
        asyncio.run(orc.start())
    except KeyboardInterrupt:
        # Fallback if signal handler didn't catch it (e.g. Windows ctrl+c)
        pass
