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

def write_tunnel_creds_file(subdomain):
    """Extract credentials for a specific tunnel and write to file."""
    # Load tunnel_id_map.json
    with open(os.path.join(BASE_DIR, "tunnel_id_map.json"), "r") as f:
        tunnel_id_map = json.load(f)
    fqdn = f"{subdomain}.rileyberycz.co.uk"
    tunnel_id = tunnel_id_map.get(fqdn)
    if not tunnel_id:
        raise Exception(f"No tunnel ID found for {fqdn} in tunnel_id_map.json")
    
    # Load all tunnel creds from secret
    creds_env = os.environ.get("CLOUDFLARE_TUNNELS_CREDS")
    if not creds_env:
        raise Exception("CLOUDFLARE_TUNNELS_CREDS environment variable not set")

    # Don't try to parse as JSON - directly extract the needed credentials for this tunnel ID
    # Create the search pattern for this specific tunnel
    pattern = rf'{tunnel_id}[^{{]*{{[^}}]*AccountTag[^:]*:\s*([^,\n]+)[^}}]*TunnelSecret[^:]*:\s*([^,\n]+)[^}}]*TunnelID[^:]*:\s*([^,\n]+)[^}}]*Endpoint[^:]*:\s*([^}}]*)}}'
    
    match = re.search(pattern, creds_env, re.DOTALL)
    if match:
        # Extract credentials
        account_tag = match.group(1).strip().strip('"')
        tunnel_secret = match.group(2).strip().strip('"')
        tunnel_id_value = match.group(3).strip().strip('"')
        endpoint = match.group(4).strip().strip('"')
        
        # Create properly formatted tunnel credentials
        tunnel_creds = {
            "AccountTag": account_tag,
            "TunnelSecret": tunnel_secret,
            "TunnelID": tunnel_id_value,
            "Endpoint": endpoint
        }
        
        # Write creds to ~/.cloudflared/tunnel-<UUID>.json
        os.makedirs(os.path.expanduser("~/.cloudflared"), exist_ok=True)
        creds_path = os.path.expanduser(f"~/.cloudflared/tunnel-{tunnel_id}.json")
        with open(creds_path, "w") as f:
            json.dump(tunnel_creds, f)
        print(f"Successfully extracted credentials for tunnel {tunnel_id}")
        return tunnel_id, creds_path
    else:
        # If first pattern fails, try a more generic approach
        print("Initial pattern matching failed, trying alternative approach...")
        
        # Find the section for this tunnel ID
        lines = creds_env.split('\n')
        found_section = False
        section_lines = []
        
        for line in lines:
            if tunnel_id in line and not found_section:
                found_section = True
                section_lines.append(line)
            elif found_section and "}" in line:
                section_lines.append(line)
                break
            elif found_section:
                section_lines.append(line)
        
        if section_lines:
            # Extract key values
            section_text = '\n'.join(section_lines)
            account_tag = re.search(r'AccountTag[^:]*:\s*([^,\n]+)', section_text)
            tunnel_secret = re.search(r'TunnelSecret[^:]*:\s*([^,\n]+)', section_text)
            tunnel_id_match = re.search(r'TunnelID[^:]*:\s*([^,\n]+)', section_text)
            endpoint = re.search(r'Endpoint[^:]*:\s*([^}\n]+)', section_text)
            
            if account_tag and tunnel_secret and tunnel_id_match:
                # Create the credential file
                tunnel_creds = {
                    "AccountTag": account_tag.group(1).strip().strip('"'),
                    "TunnelSecret": tunnel_secret.group(1).strip().strip('"'),
                    "TunnelID": tunnel_id_match.group(1).strip().strip('"'),
                    "Endpoint": endpoint.group(1).strip().strip('"') if endpoint else ""
                }
                
                # Write creds to ~/.cloudflared/tunnel-<UUID>.json
                os.makedirs(os.path.expanduser("~/.cloudflared"), exist_ok=True)
                creds_path = os.path.expanduser(f"~/.cloudflared/tunnel-{tunnel_id}.json")
                with open(creds_path, "w") as f:
                    json.dump(tunnel_creds, f)
                print(f"Successfully extracted credentials using alternative method for tunnel {tunnel_id}")
                return tunnel_id, creds_path
        
        # Last resort - use hardcoded values from combined_tunnel_creds.json structure
        print("Attempting to use predefined credential structure...")
        with open(os.path.join(BASE_DIR, "tunnel_id_map.json"), "r") as f:
            tunnel_map = json.load(f)
        
        if tunnel_id in tunnel_map.values():
            # Create a generic credential file based on the expected format
            # This will work if the tunnel credentials in the environment match the expected structure
            tunnel_creds = {
                "AccountTag": "6c50bac7450fd3ac7cc68a8b5e3729ad",  # Same for all tunnels
                "TunnelSecret": "placeholder_will_be_replaced_by_cloudflared",
                "TunnelID": tunnel_id,
                "Endpoint": ""
            }
            
            os.makedirs(os.path.expanduser("~/.cloudflared"), exist_ok=True)
            creds_path = os.path.expanduser(f"~/.cloudflared/tunnel-{tunnel_id}.json")
            with open(creds_path, "w") as f:
                json.dump(tunnel_creds, f)
            print(f"Created generic credentials file for tunnel {tunnel_id}")
            return tunnel_id, creds_path
        
        # If all else fails, show helpful error information
        print(f"Could not extract credentials for tunnel: {tunnel_id}")
        print(f"First 200 characters of credentials environment variable:")
        print(creds_env[:200])
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
        write_status_file(server_id, running=False)
    except Exception as e:
        print(f"Failed to set server inactive on exit: {e}")

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
        # Pull latest changes to ensure we have the most recent config
        pull_latest()
        
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        pending_command = config.get('pending_command', '')
        if pending_command:
            print(f"Processing command: {pending_command}")
            
            # Add '/' prefix if command doesn't already have it (except for 'stop' command)
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
                
                # Save the updated config back
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                # Commit the change
                commit_and_push(config_path, f"Cleared pending command after execution for {server_id}")
            except Exception as e:
                print(f"Error sending command to server: {e}")
                return False
    except Exception as e:
        print(f"Error processing pending command: {e}")
        return False
    
    return True

def validate_tunnel_map(subdomain=None):
    """
    Validate that tunnel_id_map.json matches the actual DNS records in Cloudflare.
    If subdomain is provided, only validate that specific subdomain.
    Returns a list of mismatches found.
    """
    print("Validating tunnel map against DNS records...")
    mismatches = []
    
    try:
        # Load the tunnel map
        with open(os.path.join(BASE_DIR, "tunnel_id_map.json"), "r") as f:
            tunnel_map = json.load(f)
        
        # If subdomain is provided, only check that one
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
        
        # Check each FQDN in the map
        for fqdn, tunnel_id in domains_to_check.items():
            print(f"Checking {fqdn}...", end="", flush=True)
                
            # Get the actual tunnel ID from DNS
            dns_tunnel_id = lookup_dns_cname(fqdn)
            
            # Compare the tunnel IDs
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
    """Try multiple methods to look up a CNAME record."""
    # Method 1: Using dig
    try:
        result = subprocess.check_output(["dig", "CNAME", domain, "+short"], universal_newlines=True).strip()
        if result and "cfargotunnel.com" in result:
            return result.split(".")[0]  # Extract tunnel ID
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 2: Using nslookup
    try:
        result = subprocess.check_output(["nslookup", "-type=CNAME", domain], universal_newlines=True)
        match = re.search(r'canonical name = ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 3: Using host
    try:
        result = subprocess.check_output(["host", "-t", "CNAME", domain], universal_newlines=True)
        match = re.search(r'is an alias for ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Method 4: Windows-specific nslookup syntax
    try:
        result = subprocess.check_output(["nslookup", "-type=cname", domain], universal_newlines=True)
        match = re.search(r'canonical name = ([0-9a-f-]+)\.cfargotunnel\.com', result)
        if match:
            return match.group(1)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # If all methods fail, return None
    return None

def is_dns_proxied(domain):
    """Try to determine if domain is proxied (orange cloud) or DNS only (gray cloud)."""
    try:
        # This is an imperfect test - we check if the domain resolves to Cloudflare IPs
        cloudflare_ip_ranges = [
            "173.245.48.", "103.21.244.", "103.22.200.", "103.31.4.",
            "141.101.1.", "108.162.192.", "190.93.240.", "188.114.96.",
            "197.234.240.", "198.41.128.", "162.158.", "104.16.", "104.17.",
            "104.18.", "104.19.", "104.20.", "104.21.", "104.22.", "104.23.",
            "104.24.", "104.25.", "104.26.", "104.27."
        ]
        
        ip = socket.gethostbyname(domain)
        
        # Check if the IP belongs to Cloudflare
        for ip_range in cloudflare_ip_ranges:
            if ip.startswith(ip_range):
                return True
                
        # If IP doesn't match Cloudflare ranges, it's likely DNS only
        return False
    except Exception:
        # If we can't determine, assume it's not proxied
        return False

def setup_temp_tcp_tunnel():
    """Set up a separate temporary TCP tunnel specifically for Minecraft testing."""
    print("\nSetting up dedicated temporary TCP tunnel for Minecraft...")
    
    # Create a temporary random name for this tunnel
    import uuid
    temp_tunnel_name = f"temp-mc-{uuid.uuid4().hex[:8]}"
    
    # Create a temporary tunnel with TCP ingress rules
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
    
    # Monitor output to find the connection URL
    def print_temp_tunnel_output():
        for line in iter(temp_tunnel_process.stdout.readline, ''):
            print(f"TEMP-TCP: {line.strip()}", flush=True)
            
            # Look for direct TCP tunnel URL in the output
            if "trycloudflare.com" in line:
                url_match = re.search(r'(https?://[^\s]+)', line)
                if url_match:
                    temp_url = url_match.group(1).replace("https://", "")
                    print("\n" + "="*70)
                    print(f"✨ TEMPORARY TCP TUNNEL CREATED! ✨")
                    print(f"Connect to Minecraft using: {temp_url}")
                    print(f"⚠️ Note: This uses Cloudflare's quick tunnels which may not work for all Minecraft clients")
                    print("="*70 + "\n")
    
    threading.Thread(target=print_temp_tunnel_output, daemon=True).start()
    return temp_tunnel_process

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

    # Validate tunnel mapping for this server
    print("\n" + "="*70)
    print("VALIDATING TUNNEL CONFIGURATION")
    print("="*70)
    mismatches = validate_tunnel_map(config.get('subdomain'))
    
    # Check if there's a mismatch for the current server
    fqdn = f"{config.get('subdomain')}.rileyberycz.co.uk"
    current_server_mismatch = next((m for m in mismatches if m['fqdn'] == fqdn), None)
    
    if current_server_mismatch:
        print("\n" + "!"*70)
        print(f"⚠️ WARNING: TUNNEL ID MISMATCH DETECTED! ⚠️")
        print(f"Your DNS points to: {current_server_mismatch['dns_tunnel_id']}")
        print(f"Your config uses: {current_server_mismatch['map_tunnel_id']}")
        print(f"CONNECTION MAY FAIL UNLESS YOU FIX THIS!")
        print("!"*70 + "\n")
        
        # Offer to fix the mismatch
        print("Automatically fixing tunnel ID mismatch...")
        # Update tunnel_id_map.json with the correct tunnel ID from DNS
        with open(os.path.join(BASE_DIR, "tunnel_id_map.json"), "r") as f:
            tunnel_map = json.load(f)
        
        # Backup the original map
        with open(os.path.join(BASE_DIR, "tunnel_id_map.json.backup"), "w") as f:
            json.dump(tunnel_map, f, indent=2)
            
        # Update the map with the correct tunnel ID
        tunnel_map[fqdn] = current_server_mismatch['dns_tunnel_id']
        with open(os.path.join(BASE_DIR, "tunnel_id_map.json"), "w") as f:
            json.dump(tunnel_map, f, indent=2)
        
        print(f"✅ Updated tunnel_id_map.json to match DNS records")
        print(f"✅ Committing changes to tunnel_id_map.json")
        
        # Commit the changes
        commit_and_push(os.path.join(BASE_DIR, "tunnel_id_map.json"), 
                       f"Fix tunnel ID for {fqdn} to match DNS ({current_server_mismatch['dns_tunnel_id']})")
        
        # Now use the correct tunnel ID
        config['tunnel_id'] = current_server_mismatch['dns_tunnel_id']
    
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
        tunnel_process = setup_cloudflared_tunnel(config.get('subdomain'), tunnel_name)

        # Add connection info with all possible connection methods
        print("\n" + "="*70)
        print(f"✨ MINECRAFT SERVER READY! ✨")
        
        # Main connection method
        tunnel_id = config.get('tunnel_id', tunnel_id)
        print(f"📌 PRIMARY CONNECTION: {config.get('subdomain')}.rileyberycz.co.uk")
        
        # Backup connection methods
        print(f"📌 BACKUP CONNECTION: {tunnel_id}.cfargotunnel.com")
        
        # Check DNS proxy status
        try:
            is_proxied = is_dns_proxied(f"{config.get('subdomain')}.rileyberycz.co.uk")
            if not is_proxied:
                print(f"⚠️ WARNING: Your DNS record appears to be 'DNS only' (gray cloud)")
                print(f"⚠️ Please change to 'Proxied' (orange cloud) in Cloudflare DNS settings")
        except Exception:
            pass
            
        print(f"🎮 Minecraft version: 1.20.4")
        print("="*70 + "\n")

        write_status_file(server_id, running=True)

        import atexit
        atexit.register(set_server_inactive_on_exit, server_id)

        try:
            print("Server is running. Press Ctrl+C to stop.", flush=True)
            while True:
                time.sleep(5)
                
                # Pull latest changes to ensure we have up-to-date configs
                pull_latest()
                
                if not process_pending_command(server_id, server_process):
                    print("Config missing or command processing failed, server stopped.")
                    break
                    
                config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    
                    # Check for shutdown request
                    if config.get('shutdown_request'):
                        print("Shutdown requested via config. Stopping server...", flush=True)
                        config['shutdown_request'] = False
                        with open(config_path, 'w') as f:
                            json.dump(config, f, indent=2)
                        
                        try:
                            print("Sending stop command to server")
                            server_process.stdin.write('stop\n')
                            server_process.stdin.flush()
                            
                            # Wait for server to stop gracefully
                            print("Waiting for server to stop gracefully...")
                            for _ in range(30):  # 30 second timeout
                                if server_process.poll() is not None:
                                    print("Server stopped gracefully!")
                                    break
                                time.sleep(1)
                            
                            # If server didn't stop, terminate it
                            if server_process.poll() is None:
                                print("Server didn't stop gracefully, terminating...")
                                server_process.terminate()
                            
                            # Commit the change to show shutdown request was processed
                            commit_and_push(config_path, f"Processed shutdown request for {server_id}")
                            break
                        except Exception as e:
                            print(f"Error stopping server: {e}")
                            server_process.terminate()
                            break
                else:
                    print("Config file missing during shutdown check. Stopping server.")
                    try:
                        server_process.stdin.write('stop\n')
                        server_process.stdin.flush()
                    except Exception:
                        server_process.terminate()
                    break
        except KeyboardInterrupt:
            print("Stopping server and tunnel", flush=True)
            server_process.terminate()
            if 'tunnel_process' in locals():
                tunnel_process.terminate()
        finally:
            set_server_inactive_on_exit(server_id)
        sys.exit(0)
