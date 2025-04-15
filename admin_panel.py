#!/usr/bin/env python3
import os
import sys
import json
import time
import uuid
import logging
import threading
import requests
import traceback
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename

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

# Server types and their configurations
SERVER_TYPES = {
    'vanilla': {
        'name': 'Vanilla',
        'download_url': 'https://piston-data.mojang.com/v1/objects/2b95cc780c99ed04682fa1355e1144a4c5aaf214/server.jar',
        'supports_plugins': False,
        'supports_mods': False,
        'java_args': '-Xmx{memory} -Xms{memory}'
    },
    'paper': {
        'name': 'Paper',
        'download_url': 'https://api.papermc.io/v2/projects/paper/versions/1.21.2/builds/324/downloads/paper-1.21.2-324.jar',
        'supports_plugins': True,
        'supports_mods': False,
        'java_args': '-Xmx{memory} -Xms{memory} -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200'
    },
    'forge': {
        'name': 'Forge',
        'download_url': 'https://maven.minecraftforge.net/net/minecraftforge/forge/1.21.1-48.0.6/forge-1.21.1-48.0.6-installer.jar',
        'supports_plugins': False,
        'supports_mods': True,
        'java_args': '-Xmx{memory} -Xms{memory} -XX:+UseG1GC'
    },
    'fabric': {
        'name': 'Fabric',
        'download_url': 'https://maven.fabricmc.net/net/fabricmc/fabric-installer/0.14.21/fabric-installer-0.14.21.jar',
        'supports_plugins': False,
        'supports_mods': True,
        'java_args': '-Xmx{memory} -Xms{memory}'
    },
    'bedrock': {
        'name': 'Bedrock',
        'download_url': 'https://minecraft.azureedge.net/bin-linux/bedrock-server-1.21.10.01.zip',
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

def load_server_configs():
    """Load all server configurations"""
    global servers
    servers = {}
    
    if os.path.exists(SERVER_CONFIGS_DIR):
        for filename in os.listdir(SERVER_CONFIGS_DIR):
            if filename.endswith('.json'):
                try:
                    server_id = filename[:-5]  # Remove .json extension
                    with open(os.path.join(SERVER_CONFIGS_DIR, filename), 'r') as f:
                        config = json.load(f)
                        servers[server_id] = config
                except Exception as e:
                    logger.error(f"Error loading server config {filename}: {e}")
    
    return servers

def save_server_config(server_id, config):
    """Save a server configuration to file"""
    os.makedirs(SERVER_CONFIGS_DIR, exist_ok=True)
    
    with open(os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json"), 'w') as f:
        json.dump(config, f, indent=2)

def check_server_status(server_id):
    """Check the status of a specific server"""
    status_path = f"server/{server_id}/status.json"
    
    try:
        if os.path.exists(status_path):
            with open(status_path, 'r') as f:
                status = json.load(f)
                
            # Check if status is recent (within last 5 minutes)
            if time.time() - status.get('timestamp', 0) < 300:
                return status
    except Exception as e:
        logger.error(f"Error checking status for server {server_id}: {e}")
    
    # Default status if not found or outdated
    return {
        'status': 'offline',
        'address': 'Not available',
        'players': [],
        'online_players': 0,
        'version': servers.get(server_id, {}).get('version', 'Unknown'),
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
                if run.get('name', '').startswith('MC Server -'):
                    server_name = run.get('name').replace('MC Server - ', '')
                    workflows.append({
                        'id': run.get('id'),
                        'name': server_name,
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

def send_github_dispatch(event_type, payload=None):
    """Send repository dispatch event to trigger actions"""
    if not GITHUB_TOKEN:
        logger.error("No GitHub token provided, cannot send dispatch")
        return False
        
    if not payload:
        payload = {}
    
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    data = {
        'event_type': event_type,
        'client_payload': payload
    }
    
    try:
        response = requests.post(f"{GITHUB_API}/dispatches", headers=headers, json=data)
        if response.status_code == 204:
            logger.info(f"Successfully triggered {event_type} event")
            return True
        else:
            logger.error(f"Failed to trigger event: {response.status_code}, {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error sending dispatch: {e}")
        return False

def calculate_memory(max_players):
    """Calculate recommended memory based on max players"""
    # Simple formula: base 1GB + 50MB per player
    memory_mb = 1024 + (max_players * 50)
    # Round up to nearest 512MB
    memory_mb = ((memory_mb + 511) // 512) * 512
    # Cap at 6GB for GitHub Actions
    memory_mb = min(memory_mb, 6144)
    return f"{memory_mb}M"

def create_workflow_file(server_id, server_name, server_type, memory, max_runtime=350, backup_interval=6):
    """Create a GitHub workflow file for running a Minecraft server"""
    server_config = servers.get(server_id, {})
    
    workflow_path = os.path.join(".github", "workflows", f"server_{server_id}.yml")
    os.makedirs(os.path.dirname(workflow_path), exist_ok=True)
    
    workflow_content = f"""name: MC Server - {server_name}

on:
  workflow_dispatch:
    inputs:
      memory:
        description: 'Memory allocation (e.g. 1024M, 2G)'
        default: '{memory}'
      max_runtime:
        description: 'Max runtime in minutes (max 360)'
        default: '{max_runtime}'
      backup_interval:
        description: 'Backup interval in hours'
        default: '{backup_interval}'

jobs:
  run-server:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        
      - name: Set up Java
"""
    
    if server_type != 'bedrock':
        workflow_content += """
        uses: actions/setup-java@v3
        with:
          distribution: 'temurin'
          java-version: '17'
"""
    
    workflow_content += f"""
      - name: Restore server files
        run: |
          mkdir -p server/{server_id}
          cd server/{server_id}
"""
    
    # Add server launch section
    if server_type != 'bedrock':
        workflow_content += f"""
      - name: Start Minecraft server
        run: |
          cd server/{server_id}
          {'./start.sh' if server_type == 'forge' else f'java -Xmx{memory} -Xms{memory} -jar server.jar nogui'}
        env:
          NGROK_AUTH_TOKEN: ${{{{ secrets.NGROK_AUTH_TOKEN }}}}
          BACKUP_INTERVAL_HOURS: ${{{{ github.event.inputs.backup_interval || '{server_config.get("backup_interval", 6)}' }}}}
          MAX_RUNTIME_MINUTES: ${{{{ github.event.inputs.max_runtime || '{server_config.get("max_runtime", 350)}' }}}}
"""
    else:
        workflow_content += f"""
      - name: Start Bedrock server
        run: |
          cd server/{server_id}
          LD_LIBRARY_PATH=. ./bedrock_server
        env:
          NGROK_AUTH_TOKEN: ${{{{ secrets.NGROK_AUTH_TOKEN }}}}
"""

    workflow_content += """
      - name: Upload world backup
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: minecraft-backup
          path: "server/*/backup_*.zip"
          retention-days: 2
"""

    with open(workflow_path, 'w') as f:
        f.write(workflow_content)
    
    return workflow_path

def setup_cloudflare_tunnel(port):
    try:
        import subprocess
        import json
        import time
        import re
        
        logger.info(f"Starting cloudflared tunnel for port {port}...")
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        
        # Wait for tunnel to establish and extract URL
        time.sleep(5)
        
        # Collect output for 10 seconds to ensure we capture the URL
        output = ""
        end_time = time.time() + 10
        while time.time() < end_time:
            if process.stderr.peek():
                line = process.stderr.readline().decode('utf-8')
                output += line
                # Look for the typical tunnel URL pattern
                match = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', line)
                if match:
                    tunnel_url = match.group(0)
                    logger.info(f"Found tunnel URL: {tunnel_url}")
                    return tunnel_url
            time.sleep(0.1)
            
        # If not found in realtime, search the collected output
        match = re.search(r'https://[a-z0-9\-]+\.trycloudflare\.com', output)
        if match:
            tunnel_url = match.group(0)
            logger.info(f"Found tunnel URL in collected output: {tunnel_url}")
            return tunnel_url
                
        logger.error("Could not find valid tunnel URL in cloudflared output")
        logger.debug(f"Cloudflared output: {output}")
        return None
    except Exception as e:
        logger.error(f"Error setting up Cloudflare tunnel: {e}")
        return None

@app.route('/')
def index():
    """Main page that lists all servers"""
    load_server_configs()
    active_workflows = get_active_github_workflows()
    
    # Update server status based on active workflows
    for server_id, server in servers.items():
        server['is_active'] = any(w['name'] == server.get('name', '') for w in active_workflows)
        server['status'] = check_server_status(server_id)
    
    return render_template('dashboard.html', 
                          servers=servers, 
                          active_workflows=active_workflows)

@app.route('/create-server', methods=['GET', 'POST'])
def create_server():
    """Create a new server configuration"""
    if request.method == 'POST':
        server_name = request.form.get('server_name', 'Minecraft Server')
        server_type = request.form.get('server_type', 'vanilla')
        max_players = int(request.form.get('max_players', 20))
        difficulty = request.form.get('difficulty', 'normal')
        gamemode = request.form.get('gamemode', 'survival')
        seed = request.form.get('seed', '')
        memory = request.form.get('memory', '') or calculate_memory(max_players)
        max_runtime = int(request.form.get('max_runtime', 350))
        backup_interval = float(request.form.get('backup_interval', 6))
        
        # Generate unique ID for server
        server_id = str(uuid.uuid4())[:8]
        
        # Create server config
        server_config = {
            'name': server_name,
            'type': server_type,
            'max_players': max_players,
            'difficulty': difficulty,
            'gamemode': gamemode,
            'seed': seed,
            'memory': memory,
            'max_runtime': max_runtime,
            'backup_interval': backup_interval,
            'created_at': time.time(),
            'has_custom_files': False
        }
        
        # Save server config
        save_server_config(server_id, server_config)
        
        # Create workflow file
        create_workflow_file(server_id, server_name, server_type, memory, max_runtime, backup_interval)
        
        flash(f'Server "{server_name}" created successfully!', 'success')
        return redirect(url_for('index'))
    
    return render_template('create_server.html', server_types=SERVER_TYPES)

@app.route('/server/<server_id>')
def view_server(server_id):
    """View a specific server's details"""
    load_server_configs()
    
    if server_id not in servers:
        flash('Server not found', 'error')
        return redirect(url_for('index'))
    
    server = servers[server_id]
    server['status'] = check_server_status(server_id)
    active_workflows = get_active_github_workflows()
    server['is_active'] = any(w['name'] == server.get('name', '') for w in active_workflows)
    
    return render_template('manage_server.html', 
                          server=server,
                          server_id=server_id)

@app.route('/server/<server_id>/start', methods=['POST'])
def start_server(server_id):
    """Start a Minecraft server"""
    load_server_configs()
    
    if server_id not in servers:
        flash('Server not found', 'error')
        return redirect(url_for('index'))
    
    # Check if server is already running
    active_workflows = get_active_github_workflows()
    if any(w['name'] == servers[server_id].get('name', '') for w in active_workflows):
        flash('Server is already running', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    
    # Use workflow_dispatch directly instead of repository_dispatch
    if GITHUB_TOKEN:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        # Extract server settings
        server = servers[server_id]
        
        # Prepare inputs for workflow_dispatch
        workflow_inputs = {
            "memory": server.get('memory', '2G'),
            "max_runtime": str(server.get('max_runtime', 350)),
            "backup_interval": str(server.get('backup_interval', 6))
        }
        
        workflow_file = f"server_{server_id}.yml"
        
        try:
            # Trigger workflow_dispatch directly
            response = requests.post(
                f"{GITHUB_API}/actions/workflows/{workflow_file}/dispatches",
                headers=headers,
                json={
                    "ref": "main", # or your default branch
                    "inputs": workflow_inputs
                }
            )
            
            if response.status_code == 204:
                flash('Server starting...', 'success')
                logger.info(f"Successfully started workflow for server {server_id}")
                return redirect(url_for('view_server', server_id=server_id))
            else:
                logger.error(f"Failed to start server: {response.status_code}, {response.text}")
                flash(f'Failed to start server. Status code: {response.status_code}', 'error')
        except Exception as e:
            logger.error(f"Error starting server: {e}")
            flash(f'Error starting server: {e}', 'error')
    else:
        flash('GitHub token not available, cannot start server', 'error')
    
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/stop', methods=['POST'])
def stop_server(server_id):
    """Stop a running Minecraft server"""
    load_server_configs()
    
    if server_id not in servers:
        flash('Server not found', 'error')
        return redirect(url_for('index'))
    
    # Check if server is running
    active_workflows = get_active_github_workflows()
    running_workflow = next((w for w in active_workflows if w['name'] == servers[server_id].get('name', '')), None)
    
    if not running_workflow:
        flash('Server is not running', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    
    # Trigger workflow cancellation
    if GITHUB_TOKEN:
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        try:
            response = requests.post(
                f"{GITHUB_API}/actions/runs/{running_workflow['id']}/cancel",
                headers=headers
            )
            if response.status_code == 202:
                flash('Server stop request sent', 'success')
            else:
                flash(f'Failed to stop server: {response.status_code}', 'error')
        except Exception as e:
            logger.error(f"Error stopping server: {e}")
            flash(f'Error stopping server: {e}', 'error')
    else:
        flash('GitHub token not available, cannot stop server', 'error')
    
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/send-command', methods=['POST'])
def send_command(server_id=None):
    """Send a command to a running Minecraft server"""
    if not server_id:
        server_id = request.form.get('server_id')
    
    command = request.form.get('command')
    
    if not server_id or not command:
        flash('Missing server ID or command', 'error')
        return redirect(url_for('index'))
    
    # Send command via repository dispatch
    success = send_github_dispatch('minecraft-server-command', {
        'server_id': server_id,
        'command': command
    })
    
    if success:
        flash(f'Command sent: {command}', 'success')
    else:
        flash('Failed to send command', 'error')
    
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/delete', methods=['POST'])
def delete_server(server_id):
    """Delete a server configuration"""
    load_server_configs()
    
    if server_id not in servers:
        flash('Server not found', 'error')
        return redirect(url_for('index'))
    
    # Check if server is running
    active_workflows = get_active_github_workflows()
    if any(w['name'] == servers[server_id].get('name', '') for w in active_workflows):
        flash('Cannot delete a running server. Stop it first.', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    
    # Delete server config
    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    if os.path.exists(config_path):
        os.remove(config_path)
    
    # Delete workflow file
    workflow_path = os.path.join(".github", "workflows", f"server_{server_id}.yml")
    if os.path.exists(workflow_path):
        os.remove(workflow_path)
    
    flash('Server deleted successfully', 'success')
    return redirect(url_for('index'))

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return 'Server shutting down...'

@app.route('/shutdown', methods=['POST'])
def shutdown_server_route():
    """Shutdown the admin panel server and the GitHub Action"""
    # First stop all running servers to ensure worlds are saved properly
    load_server_configs()
    active_workflows = get_active_github_workflows()
    
    for workflow in active_workflows:
        if GITHUB_TOKEN:
            headers = {
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            try:
                logger.info(f"Attempting to stop workflow: {workflow['id']}")
                response = requests.post(
                    f"{GITHUB_API}/actions/runs/{workflow['id']}/cancel",
                    headers=headers
                )
                if response.status_code == 202:
                    logger.info(f"Successfully stopped server: {workflow['name']}")
                else:
                    logger.warning(f"Failed to stop server: {workflow['name']} (Status: {response.status_code})")
            except Exception as e:
                logger.error(f"Error stopping server during shutdown: {e}")
    
    # Allow time for servers to save and shut down
    time.sleep(5)
    
    flash('Admin panel is shutting down...', 'success')
    
    # Create a marker file that signals workflow should end
    with open("SHUTDOWN_REQUESTED", "w") as f:
        f.write("shutdown")
    
    # Shutdown the Flask server
    threading.Thread(target=lambda: time.sleep(1) and shutdown_server()).start()
    return render_template('shutdown.html')

def main():
    """Main function to run the admin panel"""
    # Get settings from environment
    admin_port = int(os.environ.get('ADMIN_PORT', '8080'))
    
    # Debug output
    print("GITHUB_TOKEN present:", bool(GITHUB_TOKEN))
    print("REPO_OWNER:", REPO_OWNER)
    print("REPO_NAME:", REPO_NAME)
    
    # Create required directories
    os.makedirs(SERVER_CONFIGS_DIR, exist_ok=True)
    
    # Check if uploads exists as a file and handle it
    if os.path.exists(UPLOADS_DIR) and not os.path.isdir(UPLOADS_DIR):
        os.remove(UPLOADS_DIR)  # Remove if it's a file
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    
    os.makedirs("admin_panel/templates", exist_ok=True)
    os.makedirs("admin_panel/static/css", exist_ok=True)
    
    # Load server configurations
    load_server_configs()
    
    # Set up Cloudflare tunnel for public access
    public_url = setup_cloudflare_tunnel(admin_port)
    if public_url:
        logger.info(f"✨ ADMIN PANEL URL: {public_url} ✨")
        print(f"::notice title=Admin Panel URL::{public_url}")
    else:
        logger.warning("Failed to set up Cloudflare tunnel, panel will only be accessible locally")
        logger.info(f"Admin panel available locally at: http://localhost:{admin_port}")
    
    # Run Flask app
    app.run(host='0.0.0.0', port=admin_port, debug=False)

if __name__ == "__main__":
    main()