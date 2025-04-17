#!/usr/bin/env python3
# filepath: c:\Projects\MinecraftServer\MC_Server\admin_panel.py
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
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from werkzeug.utils import secure_filename
from pyngrok import ngrok, conf 
from github_helper import pull_latest, commit_and_push
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
SERVER_CONFIGS_DIR = 'server_configs'
UPLOADS_DIR = 'uploads'
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_OWNER = os.environ.get('GITHUB_REPOSITORY', '').split('/')[0] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else ''
REPO_NAME = os.environ.get('GITHUB_REPOSITORY', '').split('/')[1] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else ''
GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

SERVERS_STATUS_FILE = 'servers_status.json'

# Server types and their configurations
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
        'java_args': ''  # Not using Java
    }
}

# Initialize Flask app
app = Flask(__name__, 
            template_folder='admin_panel/templates', 
            static_folder='admin_panel/static')
app.secret_key = os.environ.get('SECRET_KEY', 'minecraft-default-secret')

# Global variables
servers = {}  # Store server configurations

def load_servers_status():
    pull_latest()
    if os.path.exists(SERVERS_STATUS_FILE):
        with open(SERVERS_STATUS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_servers_status(status):
    with open(SERVERS_STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)

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
    """Save a server configuration to file"""
    try:
        os.makedirs(SERVER_CONFIGS_DIR, exist_ok=True)
        
        # Ensure the configuration is complete
        if 'name' not in config:
            config['name'] = f"Server {server_id[:6]}"
        if 'created_at' not in config:
            config['created_at'] = time.time()
        
        # Save the configuration
        config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
            logger.info(f"Saved configuration for server {server_id}")
    except Exception as e:
        logger.error(f"Error saving server config {server_id}: {e}")
        logger.error(traceback.format_exc())

def check_server_status(server_id):
    """Check status of server from servers_status.json"""
    status_path = SERVERS_STATUS_FILE
    try:
        if os.path.exists(status_path):
            with open(status_path, 'r') as f:
                all_status = json.load(f)
            status = all_status.get(server_id, {})
            if status:
                return {
                    'status': status.get('status', 'offline'),
                    'address': status.get('address', 'Not available'),
                    'players': [],
                    'online_players': 0,
                    'version': servers.get(server_id, {}).get('type', 'Unknown'),
                    'timestamp': status.get('timestamp', 0)
                }
    except Exception as e:
        logger.error(f"Error checking status for server {server_id}: {e}")
    # Default status if not found
    return {
        'status': 'offline',
        'address': 'Not available',
        'players': [],
        'online_players': 0,
        'version': servers.get(server_id, {}).get('type', 'Unknown'),
        'timestamp': 0
    }

def get_active_github_workflows():
    """Get list of currently active workflows from GitHub API"""
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
                if run.get('name', '').startswith('MC Server -') or run.get('name', '').startswith('Vanilla Minecraft Server') or run.get('name', '').startswith('Paper Minecraft Server') or run.get('name', '').startswith('Fabric Minecraft Server') or run.get('name', '').startswith('Forge Minecraft Server') or run.get('name', '').startswith('Bedrock Minecraft Server'):
                    # Extract server_id from workflow inputs
                    server_id = None
                    if 'inputs' in run:
                        server_id = run.get('inputs', {}).get('server_id')
                    
                    # If we can't extract it, try from the name
                    if not server_id and ' - ' in run.get('name', ''):
                        server_name = run.get('name').split(' - ', 1)[1]
                        # Find server with this name
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
    """Calculate recommended memory based on max players"""
    # Simple formula: base 1GB + 50MB per player
    memory_mb = 1024 + (max_players * 50)
    # Round up to nearest 512MB
    memory_mb = ((memory_mb + 511) // 512) * 512
    # Cap at 6GB for GitHub Actions
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
            conf.get_default().auth_token = ngrok_token
        
        # Start tunnel
        logger.info(f"Starting ngrok tunnel on port {port}...")
        tunnel = ngrok.connect(port, "http")
        tunnels['ngrok'] = tunnel.public_url
        logger.info(f"ngrok tunnel established: {tunnels['ngrok']}")
    except Exception as e:
        logger.error(f"Error setting up ngrok tunnel: {e}")
    
    # Wait a moment to allow both tunnels to establish
    time.sleep(5)
    
    return tunnels

def create_cloudflare_tunnel(tunnel_name, subdomain):
    # Check tunnel count before creating
    if get_cloudflare_tunnel_count() >= 100:
        raise Exception("Tunnel limit reached (100). Cannot create more tunnels.")
    # Create the tunnel (if it doesn't exist)
    result = subprocess.run(
        ["cloudflared", "tunnel", "create", tunnel_name],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        if "already exists" in result.stderr:
            print(f"Tunnel {tunnel_name} already exists, continuing.")
        else:
            raise Exception(f"Failed to create tunnel: {result.stderr}")
    # Route the tunnel to your subdomain
    subprocess.run(
        ["cloudflared", "tunnel", "route", "dns", tunnel_name, f"{subdomain}.rileyberycz.co.uk"],
        check=True
    )
    return tunnel_name, f"{subdomain}.rileyberycz.co.uk"

def delete_cloudflare_tunnel(tunnel_name):
    """Delete a named Cloudflare tunnel."""
    try:
        subprocess.run(["cloudflared", "tunnel", "delete", tunnel_name], check=True)
        print(f"Deleted Cloudflare tunnel: {tunnel_name}")
    except Exception as e:
        print(f"Error deleting Cloudflare tunnel {tunnel_name}: {e}")

def get_cloudflare_tunnel_count():
    result = subprocess.run(["cloudflared", "tunnel", "list"], capture_output=True, text=True)
    # Parse the output to count tunnels (skip header line)
    lines = result.stdout.strip().split('\n')
    return max(0, len(lines) - 1)

@app.route('/')
def index():
    """Main page that lists all servers"""
    load_server_configs()
    current_year = datetime.datetime.now().year

    # Update server status based on active workflows
    active_workflows = get_active_github_workflows()
    for server_id, server in servers.items():
        # Check if the server has an active workflow
        is_active = any(w.get('server_id') == server_id for w in active_workflows)
        if is_active:
            server['is_active'] = True
            server['status'] = 'starting'
        else:
            # Get the current status
            status_info = check_server_status(server_id)
            server['status'] = status_info['status'] 
            server['is_active'] = server['status'] == 'online'

    # Pass servers_status to the template!
    servers_status = load_servers_status()

    return render_template(
        'dashboard.html',
        servers=servers,
        active_workflows=active_workflows,
        current_year=current_year,
        REPO_OWNER=REPO_OWNER,
        REPO_NAME=REPO_NAME,
        servers_status=servers_status 
    )

@app.route('/create-server', methods=['GET', 'POST'])
def create_server():
    if request.method == 'POST':
        if get_cloudflare_tunnel_count() >= 100:
            flash('Tunnel limit reached (100). Delete a server before creating a new one.', 'error')
            return redirect(url_for('index'))
        server_name = request.form['server_name']
        server_type = request.form['server_type']
        max_players = int(request.form.get('max_players', 20))
        difficulty = request.form.get('difficulty', 'normal')
        gamemode = request.form.get('gamemode', 'survival')
        seed = request.form.get('seed', '')
        memory = request.form.get('memory', '')
        max_runtime = int(request.form.get('max_runtime', 350))
        backup_interval = float(request.form.get('backup_interval', 6.0))
        custom_subdomain = request.form.get('custom_subdomain', '').strip()
        subdomain = custom_subdomain if custom_subdomain else server_name.replace(' ', '-')
        # Generate a random ID for this server
        server_id = str(uuid.uuid4())[:8]

        # Create the tunnel and get the full domain
        tunnel_name, tunnel_url = create_cloudflare_tunnel(subdomain, subdomain)

        # Create server configuration
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
            'tunnel_url': tunnel_url  # Store the tunnel URL in the config
        }

        # Save the configuration with the random ID
        save_server_config(server_id, server_config)
        servers[server_id] = server_config

        # Create server directory if it doesn't exist
        server_dir = os.path.join("servers", server_id)
        os.makedirs(server_dir, exist_ok=True)

        # Optionally, create a README in the server directory
        readme_path = os.path.join(server_dir, "README.md")
        with open(readme_path, "w") as f:
            f.write(f"# {server_name}\n\nServer ID: {server_id}\nType: {server_type}\nCreated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Commit and push config and readme
        commit_and_push([
            os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json"),
            readme_path
        ], f"Add new server config for {server_name} ({server_id})")

        flash(f'Server "{server_name}" created successfully with ID {server_id}!', 'success')
        return redirect(url_for('index'))
    return render_template('create_server.html', server_types=SERVER_TYPES)

@app.route('/server/<server_id>')
def view_server(server_id):
    """View a specific server's details"""
    load_server_configs()
    
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    
    server = servers[server_id]
    
    # Check status in status.json file
    status_info = check_server_status(server_id)
    server['status'] = status_info['status']
    server['address'] = status_info['address']
    server['is_active'] = server['status'] in ['online', 'starting']
    
    # Check if the server has a custom JAR file
    server_dir = os.path.join("servers", server_id)
    if os.path.exists(server_dir):
        jar_files = [f for f in os.listdir(server_dir) if f.endswith('.jar') and f != 'server.jar']
        server['has_custom_jar'] = len(jar_files) > 0
        server['custom_jar_name'] = jar_files[0] if server['has_custom_jar'] else None
    else:
        server['has_custom_jar'] = False
    
    return render_template('manage_server.html', 
                          server=server,
                          server_id=server_id,
                          REPO_OWNER=REPO_OWNER,
                          REPO_NAME=REPO_NAME)

@app.route('/server/<server_id>/start', methods=['POST'])
def start_server(server_id):
    load_server_configs()
    status = load_servers_status()
    if status.get(server_id, {}).get('status') == 'running':
        flash('Server is already running!', 'warning')
        return redirect(url_for('view_server', server_id=server_id))

    # Get the server type
    server_type = servers[server_id]['type']
    workflow_file = f"{server_type}_server.yml"  # e.g., vanilla_server.yml

    # Trigger the correct workflow
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    data = {
        'ref': 'main',  # or your default branch
        'inputs': {'server_id': server_id}
    }
    api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_file}/dispatches"
    response = requests.post(api_url, headers=headers, json=data)
    if response.status_code == 204:
        status[server_id] = {'status': 'running', 'last_started': int(time.time())}
        save_servers_status(status)
        commit_and_push(SERVERS_STATUS_FILE, "Update server status")
        flash('Server is starting...', 'success')
    else:
        flash(f"Failed to start server workflow: {response.text}", 'error')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/stop', methods=['POST'])
def stop_server(server_id):
    load_server_configs()
    status = load_servers_status()
    status[server_id] = {'status': 'stopped', 'last_stopped': int(time.time())}
    save_servers_status(status)
    commit_and_push(SERVERS_STATUS_FILE, "Update server status")
    flash('Server has been stopped.', 'success')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/delete', methods=['POST'])
def delete_server(server_id):
    load_server_configs()
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    if servers[server_id].get('is_active', False):
        flash('Cannot delete server while it is running. Stop the server first.', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    files_to_commit = []
    tunnel_name = servers[server_id].get('subdomain') or server_id  # Use subdomain as tunnel name
    # Delete the tunnel before removing config
    delete_cloudflare_tunnel(tunnel_name)
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

@app.route('/server/<server_id>/send-command', methods=['POST'])
def send_command(server_id):
    """Send a command to the server"""
    command = request.form.get('command', '')
    
    if not command:
        flash('Command cannot be empty', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    
    # For now, just acknowledge the command since we're using GitHub Actions
    flash(f'Command functionality is not available with GitHub Actions workflows.', 'warning')
    return redirect(url_for('view_server', server_id=server_id))

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
        # Commit and push the uploaded JAR
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
        import requests
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
    """Main function to run the admin panel"""
    # Get settings from environment
    admin_port = int(os.environ.get('ADMIN_PORT', '8080'))
    
    # Debug output
    print("GITHUB_TOKEN present:", bool(GITHUB_TOKEN))
    print("REPO_OWNER:", REPO_OWNER)
    print("REPO_NAME:", REPO_NAME)
    
    # Create required directories with proper error handling
    for directory in [SERVER_CONFIGS_DIR, "servers", ".github/workflows", 
                     ".github/workflows/server_templates", UPLOADS_DIR, 
                     "admin_panel/templates", "admin_panel/static/css"]:
        try:
            # Check if path exists and is not a directory
            if os.path.exists(directory) and not os.path.isdir(directory):
                # Rename the existing file
                os.rename(directory, f"{directory}.bak")
                print(f"Renamed existing file '{directory}' to '{directory}.bak'")
            
            # Now create the directory
            os.makedirs(directory, exist_ok=True)
            print(f"Directory created/verified: {directory}")
        except Exception as e:
            print(f"Warning: Issue with directory '{directory}': {e}")
    
    # Load server configurations
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
