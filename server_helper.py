#!/usr/bin/env python3

import os
import subprocess
import time
import json
import re
import sys
import threading
import socket
from github_helper import pull_latest, commit_and_push

# Ensure unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# Set BASE_DIR once, before any os.chdir
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def start_server(server_id, server_type, initialize_only=False):
    print(f"Starting {server_type} server for {server_id}")
    server_dir = f"servers/{server_id}"
    os.makedirs(server_dir, exist_ok=True)
    os.chdir(server_dir)

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

    # NEW: Ensure server has correct IP binding for tunneling
    ensure_correct_server_ip(server_dir)

    # Check for existing world folder - fixed to look for the world directory
    if initialize_only:
        world_path = "world"
        if os.path.exists(world_path) and os.path.isdir(world_path):
            print(f"World folder already exists at {server_dir}/{world_path}, skipping initialization.")
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

    print(f"Executing command: {cmd}")

    # Start server process
    if server_type == "bedrock":
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True,
            shell=True,
            bufsize=1
        )
    else:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
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

def ensure_correct_server_ip(server_dir):
    """
    Ensure server.properties has the correct IP binding for tunneling.
    For Cloudflare Tunnel to work, the server must bind to 0.0.0.0 or be empty.
    """
    properties_path = os.path.join(server_dir, "server.properties")
    if not os.path.exists(properties_path):
        print("server.properties not found, will be created with default settings")
        return
        
    # Read current properties
    with open(properties_path, "r") as f:
        lines = f.readlines()
    
    # Check and update server-ip setting
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("server-ip="):
            value = line.strip().split("=", 1)[1] if "=" in line else ""
            if value not in ["", "0.0.0.0"]:
                print(f"⚠️ Found restrictive server-ip={value} in server.properties")
                lines[i] = "server-ip=0.0.0.0\n"
                updated = True
                print("✅ Updated server-ip to 0.0.0.0 for better tunnel compatibility")
    
    # Write back if changed
    if updated:
        with open(properties_path, "w") as f:
            f.writelines(lines)

def setup_cloudflared_tunnel(subdomain, tunnel_name):
    tunnel_id, creds_path = write_tunnel_creds_file(subdomain)
    print(f"Setting up Cloudflare named tunnel: {tunnel_name} (ID: {tunnel_id})", flush=True)
    
    # Create a config file with ingress rules - fixed to work with temporary URLs
    config_dir = os.path.expanduser("~/.cloudflared")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, f"config-{tunnel_id}.yaml")
    
    with open(config_path, "w") as f:
        f.write(f"tunnel: {tunnel_id}\n")
        f.write(f"credentials-file: {creds_path}\n")
        f.write("ingress:\n")
        # Named hostname route for the domain
        f.write(f"  - hostname: {subdomain}.rileyberycz.co.uk\n")
        f.write("    service: tcp://localhost:25565\n")
        # Default catch-all - MUST BE LAST
        f.write("  - service: http_status:404\n")
    
    print(f"Created config file with ingress rules at {config_path}", flush=True)
    
    # Create a separate temporary tunnel for direct testing
    temp_config_path = os.path.join(config_dir, "temp-tunnel-config.yaml")
    print(f"Setting up temporary tunnel for direct TCP testing...", flush=True)
    
    # Start tunnel with only the --url flag to generate a temporary URL
    print(f"Running command: cloudflared tunnel --url tcp://localhost:25565", flush=True)
    
    temp_tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "tcp://localhost:25565"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=os.environ.copy()
    )
    
    # Start the main tunnel separately
    print(f"Running command: cloudflared tunnel --config {config_path} run {tunnel_name}", flush=True)
    tunnel_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--config", config_path, "run", tunnel_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=os.environ.copy()
    )
    
    # Handle output from both tunnels
    def print_temp_tunnel_output():
        for line in iter(temp_tunnel_process.stdout.readline, ''):
            print(f"TEMP-CLOUDFLARED: {line.strip()}", flush=True)
            # Look for temporary URL in output
            if "trycloudflare.com" in line:
                print("\n" + "="*70)
                print(f"✨ TEMPORARY CLOUDFLARE TCP URL DETECTED! ✨")
                url_match = re.search(r'(https?://[^\s]+)', line)
                if url_match:
                    temp_url = url_match.group(1)
                    print(f"Try connecting to Minecraft using: {temp_url.replace('https://', '')}")
                    print("(Use just the domain part without https:// in Minecraft)")
                else:
                    print(f"Try connecting to: {line.strip()}")
                print("="*70 + "\n")
    
    def print_tunnel_output():
        for line in iter(tunnel_process.stdout.readline, ''):
            print(f"CLOUDFLARED: {line.strip()}", flush=True)
    
    threading.Thread(target=print_temp_tunnel_output, daemon=True).start()
    threading.Thread(target=print_tunnel_output, daemon=True).start()
    
    print(f"Cloudflared processes started - main tunnel PID: {tunnel_process.pid}, temp tunnel PID: {temp_tunnel_process.pid}", flush=True)
    return tunnel_process

def setup_serveo_tunnel(server_id):
    """Setup a Serveo SSH tunnel for the Minecraft server"""
    print("\n" + "="*70)
    print("SETTING UP SERVEO TUNNEL")
    print("="*70)
    
    # Get the server configuration
    config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    subdomain = config.get('subdomain')
    print(f"Server configured to use subdomain: {subdomain}")
    
    # Load the Serveo mapping
    serveo_map_path = os.path.join(BASE_DIR, "serveo_tunnel_map.json")
    if not os.path.exists(serveo_map_path):
        print(f"⚠️ Serveo mapping file not found: {serveo_map_path}")
        print("Creating empty mapping file")
        with open(serveo_map_path, 'w') as f:
            json.dump({}, f, indent=2)
        serveo_map = {}
    else:
        try:
            with open(serveo_map_path, "r") as f:
                serveo_map = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ Serveo mapping file is not valid JSON, creating empty mapping")
            serveo_map = {}
    
    # Find the correct serveo entry
    serveo_entry = None
    
    # First, try to find the subdomain as a direct key in the map
    if subdomain in serveo_map:
        serveo_entry = serveo_map[subdomain]
        print(f"✅ Found direct match for subdomain {subdomain} in map")
    else:
        # If not found as a key, search through all entries
        for key, entry in serveo_map.items():
            # Check against updated_subdomain first, then original_subdomain
            if entry.get('updated_subdomain') == subdomain or entry.get('original_subdomain') == subdomain:
                serveo_entry = entry
                print(f"✅ Found subdomain match in the map under key: {key}")
                break
    
    # If still not found, use a random subdomain
    if not serveo_entry:
        print(f"⚠️ No Serveo mapping found for subdomain {subdomain}")
        import random
        import string
        random_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        serveo_subdomain = f"mc-{random_id}"
        serveo_domain = f"{serveo_subdomain}.serveo.net"
        print(f"✅ Using generated Serveo subdomain: {serveo_subdomain}")
    else:
        serveo_domain = serveo_entry.get('serveo_domain')
        serveo_subdomain = serveo_domain.split(".")[0]
        print(f"✅ Using predefined Serveo domain: {serveo_domain}")
    
    # Save the serveo domain to the config
    config['serveo_domain'] = serveo_domain
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    commit_and_push(config_path, f"Update Serveo domain for {server_id}")
    
    # Ensure SSH key is accepted automatically
    print("Setting up SSH for Serveo...", flush=True)
    home_dir = os.path.expanduser("~")
    os.makedirs(f"{home_dir}/.ssh", exist_ok=True)
    ssh_known_hosts = f"{home_dir}/.ssh/known_hosts"
    if not os.path.exists(ssh_known_hosts):
        open(ssh_known_hosts, 'a').close()
    
    subprocess.run(f"ssh-keyscan -H serveo.net >> {home_dir}/.ssh/known_hosts", shell=True)
    
    # Start the SSH tunnel
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-R", f"{serveo_subdomain}:25565:localhost:25565", "serveo.net"]
    print(f"Starting Serveo tunnel with command: {' '.join(cmd)}", flush=True)
    
    # Start the tunnel process
    tunnel_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=os.environ.copy()
    )
    
    # Monitor output to verify the connection
    def monitor_serveo_output():
        tunnel_verified = False
        for line in iter(tunnel_process.stdout.readline, ''):
            print(f"SERVEO: {line.strip()}", flush=True)
            
            # Look for successful connection
            if "Forwarding" in line and "serveo.net" in line:
                verified_domain = re.search(r'to ([a-zA-Z0-9.-]+\.serveo\.net)', line)
                if verified_domain:
                    assigned_domain = verified_domain.group(1)
                    tunnel_verified = True
                    
                    # Update the config with the actual domain if different
                    if assigned_domain != serveo_domain:
                        config['serveo_domain'] = assigned_domain
                        with open(config_path, 'w') as f:
                            json.dump(config, f, indent=2)
                        commit_and_push(config_path, f"Update with actual Serveo domain for {server_id}")
                    
                    print("\n" + "="*70)
                    print(f"✨ SERVEO TUNNEL ESTABLISHED! ✨")
                    print(f"Connect to Minecraft using: {assigned_domain}")
                    print("="*70 + "\n")
            
            # Look for errors
            if "Error" in line or "error" in line:
                print(f"⚠️ Serveo tunnel error detected: {line.strip()}")
    
    threading.Thread(target=monitor_serveo_output, daemon=True).start()
    
    # Wait for connection to establish
    time.sleep(5)
    
    return tunnel_process

def write_tunnel_creds_file(subdomain):
    """Extract credentials for a specific tunnel and write to file."""
    tunnel_map_path = os.path.join(BASE_DIR, "tunnel_id_map.json")
    
    # Handle missing tunnel_id_map.json file
    if not os.path.exists(tunnel_map_path):
        print(f"Warning: {tunnel_map_path} not found, downloading from Google Drive...")
        
        try:
            import requests
            
            # Get file ID from Google Drive URL
            file_id = "15RPnvXey81FA0XtBfWlBLA41K03-Ghg0"
            
            # Google Drive direct download URL format
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            
            # Download the file
            response = requests.get(download_url)
            
            if response.status_code == 200:
                # Create directory if needed
                os.makedirs(os.path.dirname(tunnel_map_path), exist_ok=True)
                
                # Save the file
                with open(tunnel_map_path, "w") as f:
                    f.write(response.text)
                    
                print(f"Successfully downloaded tunnel_id_map.json from Google Drive")
            else:
                print(f"Failed to download from Google Drive: {response.status_code}")
                raise Exception("Could not download tunnel map file")
                
        except Exception as e:
            print(f"Error downloading tunnel map: {e}")
            raise Exception(f"Could not retrieve tunnel map: {e}")
    
    # Now load the file (either existing or downloaded)
    with open(tunnel_map_path, "r") as f:
        try:
            tunnel_id_map = json.load(f)
        except json.JSONDecodeError:
            print("Error: Downloaded file is not valid JSON")
            raise Exception("Invalid JSON in tunnel_id_map.json")
    
    # Get the FQDN for lookup
    fqdn = f"{subdomain}.rileyberycz.co.uk"
    
    # Handle the new format with updated_domain
    if fqdn in tunnel_id_map:
        if isinstance(tunnel_id_map[fqdn], dict):
            tunnel_id = tunnel_id_map[fqdn].get("tunnel_id")
        else:
            tunnel_id = tunnel_id_map[fqdn]
    else:
        print(f"No tunnel ID found for {fqdn} in tunnel_id_map.json")
        raise Exception(f"No tunnel mapping for {fqdn}")
    
    # Rest of your existing code...
    creds_env = os.environ.get("CLOUDFLARE_TUNNELS_CREDS")
    if not creds_env:
        raise Exception("CLOUDFLARE_TUNNELS_CREDS environment variable not set")

    pattern = rf'{tunnel_id}[^{{]*{{[^}}]*AccountTag[^:]*:\s*([^,\n]+)[^}}]*TunnelSecret[^:]*:\s*([^,\n]+)[^}}]*TunnelID[^:]*:\s*([^,\n]+)[^}}]*Endpoint[^:]*:\s*([^}}]*)}}'
    
    match = re.search(pattern, creds_env, re.DOTALL)
    if match:
        account_tag = match.group(1).strip().strip('"')
        tunnel_secret = match.group(2).strip().strip('"')
        tunnel_id_value = match.group(3).strip().strip('"')
        endpoint = match.group(4).strip().strip('"')
        
        tunnel_creds = {
            "AccountTag": account_tag,
            "TunnelSecret": tunnel_secret,
            "TunnelID": tunnel_id_value,
            "Endpoint": endpoint
        }
        
        os.makedirs(os.path.expanduser("~/.cloudflared"), exist_ok=True)
        creds_path = os.path.expanduser(f"~/.cloudflared/tunnel-{tunnel_id}.json")
        with open(creds_path, "w") as f:
            json.dump(tunnel_creds, f)
        print(f"Successfully extracted credentials for tunnel {tunnel_id}")
        return tunnel_id, creds_path
    else:
        print(f"Could not extract credentials for tunnel: {tunnel_id}")
        raise Exception(f"Could not extract credentials for tunnel: {tunnel_id}")

def write_status_file(server_id, running=True):
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
        print("⚠️ Server exit detected - ensuring inactive status", flush=True)
        write_status_file(server_id, running=False)
        ensure_server_inactive(server_id)  # Double-check the inactive status
    except Exception as e:
        print(f"Failed to set server inactive on exit: {e}")
        # Last resort attempt - direct file write without Git operations
        try:
            config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config = json.load(f)
                config['is_active'] = False
                config['last_stopped'] = int(time.time())
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                print("Emergency config update: Server marked as inactive")
        except Exception as e2:
            print(f"All attempts to mark server inactive failed: {e2}")

# Add this function to ensure multiple status updates don't conflict
def ensure_server_inactive(server_id):
    """Make absolutely sure the server is marked as inactive on shutdown"""
    try:
        # Force a Git pull to get latest config state
        pull_latest()
        
        config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            
            # Track if we need to update the config
            need_update = False
            
            # Check and update active status
            if config.get('is_active', False):
                print("⚠️ Server still marked as active during shutdown - forcing inactive status")
                config['is_active'] = False
                config['last_stopped'] = int(time.time())
                need_update = True
            
            # Check and reset shutdown_request flag
            if config.get('shutdown_request', False):
                print("⚠️ Resetting shutdown_request flag to prevent restart issues")
                config['shutdown_request'] = False
                need_update = True
            
            # Only write and commit if we made changes
            if need_update:
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                commit_and_push(config_path, f"Update status for {server_id} on shutdown (inactive and reset flags)")
                print("✅ Server status updated correctly")
    except Exception as e:
        print(f"⚠️ Failed to update server status: {e}")

def load_server_config(server_id):
    pull_latest()
    config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Server config not found: {config_path}", flush=True)
        return None
    with open(config_path, 'r') as f:
        return json.load(f)

def process_pending_command(server_id, server_process):
    config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
    if not os.path.exists(config_path):
        print(f"Config file {config_path} missing. Stopping server gracefully.")
        if server_process and hasattr(server_process, 'stdin') and server_process.stdin:
            try:
                server_process.stdin.write('stop\n')
                server_process.stdin.flush()
                time.sleep(2)
                server_process.terminate()
            except Exception as e:
                print(f"Error sending stop command: {e}")
                server_process.terminate()
        return False
    
    try:
        pull_latest()
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        pending_command = config.get('pending_command', '')
        if pending_command:
            print(f"Processing command: {pending_command}")
            
            if not pending_command.startswith('/') and pending_command != 'stop':
                command_to_send = f'/{pending_command}\n'
            else:
                command_to_send = f'{pending_command}\n'
            
            try:
                print(f"Sending command to server: {command_to_send.strip()}")
                server_process.stdin.write(command_to_send)
                server_process.stdin.flush()
                config['last_command_response'] = f"Sent: {pending_command}"
                config['pending_command'] = ""
                
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                commit_and_push(config_path, f"Cleared pending command after execution for {server_id}")
            except Exception as e:
                print(f"Error sending command to server: {e}")
                return False
    except Exception as e:
        print(f"Error processing pending command: {e}")
        return False
    
    return True

def validate_tunnel_map(subdomain=None):
    print("Validating tunnel map against DNS records...")
    mismatches = []
    
    try:
        with open(os.path.join(BASE_DIR, "tunnel_id_map.json"), "r") as f:
            tunnel_map = json.load(f)
        
        domains_to_check = {}
        if subdomain:
            fqdn = f"{subdomain}.rileyberycz.co.uk"
            if fqdn in tunnel_map:
                domains_to_check[fqdn] = tunnel_map[fqdn]
            else:
                print(f"Warning: {fqdn} not found in tunnel_id_map.json")
                return []
        else:
            domains_to_check = tunnel_map
        
        for fqdn, tunnel_id in domains_to_check.items():
            print(f"Checking {fqdn}...", end="", flush=True)
                
            dns_tunnel_id = lookup_dns_cname(fqdn)
            
            if dns_tunnel_id and dns_tunnel_id != tunnel_id:
                mismatch = {
                    "fqdn": fqdn,
                    "map_tunnel_id": tunnel_id,
                    "dns_tunnel_id": dns_tunnel_id
                }
                mismatches.append(mismatch)
                print(f" ❌ MISMATCH: DNS points to {dns_tunnel_id} but map has {tunnel_id}")
            elif dns_tunnel_id:
                print(f" ✅ Correct: {tunnel_id}")
            else:
                print(f" ⚠️ Warning: DNS lookup failed")
                
    except Exception as e:
        print(f"Error validating tunnel map: {e}")
        
    return mismatches

def lookup_dns_cname(domain):
    try:
        result = subprocess.check_output(["dig", "CNAME", domain, "+short"], universal_newlines=True).strip()
        if result and "cfargotunnel.com" in result:
            return result.split(".")[0]
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    try:
        result = subprocess.check_output(["nslookup", "-type=CNAME", domain], universal_newlines=True)
        match = re.search(r'canonical name = ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    try:
        result = subprocess.check_output(["host", "-t", "CNAME", domain], universal_newlines=True)
        match = re.search(r'is an alias for ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    try:
        result = subprocess.check_output(["nslookup", "-type=cname", domain], universal_newlines=True)
        match = re.search(r'canonical name = ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    return None

def is_dns_proxied(domain):
    try:
        cloudflare_ip_ranges = [
            "173.245.48.", "103.21.244.", "103.22.200.", "103.31.4.",
            "141.101.1.", "108.162.192.", "190.93.240.", "188.114.96.",
            "197.234.240.", "198.41.128.", "162.158.", "104.16.", "104.17.",
            "104.18.", "104.19.", "104.20.", "104.21.", "104.22.", "104.23.",
            "104.24.", "104.25.", "104.26.", "104.27."
        ]
        
        ip = socket.gethostbyname(domain)
        
        for ip_range in cloudflare_ip_ranges:
            if ip.startswith(ip_range):
                return True
                
        return False
    except Exception:
        return False

def setup_temp_tcp_tunnel():
    print("\nSetting up dedicated temporary TCP tunnel for Minecraft...")
    
    import uuid
    temp_tunnel_name = f"temp-mc-{uuid.uuid4().hex[:8]}"
    
    temp_tunnel_cmd = [
        "cloudflared", "tunnel", "--no-autoupdate",
        "--origincert", os.path.expanduser("~/.cloudflared/cert.pem"),
        "--no-tls-verify", 
        "--url", "tcp://localhost:25565"
    ]
    
    print(f"Starting temporary tunnel with command: {' '.join(temp_tunnel_cmd)}")
    
    temp_tunnel_process = subprocess.Popen(
        temp_tunnel_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
        env=os.environ.copy()
    )
    
    def print_temp_tunnel_output():
        for line in iter(temp_tunnel_process.stdout.readline, ''):
            print(f"TEMP-TCP: {line.strip()}", flush=True)
            
            if "trycloudflare.com" in line:
                    print("="*70 + "\n")
    
    threading.Thread(target=print_temp_tunnel_output, daemon=True).start()
    return temp_tunnel_process

def backup_server(server_id, backup_reason="scheduled"):
    print(f"\n=== Creating server backup for {server_id} ({backup_reason}) ===")
    server_dir = f"servers/{server_id}"
    backup_dir = os.path.join(BASE_DIR, "backups", server_id)
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_file = os.path.join(backup_dir, f"{server_id}-{timestamp}.zip")
    
    try:
        backup_paths = ["world", "server.properties", "ops.json", "whitelist.json", 
                        "banned-players.json", "banned-ips.json"]
        
        existing_paths = []
        for path in backup_paths:
            full_path = os.path.join(server_dir, path)
            if os.path.exists(full_path):
                existing_paths.append(path)
        
        if not existing_paths:
            print(f"No data to backup for {server_id}")
            return False
            
        import zipfile
        with zipfile.ZipFile(backup_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
            original_dir = os.getcwd()
            os.chdir(server_dir)
            
            for path in existing_paths:
                if os.path.isdir(path):
                    for root, _, files in os.walk(path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path)
                else:
                    zipf.write(path)
                    
            os.chdir(original_dir)
        
        print(f"Backup created at {backup_file}")
        
        config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        config['last_backup'] = int(time.time())
        config['last_backup_file'] = backup_file
        
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            
        commit_and_push(config_path, f"Update backup info for {server_id}")
        
        prune_backups(server_id, keep_count=10)
        
        return True
    except Exception as e:
        print(f"Error creating backup: {e}")
        return False

def prune_backups(server_id, keep_count=10):
    backup_dir = os.path.join(BASE_DIR, "backups", server_id)
    if not os.path.exists(backup_dir):
        return
        
    try:
        backups = []
        for file in os.listdir(backup_dir):
            if file.startswith(f"{server_id}-") and file.endswith(".zip"):
                full_path = os.path.join(backup_dir, file)
                backups.append((full_path, os.path.getmtime(full_path)))
        
        backups.sort(key=lambda x: x[1], reverse=True)
        
        if len(backups) > keep_count:
            for path, _ in backups[keep_count:]:
                print(f"Removing old backup: {path}")
                os.remove(path)
    except Exception as e:
        print(f"Error pruning backups: {e}")

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
        ensure_server_inactive(server_id)
        sys.exit(0 if success else 1)
    else:
        server_process = start_server(server_id, server_type)
        if not server_process:
            print("Failed to start server")
            ensure_server_inactive(server_id)
            sys.exit(1)

        tunnel_name = config.get('subdomain')
        tunnel_process = setup_serveo_tunnel(server_id)

        # Add server binding verification
        print("\n" + "="*70)
        print("VERIFYING SERVER BINDING...")
        try:
            # Check server binding using subprocess
            netstat_output = subprocess.check_output("netstat -tulpn | grep java", shell=True).decode('utf-8')
            print(f"Server binding information:\n{netstat_output}")

            # Test connection to localhost
            nc_process = subprocess.run(["nc", "-z", "-v", "localhost", "25565"],
                                         stderr=subprocess.PIPE,
                                         text=True)
            if nc_process.returncode == 0:
                print("✅ Server is accessible from localhost!")
            else:
                print(f"⚠️ Connection test failed: {nc_process.stderr}")

            # Also test direct HTTP request to server to check if it responds
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex(('localhost', 25565))
            if result == 0:
                print("✅ Socket connection to Minecraft server succeeded")
                # Try to get server status response
                sock.send(b'\xfe\x01')
                response = sock.recv(1024)
                print(f"Server response: {response}")
            else:
                print(f"⚠️ Socket connection failed with error code {result}")
            sock.close()
        except Exception as e:
            print(f"Error during verification: {e}")

        print("="*70)
        print(f"✨ MINECRAFT SERVER READY! ✨")
        print(f"📌 CONNECT USING: {config.get('serveo_domain')}")
        print(f"🎮 Minecraft version: 1.20.4")
        print("="*70 + "\n")

        write_status_file(server_id, running=True)

        import atexit
        atexit.register(set_server_inactive_on_exit, server_id)

        try:
            print("Server is running. Press Ctrl+C to stop.", flush=True)
            start_time = time.time()
            last_backup_time = start_time
            
            # Check if running in GitHub Actions
            is_github_actions = os.environ.get('GITHUB_ACTIONS') == 'true'
            if is_github_actions:
                print(f"⚠️ Running in GitHub Actions environment - will respect max_runtime={config.get('max_runtime', 45)} hours")
                # For GitHub Actions, don't restart on max_runtime, just exit
                config['restart_on_max_runtime'] = False
            
            while True:
                time.sleep(5)
                current_time = time.time()
                
                pull_latest()
                
                runtime_hours = (current_time - start_time) / 3600
                if config.get('max_runtime') and runtime_hours >= config.get('max_runtime'):
                    print(f"\n=== Maximum runtime of {config.get('max_runtime')} hours reached ===")
                    print("Creating backup and restarting server...")
                    
                    backup_server(server_id, backup_reason="max_runtime")
                    
                    try:
                        server_process.stdin.write('say Server will restart in 60 seconds due to scheduled maintenance\n')
                        server_process.stdin.flush()
                        time.sleep(30)
                        server_process.stdin.write('say Server will restart in 30 seconds\n')
                        server_process.stdin.flush()
                        time.sleep(20)
                        server_process.stdin.write('say Server will restart in 10 seconds\n')
                        server_process.stdin.flush()
                        time.sleep(10)
                    except Exception as e:
                        print(f"Error sending restart warnings: {e}")
                    
                    try:
                        server_process.stdin.write('stop\n')
                        server_process.stdin.flush()
                        
                        print("Waiting for server to stop gracefully...")
                        for _ in range(30):
                            if server_process.poll() is not None:
                                print("Server stopped gracefully!")
                                ensure_server_inactive(server_id)
                                break
                            time.sleep(1)
                        
                        if server_process.poll() is None:
                            print("Server didn't stop gracefully, terminating...")
                            server_process.terminate()
                    except Exception as e:
                        print(f"Error stopping server for restart: {e}")
                        server_process.terminate()
                    
                    if 'tunnel_process' in locals():
                        tunnel_process.terminate()
                        
                    print("\n=== Restarting server and tunnels ===")
                    server_process = start_server(server_id, server_type)
                    if not server_process:
                        print("Failed to restart server")
                        ensure_server_inactive(server_id)
                        sys.exit(1)
                        
                    tunnel_name = config.get('subdomain')
                    tunnel_process = setup_serveo_tunnel(server_id)
                    
                    start_time = time.time()
                    last_backup_time = start_time
                    print("Server successfully restarted!")
                    continue
                
                backup_interval_hours = config.get('backup_interval', 0)
                if backup_interval_hours > 0:
                    hours_since_backup = (current_time - last_backup_time) / 3600
                    if hours_since_backup >= backup_interval_hours:
                        print(f"\n=== Periodic backup interval of {backup_interval_hours} hours reached ===")
                        
                        if backup_server(server_id, backup_reason="scheduled"):
                            last_backup_time = current_time
                            print("Periodic backup completed successfully")
                
                prune_backups(server_id, keep_count=config.get('backup_keep_count', 10))
                
                if not process_pending_command(server_id, server_process):
                    print("Config missing or command processing failed, server stopped.")
                    break
                    
                config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    
                    if config.get('shutdown_request'):
                        print("Shutdown requested via config. Stopping server...", flush=True)
                        
                        backup_server(server_id, backup_reason="shutdown")
                        
                        try:
                            print("Sending stop command to server")
                            server_process.stdin.write('stop\n')
                            server_process.stdin.flush()
                            
                            print("Waiting for server to stop gracefully...")
                            for _ in range(30):
                                if server_process.poll() is not None:
                                    print("Server stopped gracefully!")
                                    ensure_server_inactive(server_id)
                                    break
                                time.sleep(1)
                        except Exception as e:
                            print(f"Error stopping server: {e}")
                            server_process.terminate()
                            ensure_server_inactive(server_id)
                            break
                else:
                    print("Config file missing during shutdown check. Stopping server.")
                    try:
                        server_process.stdin.write('stop\n')
                        server_process.stdin.flush()
                    except Exception:
                        server_process.terminate()
                    ensure_server_inactive(server_id)
                    break
        except KeyboardInterrupt:
            print("Stopping server and tunnel", flush=True)
            server_process.terminate()
            if 'tunnel_process' in locals():
                tunnel_process.terminate()
        finally:
            ensure_server_inactive(server_id)
        sys.exit(0)

