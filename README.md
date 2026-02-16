# CTF Docker Orchestrator POC

A dynamic, on-demand Docker container system for CTF environments.

## AI Disclaimer
This was developed by utilising heavy usage of AI, but all features and plans where made by me, 
but AI did the majority of coding/development, including creating the rest of this readme file.

## Features
- **On-Demand Containers**: Starts a fresh environment for every connection.
- **Redirect Mode**: Scalable Web challenges with ephemeral ports and specialized session management.
- **Auto-Cleanup**:
    - **Session Timeout**: Containers are destroyed after 5 minutes of inactivity (Redirect Mode).
    - **Disconnect**: Containers are destroyed immediately upon disconnection (Live Mode).
    - **Graceful Shutdown**: All active containers are destroyed when the orchestrator stops (`docker compose down`).
- **Optimization**: Shared images and smart request handling to save resources.

## Supported Challenges
1.  **Basic Netcat** (Port 2222): Simple Alpine loop shell (Live Mode).
2.  **SSH Challenge** (Port 2223): Full SSH server (Live Mode).
3.  **Web Challenge** (Port 8080 -> Redirects to 30010-30015): Python HTTP server (Redirect Mode).

## Setup
1.  **Prerequisites**: Docker Desktop (running on WSL2 or Linux) or Docker Engine.
2.  **Configuration (`challenges.json`)**:
    ```json
    {
      "port": 8080,
      "folder": "web_easy",
      "mode": "redirect",
      "port_range": [30010, 30015],
      "timeout": 300
    }
    ```

## Development Guide
- **Adding Web Challenges**:
    - Ensure `docker-compose.yml` specifies a fixed `image` name (e.g., `image: ctf_my_challenge:latest`) to avoid creating a new image for every instance.
    - Use `mode: "redirect"` in `challenges.json`.

## Deployment
1.  Build and start the orchestrator:
    ```bash
    docker compose up --build -d
    ```

2.  **Verify**:
    - **Web**: `http://localhost:8080` (Redirects to instance).
    - **SSH**: `ssh -p 2223 root@localhost` (Connects directly).
