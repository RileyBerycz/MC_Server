#!/usr/bin/env python3

import os
import subprocess
import time
import json
import sys
import threading
import re
import requests
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

    # Ensure server has correct IP binding
    ensure_correct_server_ip(server_dir)

    # Check for existing world folder
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
    """Ensure server.properties has the correct IP binding."""
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
                print("✅ Updated server-ip to 0.0.0.0 for better server accessibility")
    
    # Write back if changed
    if updated:
        with open(properties_path, "w") as f:
            f.writelines(lines)

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

def create_serveo_tunnel(server_id, minecraft_port=25565):
    """Create a tunnel using serveo.net and update existing SRV record with the port"""
    print("\n" + "="*70)
    print("SETTING UP SERVEO TUNNEL")
    print("="*70)
    
    # Get subdomain for this server from server_domains.json
    domain_name = get_server_domain(server_id)
    print(f"Using domain name: {domain_name}")
    
    # Ensure SSH known_hosts is set up
    home_dir = os.path.expanduser("~")
    os.makedirs(f"{home_dir}/.ssh", exist_ok=True)
    ssh_known_hosts = f"{home_dir}/.ssh/known_hosts"
    if not os.path.exists(ssh_known_hosts):
        open(ssh_known_hosts, 'a').close()
    
    subprocess.run(f"ssh-keyscan -H serveo.net >> {home_dir}/.ssh/known_hosts", shell=True)
    
    # Start the SSH tunnel to serveo.net with random port assignment
    tunnel_process = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-R", f"0:localhost:{minecraft_port}", "serveo.net"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    
    serveo_port = None
    tunnel_url_event = threading.Event()
    
    def process_tunnel_output():
        nonlocal serveo_port
        for line in iter(tunnel_process.stdout.readline, ''):
            print(f"TUNNEL: {line.strip()}", flush=True)
            if "Forwarding" in line and "TCP" in line:
                match = re.search(r'Forwarding TCP connections from ([^:]+):(\d+)', line)
                if match:
                    host, port = match.groups()
                    serveo_port = port
                    
                    # Display connection info
                    print("\n" + "="*70)
                    print(f"✨ TUNNEL ESTABLISHED ✨")
                    print(f"Serveo endpoint: {host}:{port}")
                    print(f"Updating SRV record for {domain_name} with port {port}")
                    print("="*70 + "\n")
                    
                    # Update ONLY the port on the existing SRV record
                    update_srv_record_port(domain_name, port)
                    
                    # Signal that we have the port
                    tunnel_url_event.set()
    
    tunnel_thread = threading.Thread(target=process_tunnel_output, daemon=True)
    tunnel_thread.start()
    
    # Wait for the tunnel URL to be established (with timeout)
    if not tunnel_url_event.wait(timeout=30):
        print("⚠️ Tunnel setup is taking longer than expected...")
    
    return tunnel_process, serveo_port, domain_name

def get_server_domain(server_id):
    """Get the domain name to use for this server from server_domains.json"""
    try:
        domains_path = os.path.join(BASE_DIR, "server_domains.json")
        with open(domains_path, 'r') as f:
            domains = json.load(f)
        
        # Get server number (assuming server_id format is like "3dc9675b")
        # Also check if there's a config file with a subdomain already specified
        config_path = os.path.join(BASE_DIR, 'server_configs', f'{server_id}.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                if config.get('subdomain'):
                    return config.get('subdomain')
        
        # For each server in server_domains.json, check if updated_domain is not empty
        for server_num, data in domains.items():
            if data.get('updated_domain'):
                # Check if this updated_domain matches our server's config
                if data.get('updated_domain', '').lower() == config.get('subdomain', '').lower():
                    return data.get('updated_domain')
        
        # If no match found, just return default domain from original 
        # For demo/testing just return "minecraft-test"
        return "minecraft-test"
        
    except Exception as e:
        print(f"Error getting server domain: {e}")
        return f"minecraft-{server_id}"

def update_srv_record_port(domain_name, port):
    """Update ONLY the port field of an existing SRV record"""
    try:
        # Get Cloudflare API credentials from environment
        cf_api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
        cf_zone_id = os.environ.get("CLOUDFLARE_ZONE_ID")
        
        if not cf_api_token or not cf_zone_id:
            print("⚠️ Cloudflare API credentials not found in environment variables")
            print(f"Manual SRV update required: Set port {port} for _minecraft._tcp.{domain_name}")
            return False
        
        # Record name in Cloudflare format
        record_name = f"_minecraft._tcp.{domain_name}"
        
        # Find the existing SRV record
        url = f"https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records"
        headers = {
            "Authorization": f"Bearer {cf_api_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            url,
            headers=headers,
            params={"name": record_name}
        )
        
        if response.status_code != 200:
            print(f"⚠️ Failed to query DNS records: {response.status_code}")
            return False
        
        records = response.json().get('result', [])
        if not records:
            print(f"⚠️ No SRV record found for {record_name}")
            return False
            
        # Update each matching SRV record with the new port
        for record in records:
            if record['type'] == 'SRV' and record['name'] == record_name:
                record_id = record['id']
                
                # Get the current data and update only the port
                current_data = record['data']
                current_data['port'] = int(port)
                
                # Update the record with new port
                update_url = f"{url}/{record_id}"
                update_data = {
                    "type": "SRV",
                    "name": record_name,
                    "data": current_data,
                    "ttl": 60
                }
                
                response = requests.put(update_url, headers=headers, json=update_data)
                
                if response.status_code == 200:
                    print(f"✅ Updated SRV record port for {domain_name} to {port}")
                    return True
                else:
                    print(f"⚠️ Failed to update SRV record: {response.status_code}")
                    print(f"Response: {response.text}")
                    return False
        
        print(f"⚠️ No matching SRV record found for {record_name}")
        return False
                
    except Exception as e:
        print(f"⚠️ Error updating SRV record port: {e}")
        return False

def ensure_ssh_client():
    """Ensure SSH client is installed on Linux systems."""
    try:
        result = subprocess.run(["ssh", "-V"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            print("⚠️ SSH client not found. Installing SSH client...")
            subprocess.run(["sudo", "apt-get", "install", "-y", "openssh-client"], check=True)
            print("✅ SSH client installed successfully.")
    except Exception as e:
        print(f"⚠️ Failed to ensure SSH client: {e}")

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

        # After starting the server
        if server_process:
            # Ensure SSH client is available
            import platform
            if platform.system() == "Linux":
                ensure_ssh_client()
            
            # Create the tunnel and update the SRV record
            tunnel_process, serveo_port, domain_name = create_serveo_tunnel(server_id)
            
            if serveo_port:
                print("\n" + "="*70)
                print(f"✨ MINECRAFT SERVER READY! ✨")
                print(f"📌 CONNECT USING: {domain_name}.yourdomain.co.uk")
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
                    
                    print("\n=== Restarting server ===")
                    server_process = start_server(server_id, server_type)
                    if not server_process:
                        print("Failed to restart server")
                        ensure_server_inactive(server_id)
                        sys.exit(1)
                    
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
                                    # Force exit after shutdown
                                    os._exit(0)
                                    break
                                time.sleep(1)
                        except Exception as e:
                            print(f"Error stopping server: {e}")
                            server_process.terminate()
                            ensure_server_inactive(server_id)
                            # Force exit after error
                            os._exit(1)
                            break
                else:
                    print("Config file missing during shutdown check. Stopping server.")
                    try:
                        server_process.stdin.write('stop\n')
                        server_process.stdin.flush()
                    except Exception:
                        server_process.terminate()
                    ensure_server_inactive(server_id)
                    # Force exit if config missing
                    os._exit(1)
                    break
        except KeyboardInterrupt:
            print("Stopping server", flush=True)
            server_process.terminate()
        finally:
            try:
                # Terminate all subprocesses
                if 'server_process' in locals() and server_process:
                    try:
                        server_process.terminate()
                        print("Terminated server process")
                    except:
                        pass
                        
                # Ensure server is marked as inactive in config
                ensure_server_inactive(server_id)
                print("Server shutdown complete. Exiting...")
                
                # Force exit the process completely
                os._exit(0)  # Use os._exit instead of sys.exit
            except Exception as e:
                print(f"Error during shutdown: {e}")
                os._exit(1)