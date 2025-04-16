#!/usr/bin/env python3
# server_helper.py

import os
import subprocess
import time
import json
import re
import sys
import signal
import threading

def start_server(server_id, server_type, initialize_only=False):
    """
    Start a Minecraft server of the specified type
    If initialize_only=True, it will start the server just long enough to generate files
    """
    print(f"Starting {server_type} server for {server_id}")
    server_dir = f"servers/{server_id}"
    os.chdir(server_dir)
    
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
        cmd = ["LD_LIBRARY_PATH=. ./bedrock_server"]
    else:
        print(f"Unknown server type: {server_type}")
        return False
    
    # Create server.properties with defaults if it doesn't exist
    if not os.path.exists("server.properties"):
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
    
    # Create a pipe for the subprocess to allow reading output
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )
    
    # Track if the server has finished initializing
    initialized = False
    
    # Set up a thread to read the output
    def read_output():
        nonlocal initialized
        for line in process.stdout:
            print(line, end='')
            if "Done" in line and "For help, type" in line:
                initialized = True
                if initialize_only:
                    print("Server initialized, shutting down for files generation")
                    process.terminate()
                    break
    
    output_thread = threading.Thread(target=read_output)
    output_thread.daemon = True
    output_thread.start()
    
    # Wait for server to initialize or timeout
    timeout = 300  # 5 minutes
    start_time = time.time()
    while not initialized and time.time() - start_time < timeout:
        time.sleep(1)
        # Check if process has ended
        if process.poll() is not None:
            print("Server process ended prematurely")
            return False
    
    # If we're just initializing, wait for process to fully end
    if initialize_only:
        output_thread.join(timeout=30)
        process.wait(timeout=30)
        return True
    
    # Otherwise return the process
    return process

def setup_cloudflared_tunnel():
    """Setup a Cloudflare tunnel and return the tunnel URL"""
    print("Setting up Cloudflare tunnel")
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "tcp://localhost:25565"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    # Wait for the tunnel to start (up to 30 seconds)
    start_time = time.time()
    tunnel_url = None
    while time.time() - start_time < 30:
        output = tunnel_process.stdout.readline()
        print(output, end='')
        # Look for the tunnel URL in the output
        match = re.search(r'tcp://[a-zA-Z0-9\-]+\.trycloudflare\.com', output)
        if match:
            tunnel_url = match.group(0)
            break
    
    if not tunnel_url:
        print("Failed to get tunnel URL")
        return None, None
    
    return tunnel_url, tunnel_process

def write_status_file(server_id, tunnel_url, running=True):
    """Write status.json with server info"""
    status = {
        "address": tunnel_url,
        "running": running,
        "timestamp": int(time.time())
    }
    
    with open(f"servers/{server_id}/status.json", "w") as f:
        json.dump(status, f)
    
    print(f"Status file written: {status}")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: server_helper.py <server_id> <server_type> [initialize_only]")
        sys.exit(1)
    
    server_id = sys.argv[1]
    server_type = sys.argv[2]
    initialize_only = len(sys.argv) > 3 and sys.argv[3].lower() == "true"
    
    # Start server (initialize only or keep running)
    if initialize_only:
        success = start_server(server_id, server_type, initialize_only=True)
        sys.exit(0 if success else 1)
    else:
        server_process = start_server(server_id, server_type)
        if not server_process:
            print("Failed to start server")
            sys.exit(1)
        
        # Set up Cloudflare tunnel
        tunnel_url, tunnel_process = setup_cloudflared_tunnel()
        if not tunnel_url:
            print("Failed to set up Cloudflare tunnel")
            server_process.terminate()
            sys.exit(1)
        
        # Write status.json
        write_status_file(server_id, tunnel_url)
        
        # Keep running until interrupted
        try:
            while True:
                time.sleep(1)
                # Check if server is still running
                if server_process.poll() is not None:
                    print("Server process ended")
                    break
        except KeyboardInterrupt:
            print("Stopping server and tunnel")
            server_process.terminate()
            tunnel_process.terminate()
            
        sys.exit(0)