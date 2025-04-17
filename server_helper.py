#!/usr/bin/env python3

import os
import subprocess
import time
import json
import re
import sys
import threading
from github_helper import pull_latest, commit_and_push

# Ensure unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

def start_server(server_id, server_type, initialize_only=False):
    print(f"Starting {server_type} server for {server_id}")
    server_dir = f"servers/{server_id}"
    os.makedirs(server_dir, exist_ok=True)
    os.chdir(server_dir)

    # Create EULA file
    with open("eula.txt", "w") as f:
        f.write("eula=true\n")
    print(f"Created eula.txt with eula=true in {server_dir}")

    # Define command
    if server_type == "vanilla":
        cmd = ["java", "-Xmx2G", "-Xms2G", "-jar", "server.jar", "nogui"]
    elif server_type == "paper":
        cmd = ["java", "-Xmx2G", "-Xms2G", "-XX:+UseG1GC", "-jar", "server.jar", "nogui"]
    elif server_type == "forge":
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

    # Create default server.properties if missing
    if not os.path.exists("server.properties"):
        print(f"Creating default server.properties in {server_dir}")
        with open("server.properties", "w") as f:
            f.write("enable-jmx-monitoring=false\nrcon.port=25575\nlevel-seed=\ngamemode=survival\n")
            f.write("enable-command-block=true\nenable-query=false\ngenerator-settings={}\nlevel-name=world\n")
            f.write("motd=A Minecraft Server\nquery.port=25565\npvp=true\ndifficulty=easy\n")
            f.write("network-compression-threshold=256\nmax-tick-time=60000\nrequire-resource-pack=false\n")
            f.write("max-players=20\nuse-native-transport=true\nonline-mode=true\nenable-status=true\n")
            f.write("allow-flight=false\nbroadcast-rcon-to-ops=true\nview-distance=10\nserver-ip=\n")
            f.write("resource-pack-prompt=\nallow-nether=true\nserver-port=25565\nenable-rcon=false\n")
            f.write("sync-chunk-writes=true\nop-permission-level=4\nprevent-proxy-connections=false\n")
            f.write("hide-online-players=false\nresource-pack=\nentity-broadcast-range-percentage=100\n")
            f.write("simulation-distance=10\nrcon.password=\nplayer-idle-timeout=0\nforce-gamemode=false\n")
            f.write("rate-limit=0\nhardcore=false\nwhite-list=false\nbroadcast-console-to-ops=true\n")
            f.write("spawn-npcs=true\nspawn-animals=true\nfunction-permission-level=2\nlevel-type=minecraft\\:normal\n")
            f.write("text-filtering-config=\nspawn-monsters=true\nenforce-whitelist=false\nspawn-protection=16\n")
            f.write("resource-pack-sha1=\nmax-world-size=29999984\n")

    print(f"Executing command: {cmd}")

    # Start server process
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

    initialized = False

    def read_output():
        nonlocal initialized
        try:
            for line in iter(process.stdout.readline, ''):
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

    timeout = 300
    start_time = time.time()
    print(f"Waiting for server initialization (timeout: {timeout} seconds)...")

    while not initialized and time.time() - start_time < timeout:
        time.sleep(1)
        if process.poll() is not None:
            print(f"Server process ended prematurely with code: {process.returncode}")
            return False

    if not initialized:
        print(f"Server initialization timed out after {timeout} seconds")

    if initialize_only:
        print("Waiting for server to shut down...")
        output_thread.join(timeout=30)
        process.wait(timeout=30)
        print("Server shutdown complete")
        return True

    print("Server fully initialized and running")
    return process

def setup_cloudflared_tunnel():
    print("Setting up Cloudflare tunnel", flush=True)
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "tcp://localhost:25565"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )
    print(f"Cloudflared process started with PID: {tunnel_process.pid}", flush=True)
    start_time = time.time()
    tunnel_url = None
    print("Waiting for tunnel URL...", flush=True)
    while time.time() - start_time < 30:
        output = tunnel_process.stdout.readline()
        print(f"CLOUDFLARED: {output.strip()}", flush=True)
        match = re.search(r'tcp://[a-zA-Z0-9\-]+\.trycloudflare\.com', output)
        if match:
            tunnel_url = match.group(0)
            print(f"Found tunnel URL: {tunnel_url}", flush=True)
            break
    if not tunnel_url:
        print("Failed to get tunnel URL within timeout", flush=True)
    return tunnel_url, tunnel_process

def write_status_file(server_id, tunnel_url, running=True):
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
    try:
        write_status_file(server_id, tunnel_url, running=False)
    except Exception as e:
        print(f"Failed to set server inactive on exit: {e}")

def load_server_config(server_id):
    pull_latest()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Server config not found: {config_path}", flush=True)
        return None
    with open(config_path, 'r') as f:
        return json.load(f)

if __name__ == "__main__":
    pull_latest()
    if len(sys.argv) < 3:
        print("Usage: server_helper.py <server_id> <server_type> [initialize_only]")
        sys.exit(1)

    server_id = sys.argv[1]
    server_type = sys.argv[2]
    initialize_only = len(sys.argv) > 3 and sys.argv[3].lower() == "true"

    config = load_server_config(server_id)
    if not config:
        print("Could not load server config.")
        sys.exit(1)
    tunnel_url = config.get('tunnel_url')

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

        if not tunnel_url:
            tunnel_url, tunnel_process = setup_cloudflared_tunnel()
            if not tunnel_url:
                print("Failed to set up Cloudflare tunnel")
                server_process.terminate()
                set_server_inactive_on_exit(server_id, tunnel_url)
                sys.exit(1)

        write_status_file(server_id, tunnel_url, running=True)

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