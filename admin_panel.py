#!/usr/bin/env python3
import os
import sys
import time
import json
import uuid
import logging
import re
import subprocess
import traceback
import datetime
import requests
import threading
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from github_helper import pull_latest, commit_and_push

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SERVER_CONFIGS_DIR = 'server_configs'
UPLOADS_DIR = 'uploads'
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_OWNER = os.environ.get('GITHUB_REPOSITORY', '').split('/')[0] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else ''
REPO_NAME = os.environ.get('GITHUB_REPOSITORY', '').split('/')[1] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else ''
GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ZONE_ID = os.environ.get("CLOUDFLARE_ZONE_ID")
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_cloudflare_headers():
    return {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json"
    }

def list_minecraft_cnames():
    url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records?type=CNAME&per_page=100"
    resp = requests.get(url, headers=get_cloudflare_headers())
    resp.raise_for_status()
    records = resp.json()["result"]
    return [r for r in records if r["name"].startswith("minecraft-")]

def create_cname(subdomain, target):
    url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records"
    data = {
        "type": "CNAME",
        "name": f"{subdomain}.rileyberycz.co.uk",
        "content": target,
        "ttl": 120,
        "proxied": False
    }
    resp = requests.post(url, headers=get_cloudflare_headers(), json=data)
    resp.raise_for_status()
    print(f"Created CNAME {subdomain}.rileyberycz.co.uk -> {target}")
    return resp.json()["result"]

def rename_cname(old_subdomain, new_subdomain):
    records = list_minecraft_cnames()
    cname_record = next((r for r in records if r["name"] == f"{old_subdomain}.rileyberycz.co.uk"), None)
    if not cname_record:
        return False
    url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records/{cname_record['id']}"
    data = {
        "type": "CNAME",
        "name": f"{new_subdomain}.rileyberycz.co.uk",
        "content": cname_record["content"],
        "ttl": 120,
        "proxied": False
    }
    resp = requests.put(url, headers=get_cloudflare_headers(), json=data)
    resp.raise_for_status()
    print(f"Renamed CNAME {old_subdomain} to {new_subdomain}")
    return True

def get_next_free_minecraft_number():
    records = list_minecraft_cnames()
    used_numbers = set()
    for r in records:
        match = re.match(r"minecraft-(\d{3})\.rileyberycz\.co\.uk", r["name"])
        if match:
            used_numbers.add(int(match.group(1)))
    for i in range(1, 101):
        if i not in used_numbers:
            return f"{i:03d}"
    return None

def recycle_lowest_cname(preferred_subdomain):
    """
    Find the lowest numbered minecraft-XXX CNAME and rename it to the preferred subdomain.
    Returns the tunnel ID and the new subdomain.
    """
    # Get all minecraft-XXX CNAMEs from Cloudflare
    records = list_minecraft_cnames()
    used_numbers = []
    
    # Extract the numeric parts and sort them
    for r in records:
        match = re.match(r"minecraft-(\d{3})\.rileyberycz\.co\.uk", r["name"])
        if match:
            used_numbers.append((int(match.group(1)), r["name"]))
    
    if not used_numbers:
        logger.error("No minecraft CNAMEs found to recycle!")
        return None, preferred_subdomain  # Fallback
    
    # Sort by number to get the lowest
    used_numbers.sort()
    lowest_num, old_fqdn = used_numbers[0]
    old_subdomain = old_fqdn.split('.')[0]
    
    # Rename the CNAME in Cloudflare
    logger.info(f"Renaming CNAME from {old_subdomain} to {preferred_subdomain}")
    rename_success = rename_cname(old_subdomain, preferred_subdomain)
    
    if not rename_success:
        logger.error(f"Failed to rename CNAME {old_subdomain} -> {preferred_subdomain}")
        return None, preferred_subdomain  # Fallback
    
    # Update the tunnel map
    with open("tunnel_id_map.json", "r") as f:
        tunnel_map = json.load(f)
    
    # Get the tunnel ID associated with the old name
    tunnel_id = tunnel_map.pop(old_fqdn)
    
    # Add new mapping with the preferred subdomain
    new_fqdn = f"{preferred_subdomain}.rileyberycz.co.uk"
    tunnel_map[new_fqdn] = tunnel_id
    
    # Save the updated map
    with open("tunnel_id_map.json", "w") as f:
        json.dump(tunnel_map, f, indent=2)
    
    # Return the tunnel ID and the new subdomain
    return tunnel_id, preferred_subdomain

def recycle_subdomain_to_number(subdomain):
    """
    When deleting a server, rename its CNAME back to minecraft-XXX,
    where XXX is the lowest available number.
    """
    try:
        # Get all CNAMEs to find available numbers
        records = list_minecraft_cnames()
        used_numbers = set()
        
        for r in records:
            match = re.match(r"minecraft-(\d{3})\.rileyberycz\.co\.uk", r["name"])
            if match:
                used_numbers.add(int(match.group(1)))
        
        # Find the lowest available number
        next_num = None
        for i in range(1, 101):
            if i not in used_numbers:
                next_num = i
                break
                
        # If all numbers are used, just use 999 as fallback
        if next_num is None:
            next_num = 999
            
        # Format the new subdomain
        new_subdomain = f"minecraft-{next_num:03d}"
        
        # Rename the CNAME in Cloudflare
        rename_success = rename_cname(subdomain, new_subdomain)
        
        if not rename_success:
            logger.error(f"Failed to rename CNAME {subdomain} -> {new_subdomain}")
            return
        
        # Update the tunnel map
        with open("tunnel_id_map.json", "r") as f:
            tunnel_map = json.load(f)
        
        old_fqdn = f"{subdomain}.rileyberycz.co.uk"
        if old_fqdn in tunnel_map:
            tunnel_id = tunnel_map.pop(old_fqdn)
            new_fqdn = f"{new_subdomain}.rileyberycz.co.uk"
            tunnel_map[new_fqdn] = tunnel_id
            
            with open("tunnel_id_map.json", "w") as f:
                json.dump(tunnel_map, f, indent=2)
            
            logger.info(f"Recycled CNAME {subdomain} -> {new_subdomain}")
            
    except Exception as e:
        logger.error(f"Error recycling subdomain {subdomain}: {e}")

def remove_subdomain_from_tunnel_map(subdomain):
    """Remove subdomain from tunnel map and delete DNS record"""
    try:
        # Remove from tunnel_id_map.json
        with open("tunnel_id_map.json", "r") as f:
            tunnel_map = json.load(f)
        
        fqdn = f"{subdomain}.rileyberycz.co.uk"
        if fqdn in tunnel_map:
            del tunnel_map[fqdn]
            with open("tunnel_id_map.json", "w") as f:
                json.dump(tunnel_map, f, indent=2)
            
            # Also delete the DNS record
            if CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID:
                try:
                    # Find and delete the DNS record
                    url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records?type=CNAME&name={fqdn}"
                    resp = requests.get(url, headers=get_cloudflare_headers())
                    resp.raise_for_status()
                    records = resp.json()["result"]
                    
                    if records:
                        record_id = records[0]["id"]
                        delete_url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records/{record_id}"
                        requests.delete(delete_url, headers=get_cloudflare_headers())
                        logger.info(f"Deleted CNAME record for {fqdn}")
                except Exception as e:
                    logger.error(f"Failed to delete Cloudflare CNAME: {e}")
    except Exception as e:
        logger.error(f"Error removing subdomain from tunnel map: {e}")

def sanitize_subdomain(name):
    base = re.sub(r'[^a-z0-9\-]', '', re.sub(r'[\s_]+', '-', name.lower()))
    return f"minecraft-{base}"[:63]

def get_next_available_subdomain():
    used = set()
    with open("tunnel_id_map.json") as f:
        tunnel_map = json.load(f)
    for fqdn in tunnel_map.keys():
        if fqdn.startswith("minecraft-") and fqdn.endswith(".rileyberycz.co.uk"):
            used.add(fqdn.split(".")[0])
    for i in range(1, 101):
        sub = f"minecraft-{i:03d}"
        fqdn = f"{sub}.rileyberycz.co.uk"
        if sub not in used:
            return sub
    return None

def update_tunnel_domain(original_domain, new_domain):
    """
    Update the tunnel mapping when a domain is changed.
    
    Args:
        original_domain: The original domain name (e.g. minecraft-002.rileyberycz.co.uk)
        new_domain: The new domain name that replaces it
    """
    map_path = os.path.join(BASE_DIR, "tunnel_map.json")
    
    # Load current tunnel map
    with open(map_path, "r") as f:
        tunnel_map = json.load(f)
    
    # Check if the original domain exists in the map
    fqdn = f"{original_domain}.rileyberycz.co.uk" if ".rileyberycz.co.uk" not in original_domain else original_domain
    new_fqdn = f"{new_domain}.rileyberycz.co.uk" if ".rileyberycz.co.uk" not in new_domain else new_domain
    
    if fqdn in tunnel_map:
        # Save the entry
        entry = tunnel_map[fqdn]
        
        # Update the entry
        entry["updated_domain"] = new_fqdn
        
        # Remove old key and add new key
        tunnel_map.pop(fqdn)
        tunnel_map[new_fqdn] = entry
        
        # Save the updated map
        with open(map_path, "w") as f:
            json.dump(tunnel_map, f, indent=2)
            
        print(f"Updated tunnel map: {fqdn} → {new_fqdn}")
        return True
    else:
        print(f"Error: Domain {fqdn} not found in tunnel map")
        return False

def revert_tunnel_domain(current_domain):
    """
    Revert the tunnel mapping when a server is deleted.
    
    Args:
        current_domain: The current domain name to revert
    """
    map_path = os.path.join(BASE_DIR, "tunnel_map.json")
    
    # Load current tunnel map
    with open(map_path, "r") as f:
        tunnel_map = json.load(f)
    
    # Check if the domain exists in the map
    fqdn = f"{current_domain}.rileyberycz.co.uk" if ".rileyberycz.co.uk" not in current_domain else current_domain
    
    if fqdn in tunnel_map:
        # Save the entry
        entry = tunnel_map[fqdn]
        original_domain = entry["original_domain"]
        
        # Check if this is actually a renamed domain
        if entry["updated_domain"] and entry["original_domain"] != fqdn:
            # Clear the updated domain field
            entry["updated_domain"] = ""
            
            # Remove current key and restore original key
            tunnel_map.pop(fqdn)
            tunnel_map[original_domain] = entry
            
            # Save the updated map
            with open(map_path, "w") as f:
                json.dump(tunnel_map, f, indent=2)
                
            print(f"Reverted tunnel map: {fqdn} → {original_domain}")
        else:
            print(f"Domain {fqdn} is not renamed, no reversion needed")
            
        return True
    else:
        print(f"Error: Domain {fqdn} not found in tunnel map")
        return False

def load_server_configs():
    global servers
    pull_latest()
    servers = {}
    if os.path.exists(SERVER_CONFIGS_DIR):
        for filename in os.listdir(SERVER_CONFIGS_DIR):
            if filename.endswith('.json'):
                config_path = os.path.join(SERVER_CONFIGS_DIR, filename)
                try:
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    server_id = filename.replace('.json', '')
                    servers[server_id] = config
                except Exception as e:
                    logger.error(f"Error loading server config {filename}: {e}")
    return servers

def get_active_github_workflows():
    workflows = []
    try:
        if not GITHUB_TOKEN:
            logger.warning("GITHUB_TOKEN not set, cannot fetch workflows")
            return []
            
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
        response = requests.get(f"{GITHUB_API}/actions/runs?status=in_progress", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            for run in data.get('workflow_runs', []):
                server_id = None
                if 'server' in run.get('name', '').lower():
                    server_name = run.get('name').split(' - ', 1)[1] if ' - ' in run.get('name', '') else ''
                    for sid, sconfig in servers.items():
                        if sconfig.get('name') == server_name:
                            server_id = sid
                            break
                workflows.append({
                    'id': run.get('id'),
                    'name': run.get('name'),
                    'server_id': server_id,
                    'started_at': run.get('run_started_at'),
                    'url': run.get('html_url')
                })
            return workflows
        else:
            logger.error(f"Failed to fetch workflows: {response.status_code}")
            return []
    except Exception as e:
        logger.error(f"Error fetching workflows: {e}")
        return []

def calculate_memory(max_players):
    memory_mb = 1024 + (max_players * 50)
    memory_mb = ((memory_mb + 511) // 512) * 512
    memory_mb = min(memory_mb, 6144)
    return f"{memory_mb}M"

def setup_tunnels(port):
    """Set up both cloudflare and ngrok tunnels in parallel"""
    logger.info("Setting up tunnels for admin panel...")
    
    tunnels = {
        'cloudflare': None,
        'ngrok': None
    }
    
    # Start Cloudflare Tunnel
    try:
        logger.info(f"Starting cloudflared tunnel for port {port}...")
        cf_process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Start a thread to capture the cloudflare URL
        def capture_cf_url():
            for line in cf_process.stderr:
                match = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
                if match:
                    tunnels['cloudflare'] = match.group(0)
                    logger.info(f"Cloudflare tunnel established: {tunnels['cloudflare']}")
                    break
        
        cf_thread = threading.Thread(target=capture_cf_url)
        cf_thread.daemon = True
        cf_thread.start()
    except Exception as e:
        logger.error(f"Error starting Cloudflare tunnel: {e}")
    
    # Start ngrok Tunnel
    try:     
        # Configure ngrok with auth token if available
        ngrok_token = os.environ.get('NGROK_AUTH_TOKEN')
        if ngrok_token:
            # If using pyngrok library
            try:
                from pyngrok import ngrok, conf
                conf.get_default().auth_token = ngrok_token
                # Start tunnel
                logger.info(f"Starting ngrok tunnel on port {port}...")
                tunnel = ngrok.connect(port, "http")
                tunnels['ngrok'] = tunnel.public_url
            except ImportError:
                # Fallback to command line ngrok
                logger.info("pyngrok not available, using command line ngrok...")
                cmd = f"ngrok http {port}"
                if ngrok_token:
                    subprocess.run(f"ngrok authtoken {ngrok_token}", shell=True)
                ngrok_process = subprocess.Popen(
                    cmd, shell=True,
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
                # Parse ngrok URL from the API
                time.sleep(3)  # Give ngrok time to start
                try:
                    resp = requests.get("http://localhost:4040/api/tunnels")
                    data = resp.json()
                    for tunnel in data.get("tunnels", []):
                        if tunnel.get("proto") == "https":
                            tunnels['ngrok'] = tunnel.get("public_url")
                            break
                except Exception as e:
                    logger.error(f"Could not get ngrok URL from API: {e}")
        
        logger.info(f"ngrok tunnel established: {tunnels['ngrok']}")
    except Exception as e:
        logger.error(f"Error setting up ngrok tunnel: {e}")
    
    # Wait a moment to allow both tunnels to establish
    time.sleep(5)
    
    return tunnels

def get_public_admin_url():
    """Get the public URL for the admin panel, trying Cloudflare first, then ngrok"""
    # Try to use an existing tunnel from setup_tunnels
    # For Cloudflare
    try:
        cf_process = subprocess.Popen(
            ["cloudflared", "tunnel", "url"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = cf_process.communicate(timeout=2)
        for line in stdout.splitlines() + stderr.splitlines():
            match = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
            if match:
                return match.group(0)
    except Exception as e:
        logger.debug(f"Could not get Cloudflare URL: {e}")
    
    # Check for ngrok tunnel
    try:
        resp = requests.get("http://localhost:4040/api/tunnels", timeout=1)
        if resp.status_code == 200:
            tunnels = resp.json().get("tunnels", [])
            for tunnel in tunnels:
                if tunnel.get("proto") == "https":
                    return tunnel.get("public_url")
    except Exception as e:
        logger.debug(f"Could not get ngrok URL: {e}")
    
    # If we already have tunnel URLs from main(), use them
    admin_port = int(os.environ.get('ADMIN_PORT', '8080'))
    return f"http://localhost:{admin_port}"

app = Flask(__name__, 
            template_folder='admin_panel/templates', 
            static_folder='admin_panel/static')
app.secret_key = os.environ.get('SECRET_KEY', 'minecraft-default-secret')

servers = {}

@app.route('/')
def index():
    load_server_configs()
    current_year = datetime.datetime.now().year
    active_workflows = get_active_github_workflows()
    active_server_ids = {w.get('server_id') for w in active_workflows}
    for server_id, server in servers.items():
        server['is_active'] = server_id in active_server_ids or server.get('is_active', False)
    
    # Get and log the public URL
    public_url = get_public_admin_url()
    logger.info(f"Using admin panel URL: {public_url}")
    
    return render_template(
        'dashboard.html',
        servers=servers,
        active_workflows=active_workflows,
        current_year=current_year,
        REPO_OWNER=REPO_OWNER,
        REPO_NAME=REPO_NAME,
        public_url=public_url
    )

@app.route('/create-server', methods=['GET', 'POST'])
def create_server():
    if request.method == 'POST':
        server_name = request.form['server_name']
        server_type = request.form['server_type']
        max_players = int(request.form.get('max_players', 20))
        difficulty = request.form.get('difficulty', 'normal')
        gamemode = request.form.get('gamemode', 'survival')
        seed = request.form.get('seed', '')
        memory = request.form.get('memory', '')
        max_runtime = int(request.form.get('max_runtime', 350))
        backup_interval = float(request.form.get('backup_interval', 6.0))
        custom_subdomain = request.form.get('custom_subdomain', '')
        
        # Generate server ID
        server_id = str(uuid.uuid4())[:8]
        
        # Get user's preferred subdomain
        user_subdomain = custom_subdomain if custom_subdomain else server_name
        user_subdomain = sanitize_subdomain(user_subdomain)
        
        # Always recycle the lowest numbered CNAME
        tunnel_id, subdomain = recycle_lowest_cname(user_subdomain)
        
        # Update the tunnel map with the new domain
        original_domain = f"minecraft-{get_next_free_minecraft_number()}"
        update_tunnel_domain(original_domain, subdomain)
        
        # Create server config
        server_config = {
            'id': server_id,
            'name': server_name,
            'type': server_type,
            'max_players': max_players,
            'difficulty': difficulty,
            'gamemode': gamemode,
            'seed': seed,
            'memory': memory if memory else calculate_memory(max_players),
            'created_at': time.time(),
            'is_active': False,
            'max_runtime': max_runtime,
            'backup_interval': backup_interval,
            'subdomain': subdomain,
            'tunnel_url': f"https://{subdomain}.rileyberycz.co.uk"
        }
        
        # Save the server config
        save_server_config(server_id, server_config)
        
        # Create server directory and README
        server_dir = os.path.join("servers", server_id)
        os.makedirs(server_dir, exist_ok=True)
        readme_path = os.path.join(server_dir, "README.md")
        with open(readme_path, "w") as f:
            f.write(f"# {server_name}\n\nServer ID: {server_id}\nType: {server_type}\nCreated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Commit changes
        commit_and_push([
            os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json"),
            readme_path,
            os.path.join(BASE_DIR, "tunnel_map.json")  # Use the path directly
        ], f"Add new server config for {server_name} ({server_id})")
        
        flash(f'Server "{server_name}" created successfully with ID {server_id}!', 'success')
        return redirect(url_for('index'))
        
    # Define server types for the template
    SERVER_TYPES = {
        'vanilla': {
            'name': 'Vanilla',
            'download_url': 'https://piston-data.mojang.com/v1/objects/8dd1a28015f51b1803213892b50b7b4fc76e594d/server.jar',
            'supports_plugins': False,
            'supports_mods': False,
            'java_args': '-Xmx{memory} -Xms{memory}'
        },
        'paper': {
            'name': 'Paper',
            'download_url': 'https://api.papermc.io/v2/projects/paper/versions/1.21.4/builds/389/downloads/paper-1.21.4-389.jar',
            'supports_plugins': True,
            'supports_mods': False,
            'java_args': '-Xmx{memory} -Xms{memory} -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200'
        },
        'forge': {
            'name': 'Forge',
            'download_url': 'https://maven.minecraftforge.net/net/minecraftforge/forge/1.21.4-49.0.11/forge-1.21.4-49.0.11-installer.jar',
            'supports_plugins': False,
            'supports_mods': True,
            'java_args': '-Xmx{memory} -Xms{memory} -XX:+UseG1GC'
        },
        'fabric': {
            'name': 'Fabric',
            'download_url': 'https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.0/fabric-installer-1.1.0.jar',
            'supports_plugins': False,
            'supports_mods': True,
            'java_args': '-Xmx{memory} -Xms{memory}'
        },
        'bedrock': {
            'name': 'Bedrock',
            'download_url': 'https://minecraft.azureedge.net/bin-linux/bedrock-server-1.21.41.01.zip',
            'supports_plugins': False,
            'supports_mods': False,
            'java_args': ''
        }
    }
    return render_template('create_server.html', server_types=SERVER_TYPES)

@app.route('/server/<server_id>')
def view_server(server_id):
    load_server_configs()
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
        
    server = servers[server_id]
    server_dir = os.path.join("servers", server_id)
    properties_path = os.path.join(server_dir, "server.properties")
    
    if os.path.exists(properties_path):
        with open(properties_path, 'r') as f:
            server['server_properties'] = f.read()
    else:
        server['server_properties'] = ''
        
    active_workflows = get_active_github_workflows()
    server['is_active'] = any(w.get('server_id') == server_id for w in active_workflows) or server.get('is_active', False)
    
    if os.path.exists(server_dir):
        jar_files = [f for f in os.listdir(server_dir) if f.endswith('.jar') and f != 'server.jar']
        server['has_custom_jar'] = len(jar_files) > 0
        server['custom_jar_name'] = jar_files[0] if server['has_custom_jar'] else None
    else:
        server['has_custom_jar'] = False
        
    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
        server['last_command_response'] = config.get('last_command_response', '')
    else:
        server['last_command_response'] = ''
        
    return render_template('manage_server.html', 
                          server=server,
                          server_id=server_id,
                          REPO_OWNER=REPO_OWNER,
                          REPO_NAME=REPO_NAME)

@app.route('/server/<server_id>/start', methods=['POST'])
def start_server(server_id):
    load_server_configs()
    server_type = servers[server_id]['type']
    workflow_file = f"{server_type}_server.yml"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    data = {
        'ref': 'main',
        'inputs': {'server_id': server_id}
    }
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_file}/dispatches"
    response = requests.post(api_url, headers=headers, json=data)
    if response.status_code == 204:
        flash('Server is starting...', 'success')
    else:
        flash(f"Failed to start server workflow: {response.text}", 'error')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/stop', methods=['POST'])
def stop_server(server_id):
    load_server_configs()
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    config['shutdown_request'] = True
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    commit_and_push(config_path, f"Request shutdown for server {server_id}")
    flash('Shutdown requested. The server will stop shortly.', 'success')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/delete', methods=['POST', 'GET'])
def delete_server(server_id):
    load_server_configs()
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))

    if request.method == 'GET' and servers[server_id].get('is_active', False):
        return render_template('confirm_delete.html', server=servers[server_id], server_id=server_id)

    if servers[server_id].get('is_active', False):
        config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
        with open(config_path, 'r') as f:
            config = json.load(f)
        config['shutdown_request'] = True
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        commit_and_push(config_path, f"Request shutdown for server {server_id}")
        flash('Shutdown requested. Please wait for the server to stop before deleting.', 'warning')
        return redirect(url_for('view_server', server_id=server_id))

    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    files_to_commit = []
    subdomain = servers[server_id].get('subdomain')
    if subdomain:
        revert_tunnel_domain(subdomain)
        print(f"Reverted tunnel domain for {subdomain}")
        print(f"Files to be committed: {files_to_commit}")
        
        # Check and add both possible tunnel map files to ensure consistency
        tunnel_map_path = os.path.join(BASE_DIR, "tunnel_map.json")
        tunnel_id_map_path = os.path.join(BASE_DIR, "tunnel_id_map.json")
        
        if os.path.exists(tunnel_map_path):
            files_to_commit.append(tunnel_map_path)
        
        if os.path.exists(tunnel_id_map_path):
            files_to_commit.append(tunnel_id_map_path)
    if os.path.exists(config_path):
        os.remove(config_path)
        files_to_commit.append(config_path)
    server_dir = os.path.join("servers", server_id)
    if os.path.exists(server_dir):
        import shutil
        shutil.rmtree(server_dir)
        files_to_commit.append(server_dir)
    server_name = servers[server_id].get('name', 'Unnamed Server')
    del servers[server_id]
    print(f"Files to be committed: {files_to_commit}")
    commit_and_push(files_to_commit, f"Delete server {server_name} ({server_id})")
    flash(f'Server "{server_name}" has been deleted.', 'success')
    return redirect(url_for('index'))

@app.route('/server/<server_id>/upload-jar', methods=['POST'])
def upload_server_jar(server_id):
    if 'jar_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    file = request.files['jar_file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    if file and file.filename.endswith('.jar'):
        server_dir = os.path.join("servers", server_id)
        os.makedirs(server_dir, exist_ok=True)
        filename = secure_filename(file.filename)
        file_path = os.path.join(server_dir, filename)
        file.save(file_path)
        commit_and_push(file_path, f"Upload custom JAR for {server_id}")
        flash(f'Server JAR file "{filename}" uploaded successfully', 'success')
    else:
        flash('Invalid file type. Please upload a JAR file.', 'error')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/download-jar', methods=['POST'])
def download_server_jar(server_id):
    jar_url = request.form.get('jar_url', '')
    if not jar_url:
        flash('Please provide a download URL', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    try:
        server_dir = os.path.join("servers", server_id)
        os.makedirs(server_dir, exist_ok=True)
        response = requests.get(jar_url, stream=True)
        if response.status_code == 200:
            filename = jar_url.split('/')[-1]
            if not filename.endswith('.jar'):
                filename += '.jar'
            filename = secure_filename(filename)
            file_path = os.path.join(server_dir, filename)
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            commit_and_push(file_path, f"Download server JAR for {server_id}")
            flash(f'Server JAR file "{filename}" downloaded successfully', 'success')
        else:
            flash(f'Failed to download JAR file: {response.status_code}', 'error')
    except Exception as e:
        flash(f'Error downloading JAR file: {str(e)}', 'error')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/send-command', methods=['POST'])
def send_command(server_id):
    load_server_configs()
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    command = request.form.get('command', '').strip()
    if not command:
        flash('No command entered.', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    with open(config_path, 'r') as f:
        config = json.load(f)
    config['pending_command'] = command
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    commit_and_push(config_path, f"Send command to server {server_id}")
    flash(f'Command "{command}" sent to server.', 'success')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/edit-properties', methods=['POST'])
def edit_properties(server_id):
    load_server_configs()
    if server_id not in servers:
        flash('Server not found.', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    server_dir = os.path.join("servers", server_id)
    properties_path = os.path.join(server_dir, "server.properties")
    new_properties = request.form.get('properties', '')
    try:
        with open(properties_path, 'w') as f:
            f.write(new_properties)
        commit_and_push(properties_path, f"Update server.properties for {server_id}")
        flash('server.properties updated successfully.', 'success')
    except Exception as e:
        flash(f'Failed to update server.properties: {e}', 'error')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/shutdown', methods=['POST'])
def shutdown_server_route():
    """Shutdown the admin panel and exit the process."""
    with open("SHUTDOWN_REQUESTED", "w") as f:
        f.write("Shutdown requested at " + str(datetime.datetime.now()))
    func = request.environ.get('werkzeug.server.shutdown')
    if func:
        func()
    else:
        os._exit(0)  # Fallback: force exit if not running with Werkzeug
    return render_template('shutdown.html')

def main():
    admin_port = int(os.environ.get('ADMIN_PORT', '8080'))
    print("GITHUB_TOKEN present:", bool(GITHUB_TOKEN))
    print("REPO_OWNER:", REPO_OWNER)
    print("REPO_NAME:", REPO_NAME)
    for directory in [SERVER_CONFIGS_DIR, "servers", ".github/workflows", 
                     ".github/workflows/server_templates", UPLOADS_DIR, 
                     "admin_panel/templates", "admin_panel/static/css"]:
        try:
            if os.path.exists(directory) and not os.path.isdir(directory):
                os.rename(directory, f"{directory}.bak")
                print(f"Renamed existing file '{directory}' to '{directory}.bak'")
            os.makedirs(directory, exist_ok=True)
            print(f"Directory created/verified: {directory}")
        except Exception as e:
            print(f"Warning: Issue with directory '{directory}': {e}")
    
    load_server_configs()
    
    # Set up both tunnels for public access
    tunnel_urls = setup_tunnels(admin_port)
    
    # Display URLs to access admin panel
    if tunnel_urls['cloudflare']:
        print(f"\n✨ ADMIN PANEL via CLOUDFLARE: {tunnel_urls['cloudflare']} ✨")
        print(f"::notice::Admin Panel URL (Cloudflare): {tunnel_urls['cloudflare']}")
    else:
        print("\n⚠️ Cloudflare tunnel not established!")
    
    if tunnel_urls['ngrok']:
        print(f"\n✨ ADMIN PANEL via NGROK: {tunnel_urls['ngrok']} ✨")
        print(f"::notice::Admin Panel URL (ngrok): {tunnel_urls['ngrok']}")
    else:
        print("\n⚠️ ngrok tunnel not established!")
    
    if not tunnel_urls['cloudflare'] and not tunnel_urls['ngrok']:
        print("\n⚠️ WARNING: Failed to establish any tunnels! Admin panel will only be available locally at http://localhost:%d" % admin_port)
    
    # Run Flask app
    app.run(host='0.0.0.0', port=admin_port, debug=False)

if __name__ == "__main__":
    main()
