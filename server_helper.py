#!/usr/bin/env python3
# filepath: c:\Projects\MinecraftServer\MC_Server\server_helper.py

import os
import subprocess
import time
import json
import re
import sys
import signal
import threading
from github_helper import pull_latest, commit_and_push
# Ensure unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def start_server(server_id, server_type, initialize_only=False):
    """
    Start a Minecraft server of the specified type
    If initialize_only=True, it will start the server just long enough to generate files
    """
    print(f"Starting {server_type} server for {server_id}")
    server_dir = f"servers/{server_id}"
    
    # Make sure the directory exists
    os.makedirs(server_dir, exist_ok=True)
    os.chdir(server_dir)
    
    # Create EULA file before starting the server
    with open("eula.txt", "w") as f:
        f.write("eula=true\n")
        
    print(f"Created eula.txt with eula=true in {server_dir}")
    
    # Define commands for different server types
    if server_type == "vanilla":
        cmd = ["java", "-Xmx2G", "-Xms2G", "-jar", "server.jar", "nogui"]
    elif server_type == "paper":
        cmd = ["java", "-Xmx2G", "-Xms2G", "-XX:+UseG1GC", "-jar", "server.jar", "nogui"]
    elif server_type == "forge":
        # Find the forge jar file
        forge_jar = [f for f in os.listdir(".") if f.startswith("forge") and f.endswith(".jar") and "installer" not in f]
        if forge_jar:
            cmd = ["java", "-Xmx2G", "-Xms2G", "-jar", forge_jar[0], "nogui"]
        else:
            print("Error: Forge jar not found")
            return False
    elif server_type == "fabric":
        if os.path.exists("fabric-server-launch.jar"):
            cmd = ["java", "-Xmx2G", "-Xms2G", "-jar", "fabric-server-launch.jar", "nogui"]
        else:
            cmd = ["java", "-Xmx2G", "-Xms2G", "-jar", "server.jar", "nogui"]
    elif server_type == "bedrock":
        cmd = "LD_LIBRARY_PATH=. ./bedrock_server"
    else:
        print(f"Unknown server type: {server_type}")
        return False
    
    # Create server.properties with defaults if it doesn't exist
    if not os.path.exists("server.properties"):
        print(f"Creating default server.properties in {server_dir}")
        with open("server.properties", "w") as f:
            f.write("enable-jmx-monitoring=false\n")
            f.write("rcon.port=25575\n")
            f.write("level-seed=\n")
            f.write("gamemode=survival\n")
            f.write("enable-command-block=true\n")
            f.write("enable-query=false\n")
            f.write("generator-settings={}\n")
            f.write("level-name=world\n")
            f.write("motd=A Minecraft Server\n")
            f.write("query.port=25565\n")
            f.write("pvp=true\n")
            f.write("difficulty=easy\n")
            f.write("network-compression-threshold=256\n")
            f.write("max-tick-time=60000\n")
            f.write("require-resource-pack=false\n")
            f.write("max-players=20\n")
            f.write("use-native-transport=true\n")
            f.write("online-mode=true\n")
            f.write("enable-status=true\n")
            f.write("allow-flight=false\n")
            f.write("broadcast-rcon-to-ops=true\n")
            f.write("view-distance=10\n")
            f.write("server-ip=\n")
            f.write("resource-pack-prompt=\n")
            f.write("allow-nether=true\n")
            f.write("server-port=25565\n")
            f.write("enable-rcon=false\n")
            f.write("sync-chunk-writes=true\n")
            f.write("op-permission-level=4\n")
            f.write("prevent-proxy-connections=false\n")
            f.write("hide-online-players=false\n")
            f.write("resource-pack=\n")
            f.write("entity-broadcast-range-percentage=100\n")
            f.write("simulation-distance=10\n")
            f.write("rcon.password=\n")
            f.write("player-idle-timeout=0\n")
            f.write("force-gamemode=false\n")
            f.write("rate-limit=0\n")
            f.write("hardcore=false\n")
            f.write("white-list=false\n")
            f.write("broadcast-console-to-ops=true\n")
            f.write("spawn-npcs=true\n")
            f.write("spawn-animals=true\n")
            f.write("function-permission-level=2\n")
            f.write("level-type=minecraft\\:normal\n")
            f.write("text-filtering-config=\n")
            f.write("spawn-monsters=true\n")
            f.write("enforce-whitelist=false\n")
            f.write("spawn-protection=16\n")
            f.write("resource-pack-sha1=\n")
            f.write("max-world-size=29999984\n")
    
    print(f"Executing command: {cmd}")
    
    # Create a pipe for the subprocess to allow reading output
    if server_type == "bedrock":
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            shell=True,
            bufsize=1
        )
    else:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
    
    print(f"Server process started with PID: {process.pid}")
    
    # Track if the server has finished initializing
    initialized = False
    
    # Set up a thread to read the output
    def read_output():
        nonlocal initialized
        try:
            for line in iter(process.stdout.readline, ''):
                # Add flush=True to ensure output appears immediately
                print(f"SERVER OUTPUT: {line.strip()}", flush=True)
                if "Done" in line and "For help, type" in line:
                    print("Server initialization completed!", flush=True)
                    initialized = True
                    if initialize_only:
                        print("Server initialized, shutting down", flush=True)
                        process.terminate()
                        break
        except Exception as e:
            print(f"Error reading server output: {e}", flush=True)
    
    output_thread = threading.Thread(target=read_output)
    output_thread.daemon = True
    output_thread.start()
    
    # Wait for server to initialize or timeout
    timeout = 300  # 5 minutes
    start_time = time.time()
    print(f"Waiting for server initialization (timeout: {timeout} seconds)...")
    
    while not initialized and time.time() - start_time < timeout:
        time.sleep(1)
        # Check if process has ended
        if process.poll() is not None:
            print(f"Server process ended prematurely with code: {process.returncode}")
            return False
    
    if not initialized:
        print(f"Server initialization timed out after {timeout} seconds")
    
    # If we're just initializing, wait for process to fully end
    if initialize_only:
        print("Waiting for server to shut down...")
        output_thread.join(timeout=30)
        process.wait(timeout=30)
        print("Server shutdown complete")
        return True
    
    # Otherwise return the process
    print("Server fully initialized and running")
    return process

def setup_cloudflared_tunnel():
    """Setup a Cloudflare tunnel and return the tunnel URL"""
    print("Setting up Cloudflare tunnel", flush=True)
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "tcp://localhost:25565"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Combine stderr and stdout
        universal_newlines=True,
        bufsize=1  # Line buffering
    )
    
    print(f"Cloudflared process started with PID: {tunnel_process.pid}", flush=True)
    
    # Wait for the tunnel to start (up to 30 seconds)
    start_time = time.time()
    tunnel_url = None
    
    print("Waiting for tunnel URL...", flush=True)
    while time.time() - start_time < 30:
        output = tunnel_process.stdout.readline()
        # Print immediately with flush
        print(f"CLOUDFLARED: {output.strip()}", flush=True)
        
        # Look for the tunnel URL in the output
        match = re.search(r'tcp://[a-zA-Z0-9\-]+\.trycloudflare\.com', output)
        if match:
            tunnel_url = match.group(0)
            print(f"Found tunnel URL: {tunnel_url}", flush=True)
            break
    
    if not tunnel_url:
        print("Failed to get tunnel URL within timeout", flush=True)
    
    return tunnel_url, tunnel_process

def write_status_file(server_id, tunnel_url, running=True):
    """Update the server config with running status and address."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        return False
    with open(config_path, 'r') as f:
        config = json.load(f)
    config['is_active'] = running
    config['tunnel_url'] = tunnel_url
    if running:
        config['last_started'] = int(time.time())
    else:
        config['last_stopped'] = int(time.time())
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Updated config for {server_id}: is_active={running}, tunnel_url={tunnel_url}")
    commit_and_push(config_path, f"Update running status for {server_id}")
    return True

def set_server_inactive_on_exit(server_id, tunnel_url):
    """Set is_active to False in config on exit."""
    try:
        write_status_file(server_id, tunnel_url, running=False)
    except Exception as e:
        print(f"Failed to set server inactive on exit: {e}")

def pull_latest():
    """Pull the latest changes from the remote repository."""
    os.system('git pull --rebase --autostash')

def update_servers_status(server_id, status, extra=None):
    pull_latest()
    status_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'servers_status.json'))
    try:
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                all_status = json.load(f)
        else:
            all_status = {}
    except Exception:
        all_status = {}
    entry = {
        "status": status,
        "timestamp": int(time.time())
    }
    if extra:
        entry.update(extra)
    all_status[server_id] = entry
    with open(status_file, 'w') as f:
        json.dump(all_status, f, indent=2)
    print(f"Updated servers_status.json for {server_id}: {entry}", flush=True)
    # Commit and push after editing
    commit_and_push(status_file, f"Update status for {server_id}")

def load_server_config(server_id):
    pull_latest()  # Always pull latest before reading config
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Server config not found: {config_path}", flush=True)
        return None
    with open(config_path, 'r') as f:
        return json.load(f)

if __name__ == "__main__":
    pull_latest()  # Always pull latest before doing anything
    if len(sys.argv) < 3:
        print("Usage: server_helper.py <server_id> <server_type> [initialize_only]")
        sys.exit(1)

    server_id = sys.argv[1]
    server_type = sys.argv[2]
    initialize_only = len(sys.argv) > 3 and sys.argv[3].lower() == "true"

    # Load config and get tunnel info
    config = load_server_config(server_id)
    if not config:
        print("Could not load server config.")
        sys.exit(1)
    tunnel_url = config.get('tunnel_url')

    # Start server (initialize only or keep running)
    if initialize_only:
        success = start_server(server_id, server_type, initialize_only=True)
        set_server_inactive_on_exit(server_id, tunnel_url)
        sys.exit(0 if success else 1)
    else:
        server_process = start_server(server_id, server_type)
        if not server_process:
            print("Failed to start server")
            set_server_inactive_on_exit(server_id, tunnel_url)
            sys.exit(1)
        
        # Set up Cloudflare tunnel
        if not tunnel_url:
            tunnel_url, tunnel_process = setup_cloudflared_tunnel()
            if not tunnel_url:
                print("Failed to set up Cloudflare tunnel")
                server_process.terminate()
                set_server_inactive_on_exit(server_id, tunnel_url)
                sys.exit(1)
        
        # Mark as running
        write_status_file(server_id, tunnel_url, running=True)
        
        # Ensure we mark as inactive on any exit
        import atexit
        atexit.register(set_server_inactive_on_exit, server_id, tunnel_url)

        try:
            print("Server is running. Press Ctrl+C to stop.", flush=True)
            while True:
                time.sleep(30)
                if server_process.poll() is not None:
                    print(f"Server process ended with code: {server_process.returncode}", flush=True)
                    break
                print(f"Server still running. Last timestamp: {time.time()}", flush=True)
                write_status_file(server_id, tunnel_url, running=True)
        except KeyboardInterrupt:
            print("Stopping server and tunnel", flush=True)
            server_process.terminate()
            if 'tunnel_process' in locals():
                tunnel_process.terminate()
        finally:
            set_server_inactive_on_exit(server_id, tunnel_url)
        sys.exit(0)

