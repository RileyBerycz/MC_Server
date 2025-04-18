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

    # Check for existing world folder
    if initialize_only:
        if os.path.exists("world") and os.path.isdir("world"):
            print("World folder already exists, skipping initialization.")
            return True

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

def setup_cloudflared_tunnel(tunnel_name):
    # Set the environment variable for cloudflared to find cert.pem
    cert_path = os.path.expanduser("~/.cloudflared/cert.pem")
    os.environ["TUNNEL_ORIGIN_CERT"] = cert_path
    print(f"Setting up Cloudflare named tunnel: {tunnel_name}", flush=True)
    print(f"Running command: cloudflared tunnel run {tunnel_name}", flush=True)
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "run", tunnel_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=os.environ.copy()
    )
    def print_tunnel_output():
        for line in iter(tunnel_process.stdout.readline, ''):
            print(f"CLOUDFLARED: {line.strip()}", flush=True)
    threading.Thread(target=print_tunnel_output, daemon=True).start()
    print(f"Cloudflared process started with PID: {tunnel_process.pid}", flush=True)
    return tunnel_process

def write_status_file(server_id, running=True):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        return False
    with open(config_path, 'r') as f:
        config = json.load(f)
    config['is_active'] = running
    if running:
        config['last_started'] = int(time.time())
    else:
        config['last_stopped'] = int(time.time())
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"Updated config for {server_id}: is_active={running}")
    commit_and_push(config_path, f"Update running status for {server_id}")
    return True

def set_server_inactive_on_exit(server_id):
    try:
        write_status_file(server_id, running=False)
    except Exception as e:
        print(f"Failed to set server inactive on exit: {e}")

def load_server_config(server_id):
    pull_latest()
    BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Server config not found: {config_path}", flush=True)
        return None
    with open(config_path, 'r') as f:
        return json.load(f)

def process_pending_command(server_id, server_process):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Config file {config_path} missing. Stopping server gracefully.")
        if server_process and server_process.stdin:
            server_process.stdin.write('stop\n')
            server_process.stdin.flush()
            time.sleep(2)
            server_process.terminate()
        return False
    with open(config_path, 'r') as f:
        config = json.load(f)
    pending_command = config.get('pending_command')
    if pending_command:
        print(f"Processing command: {pending_command}")
        server_process.stdin.write(pending_command + '\n')
        server_process.stdin.flush()
        config['last_command_response'] = f"Sent: {pending_command}"
        config['pending_command'] = ""
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
    return True

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

    address = config.get('address')

    if initialize_only:
        success = start_server(server_id, server_type, initialize_only=True)
        set_server_inactive_on_exit(server_id)
        sys.exit(0 if success else 1)
    else:
        server_process = start_server(server_id, server_type)
        if not server_process:
            print("Failed to start server")
            set_server_inactive_on_exit(server_id)
            sys.exit(1)

        tunnel_name = config.get('subdomain')
        tunnel_process = setup_cloudflared_tunnel(tunnel_name)

        write_status_file(server_id, running=True)

        import atexit
        atexit.register(set_server_inactive_on_exit, server_id)

        try:
            print("Server is running. Press Ctrl+C to stop.", flush=True)
            while True:
                time.sleep(5)
                if not process_pending_command(server_id, server_process):
                    print("Config missing, server stopped.")
                    break
                BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
                config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    if config.get('shutdown_request'):
                        print("Shutdown requested via config. Stopping server...", flush=True)
                        config['shutdown_request'] = False
                        with open(config_path, 'w') as f:
                            json.dump(config, f, indent=2)
                        server_process.stdin.write('stop\n')
                        server_process.stdin.flush()
                        break
                else:
                    print("Config file missing during shutdown check. Stopping server.")
                    server_process.stdin.write('stop\n')
                    server_process.stdin.flush()
                    break
        except KeyboardInterrupt:
            print("Stopping server and tunnel", flush=True)
            server_process.terminate()
            if 'tunnel_process' in locals():
                tunnel_process.terminate()
        finally:
            set_server_inactive_on_exit(server_id)
        sys.exit(0)
