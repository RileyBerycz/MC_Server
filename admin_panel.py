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
from pyngrok import ngrok, conf 
from github_helper import pull_latest, commit_and_push

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SERVER_CONFIGS_DIR = 'server_configs'
UPLOADS_DIR = 'uploads'
SUBDOMAIN_POOL_FILE = "minecraft_subdomains.json"
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_OWNER = os.environ.get('GITHUB_REPOSITORY', '').split('/')[0] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else ''
REPO_NAME = os.environ.get('GITHUB_REPOSITORY', '').split('/')[1] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else ''
GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
CLOUDFLARE_ZONE_ID = os.environ.get("CLOUDFLARE_ZONE_ID")
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"

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

def delete_cname(subdomain):
    records = list_minecraft_cnames()
    for r in records:
        if r["name"] == f"{subdomain}.rileyberycz.co.uk":
            url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records/{r['id']}"
            resp = requests.delete(url, headers=get_cloudflare_headers())
            resp.raise_for_status()
            print(f"Deleted CNAME {subdomain}.rileyberycz.co.uk from Cloudflare")
            return True
    return False

def get_next_available_minecraft_number():
    records = list_minecraft_cnames()
    used_numbers = set()
    for r in records:
        match = re.match(r"minecraft-(\d+)\.rileyberycz\.co\.uk", r["name"])
        if match:
            used_numbers.add(int(match.group(1)))
    for i in range(1, 101):
        if i not in used_numbers:
            return i
    raise Exception("All 100 minecraft-XXX subdomains are in use!")

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

def rename_cname_to_number(subdomain):
    records = list_minecraft_cnames()
    cname_record = next((r for r in records if r["name"] == f"{subdomain}.rileyberycz.co.uk"), None)
    if not cname_record:
        return False
    next_num = get_next_free_minecraft_number()
    if not next_num:
        return False
    url = f"{CLOUDFLARE_API_BASE}/zones/{CLOUDFLARE_ZONE_ID}/dns_records/{cname_record['id']}"
    data = {
        "type": "CNAME",
        "name": f"minecraft-{next_num}.rileyberycz.co.uk",
        "content": cname_record["content"],
        "ttl": 120,
        "proxied": False
    }
    resp = requests.put(url, headers=get_cloudflare_headers(), json=data)
    resp.raise_for_status()
    print(f"Renamed CNAME {subdomain} to minecraft-{next_num}")
    return True

def is_reserved_subdomain(name):
    return re.fullmatch(r"minecraft-0*\d{1,3}", name) and 1 <= int(name.split('-')[1]) <= 100

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

app = Flask(__name__, 
            template_folder='admin_panel/templates', 
            static_folder='admin_panel/static')
app.secret_key = os.environ.get('SECRET_KEY', 'minecraft-default-secret')

servers = {}

def load_subdomain_pool():
    if os.path.exists(SUBDOMAIN_POOL_FILE):
        with open(SUBDOMAIN_POOL_FILE, "r") as f:
            return json.load(f)
    return {}

def save_subdomain_pool(pool):
    with open(SUBDOMAIN_POOL_FILE, "w") as f:
        json.dump(pool, f, indent=2)

def sanitize_subdomain(name):
    base = re.sub(r'[^a-z0-9\-]', '', re.sub(r'[\s_]+', '-', name.lower()))
    return f"minecraft-{base}"[:63]

def get_next_available_subdomain(custom_name):
    pool = load_subdomain_pool()
    subdomain = sanitize_subdomain(custom_name)
    candidate = subdomain
    i = 2
    while candidate in pool and pool[candidate] == "used":
        candidate = f"{subdomain}-{i}"
        i += 1
    return candidate

def mark_subdomain_used(subdomain):
    pool = load_subdomain_pool()
    pool[subdomain] = "used"
    save_subdomain_pool(pool)

def mark_subdomain_available(subdomain):
    pool = load_subdomain_pool()
    pool[subdomain] = "available"
    save_subdomain_pool(pool)

def load_server_configs():
    global servers
    pull_latest()
    servers = {}
    if os.path.exists(SERVER_CONFIGS_DIR):
        for filename in os.listdir(SERVER_CONFIGS_DIR):
            if filename.endswith('.json'):
                server_id = filename[:-5]
                with open(os.path.join(SERVER_CONFIGS_DIR, filename), 'r') as f:
                    config = json.load(f)
                    servers[server_id] = config
    return servers

def save_server_config(server_id, config):
    try:
        os.makedirs(SERVER_CONFIGS_DIR, exist_ok=True)
        if 'name' not in config:
            config['name'] = f"Server {server_id[:6]}"
        if 'created_at' not in config:
            config['created_at'] = time.time()
        config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            logger.info(f"Saved configuration for server {server_id}")
    except Exception as e:
        logger.error(f"Error saving server config {server_id}: {e}")
        logger.error(traceback.format_exc())

def get_active_github_workflows():
    if not GITHUB_TOKEN:
        return []
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    try:
        response = requests.get(f"{GITHUB_API}/actions/runs?status=in_progress", headers=headers)
        if response.status_code == 200:
            data = response.json()
            workflows = []
            for run in data.get('workflow_runs', []):
                if run.get('name', '').startswith(('MC Server -', 'Vanilla Minecraft Server', 'Paper Minecraft Server', 'Fabric Minecraft Server', 'Forge Minecraft Server', 'Bedrock Minecraft Server')):
                    server_id = None
                    if 'inputs' in run:
                        server_id = run.get('inputs', {}).get('server_id')
                    if not server_id and ' - ' in run.get('name', ''):
                        server_name = run.get('name').split(' - ', 1)[1]
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
    logger.info("Setting up tunnels for admin panel...")
    tunnels = {'cloudflare': None, 'ngrok': None}
    try:
        logger.info(f"Starting cloudflared tunnel for port {port}...")
        cf_process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
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
    try:     
        ngrok_token = os.environ.get('NGROK_AUTH_TOKEN')
        if ngrok_token:
            conf.get_default().auth_token = ngrok_token
        logger.info(f"Starting ngrok tunnel on port {port}...")
        tunnel = ngrok.connect(port, "http")
        tunnels['ngrok'] = tunnel.public_url
        logger.info(f"ngrok tunnel established: {tunnels['ngrok']}")
    except Exception as e:
        logger.error(f"Error setting up ngrok tunnel: {e}")
    time.sleep(5)
    return tunnels

def create_cloudflare_tunnel(tunnel_name, subdomain):
    result = subprocess.run(
        ["cloudflared", "tunnel", "create", tunnel_name],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if "already exists" in result.stderr:
            print(f"Tunnel {tunnel_name} already exists, continuing.")
        else:
            raise Exception(f"Failed to create tunnel: {result.stderr}")
    try:
        subprocess.run(
            ["cloudflared", "tunnel", "route", "dns", "delete", f"{subdomain}.rileyberycz.co.uk"],
            check=True
        )
        print(f"Removed existing DNS record for {subdomain}.rileyberycz.co.uk")
    except subprocess.CalledProcessError:
        pass
    try:
        subprocess.run(
            ["cloudflared", "tunnel", "route", "dns", tunnel_name, f"{subdomain}.rileyberycz.co.uk"],
            check=True,
            capture_output=True,
            text=True
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if hasattr(e.stderr, "decode") else str(e.stderr)
        if "An A, AAAA, or CNAME record with that host already exists" in stderr:
            raise Exception(
                f"Failed to add tunnel route: DNS record for {subdomain}.rileyberycz.co.uk already exists as an A, AAAA, or CNAME record. "
                "Please remove the conflicting DNS record from your Cloudflare dashboard."
            )
        else:
            raise Exception(f"Failed to add tunnel route: {stderr}")
    return tunnel_name, f"{subdomain}.rileyberycz.co.uk"

def update_readme_with_url(url):
    readme_path = "README.md"
    url_line = f"✨ ADMIN PANEL URL: {url} ✨"
    pattern = r"✨ ADMIN PANEL URL: .+ ✨"
    if os.path.exists(readme_path):
        with open(readme_path, "r") as f:
            content = f.read()
    else:
        content = ""
    if re.search(pattern, content):
        content = re.sub(pattern, url_line, content)
    else:
        content += f"\n{url_line}\n"
    with open(readme_path, "w") as f:
        f.write(content)
    commit_and_push(readme_path, "Update Admin Panel URL in README")

def fix_stale_server_status():
    load_server_configs()
    active_workflows = get_active_github_workflows()
    active_server_ids = {w['server_id'] for w in active_workflows if w['server_id']}
    changed = False
    for server_id, config in servers.items():
        if config.get('is_active', False) and server_id not in active_server_ids:
            config['is_active'] = False
            save_server_config(server_id, config)
            changed = True
    if changed:
        commit_and_push([os.path.join(SERVER_CONFIGS_DIR, f"{sid}.json") for sid in servers], "Auto-fix stale server status")

@app.route('/')
def index():
    load_server_configs()
    current_year = datetime.datetime.now().year
    active_workflows = get_active_github_workflows()
    active_server_ids = {w.get('server_id') for w in active_workflows}
    for server_id, server in servers.items():
        server['is_active'] = server_id in active_server_ids or server.get('is_active', False)
    return render_template(
        'dashboard.html',
        servers=servers,
        active_workflows=active_workflows,
        current_year=current_year,
        REPO_OWNER=REPO_OWNER,
        REPO_NAME=REPO_NAME
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
        if is_reserved_subdomain(sanitize_subdomain(server_name)):
            flash('Subdomain names minecraft-001 to minecraft-100 are reserved. Please choose another name.', 'error')
            return redirect(url_for('create_server'))
        if get_next_free_minecraft_number() is None:
            flash('Maximum number of Minecraft subdomains reached. Please delete an old server first.', 'error')
            return redirect(url_for('create_server'))
        subdomain = get_next_available_subdomain(server_name)
        mark_subdomain_used(subdomain)
        server_id = str(uuid.uuid4())[:8]
        tunnel_name, tunnel_cname = create_cloudflare_tunnel(subdomain, subdomain)
        server_config = {
            'name': server_name,
            'type': server_type,
            'max_players': max_players,
            'difficulty': difficulty,
            'gamemode': gamemode,
            'seed': seed,
            'memory': memory if memory else calculate_memory(max_players),
            'is_active': False,
            'created_at': time.time(),
            'last_started': 0,
            'max_runtime': max_runtime,
            'backup_interval': backup_interval,
            'subdomain': subdomain,
            'address': tunnel_cname
        }
        save_server_config(server_id, server_config)
        servers[server_id] = server_config
        server_dir = os.path.join("servers", server_id)
        os.makedirs(server_dir, exist_ok=True)
        readme_path = os.path.join(server_dir, "README.md")
        with open(readme_path, "w") as f:
            f.write(f"# {server_name}\n\nServer ID: {server_id}\nType: {server_type}\nCreated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        commit_and_push([
            os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json"),
            readme_path
        ], f"Add new server config for {server_name} ({server_id})")
        flash(f'Server "{server_name}" created successfully with ID {server_id}!', 'success')
        return redirect(url_for('index'))
    return render_template('create_server.html', server_types=SERVER_TYPES)

@app.route('/server/<server_id>')
def view_server(server_id):
    load_server_configs()
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    server = servers[server_id]
    active_workflows = get_active_github_workflows()
    server['is_active'] = any(w.get('server_id') == server_id for w in active_workflows) or server.get('is_active', False)
    server_dir = os.path.join("servers", server_id)
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
        return redirect(url_for('view_server', server_id=server_id))
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
        rename_cname_to_number(subdomain)
        mark_subdomain_available(subdomain)
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

@app.route('/shutdown', methods=['POST'])
def shutdown_server_route():
    readme_path = "README.md"
    backup_readme_path = "README.md.bak"
    if os.path.exists(backup_readme_path):
        with open(backup_readme_path, "r") as f:
            original_content = f.read()
        with open(readme_path, "w") as f:
            f.write(original_content)
        commit_and_push(readme_path, "Restore README after admin panel shutdown")
        os.remove(backup_readme_path)
    func = request.environ.get('werkzeug.server.shutdown')
    if func:
        func()
    else:
        os._exit(0)
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
    readme_path = "README.md"
    backup_readme_path = "README.md.bak"
    if os.path.exists(readme_path) and not os.path.exists(backup_readme_path):
        with open(readme_path, "r") as f:
            original_content = f.read()
        with open(backup_readme_path, "w") as f:
            f.write(original_content)
    load_server_configs()
    fix_stale_server_status()
    tunnel_urls = setup_tunnels(admin_port)
    if tunnel_urls['cloudflare']:
        print(f"\n✨ ADMIN PANEL via CLOUDFLARE: {tunnel_urls['cloudflare']} ✨")
        print(f"::notice::Admin Panel URL (Cloudflare): {tunnel_urls['cloudflare']}")
        update_readme_with_url(tunnel_urls['cloudflare'])
    else:
        print("\n⚠️ Cloudflare tunnel not established!")
    if tunnel_urls['ngrok']:
        print(f"\n✨ ADMIN PANEL via NGROK: {tunnel_urls['ngrok']} ✨")
        print(f"::notice::Admin Panel URL (ngrok): {tunnel_urls['ngrok']}")
    else:
        print("\n⚠️ ngrok tunnel not established!")
    if not tunnel_urls['cloudflare'] and not tunnel_urls['ngrok']:
        print("\n⚠️ WARNING: Failed to establish any tunnels! Admin panel will only be available locally at http://localhost:%d" % admin_port)
    app.run(host='0.0.0.0', port=admin_port, debug=False)

if __name__ == "__main__":
    main()