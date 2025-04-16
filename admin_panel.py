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
                        # Validate required fields are present
                        if 'name' not in config:
                            config['name'] = f"Server {server_id[:6]}"
                        if 'type' not in config:
                            config['type'] = 'vanilla'
                        servers[server_id] = config
                        logger.info(f"Loaded server config for {config.get('name', 'Unnamed')} ({server_id})")
                except Exception as e:
                    logger.error(f"Error loading server config {filename}: {e}")
    
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
    """Check status of server from status.json and workflow status"""
    # Check in servers/ directory instead of server/
    status_path = f"servers/{server_id}/status.json"
    try:
        if os.path.exists(status_path):
            with open(status_path, 'r') as f:
                status = json.load(f)
            # If status is recent (within last 5 minutes)
            if time.time() - status.get('timestamp', 0) < 300:
                return {
                    'status': 'online' if status.get('running') else 'offline',
                    'address': status.get('address', 'Not available'),
                    'players': [],
                    'online_players': 0,
                    'version': servers.get(server_id, {}).get('type', 'Unknown'),
                    'timestamp': status.get('timestamp', 0)
                }
    except Exception as e:
        logger.error(f"Error checking status for server {server_id}: {e}")
    
    # Check active GitHub workflows as fallback
    active_workflows = get_active_github_workflows()
    if any(w.get('server_id') == server_id for w in active_workflows):
        return {
            'status': 'starting',
            'address': 'Starting up...',
            'players': [],
            'online_players': 0,
            'version': servers.get(server_id, {}).get('type', 'Unknown'),
            'timestamp': int(time.time())
        }
    
    # Default status if not found or outdated
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
        # Install pyngrok if needed
        try:
            from pyngrok import ngrok, conf
        except ImportError:
            logger.info("Installing pyngrok package...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyngrok"])
            from pyngrok import ngrok, conf
        
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

@app.route('/')
def index():
    """Main page that lists all servers"""
    load_server_configs()
    current_year = datetime.datetime.now().year
    
    # Update server status based on active workflows
    active_workflows = get_active_github_workflows()
    for server_id, server in servers.items():
        # Check if server is active in workflows
        is_active_in_workflow = any(w.get('server_id') == server_id for w in active_workflows)
        if is_active_in_workflow:
            server['is_active'] = True
            server['last_started'] = time.time()
        
        # Check status file for updated info
        status = check_server_status(server_id)
        server['status'] = status['status']
        server['address'] = status['address']
    
    return render_template('dashboard.html', 
                           servers=servers, 
                           active_workflows=active_workflows,
                           current_year=current_year,
                           REPO_OWNER=REPO_OWNER,
                           REPO_NAME=REPO_NAME)

@app.route('/create-server', methods=['GET', 'POST'])
def create_server():
    """Create a new server configuration with a random ID"""
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
        
        # Generate a random ID for this server
        server_id = str(uuid.uuid4())[:8]  # Use first 8 chars of UUID for shorter ID
        
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
            'backup_interval': backup_interval
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
    """Start a Minecraft server using GitHub Actions"""
    load_server_configs()
    
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    
    server_config = servers[server_id]
    server_type = server_config.get('type', 'vanilla')
    server_name = server_config.get('name', 'Unnamed Server')
    
    try:
        # Get appropriate workflow file for the server type
        workflow_file = f"{server_type}_server.yml"
        
        headers = {
            'Authorization': f"Bearer {GITHUB_TOKEN}",
            'Accept': 'application/vnd.github+json'
        }
        
        # Build inputs for the workflow
        inputs = {
            'server_id': server_id
        }
        
        data = {
            'ref': 'admin_panel',
            'inputs': inputs
        }
        
        # Build the API URL for the workflow file directly in .github/workflows
        api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{workflow_file}/dispatches"
        
        logger.info(f"Dispatching workflow: {workflow_file} with inputs: {inputs}")
        response = requests.post(api_url, headers=headers, json=data)
        
        if response.status_code == 204:
            # Success - update server status
            server_config['is_active'] = True
            server_config['last_started'] = time.time()
            save_server_config(server_id, server_config)
            flash('Server starting in GitHub Actions. It will be ready in about 2 minutes.', 'success')
        else:
            error_text = response.text
            logger.error(f"GitHub API error: {response.status_code} - {error_text}")
            flash(f'Failed to start server: {response.status_code}. {error_text}', 'error')
            
    except Exception as e:
        logger.error(f"Error starting server {server_id}: {e}")
        logger.error(traceback.format_exc())
        flash(f'Error starting server: {str(e)}', 'error')
    
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/stop', methods=['POST'])
def stop_server(server_id):
    """Stop a Minecraft server"""
    load_server_configs()
    
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    
    # Update the status in our config
    servers[server_id]['is_active'] = False
    save_server_config(server_id, servers[server_id])
    
    # Create a status file that indicates the server is stopped
    status_path = f"servers/{server_id}/status.json"
    try:
        status = {
            'address': 'Not available',
            'running': False,
            'timestamp': int(time.time())
        }
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        with open(status_path, 'w') as f:
            json.dump(status, f)
    except Exception as e:
        logger.error(f"Error updating status file: {e}")
    
    flash('Server has been stopped.', 'success')
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/delete', methods=['POST'])
def delete_server(server_id):
    """Delete a server configuration"""
    load_server_configs()
    
    if server_id not in servers:
        flash(f'Server with ID {server_id} not found!', 'error')
        return redirect(url_for('index'))
    
    # Check if server is currently running
    if servers[server_id].get('is_active', False):
        flash('Cannot delete server while it is running. Stop the server first.', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    
    # Delete the config file
    config_path = os.path.join(SERVER_CONFIGS_DIR, f"{server_id}.json")
    if os.path.exists(config_path):
        os.remove(config_path)
    
    # Remove the server from memory
    server_name = servers[server_id].get('name', 'Unnamed Server')
    del servers[server_id]
    
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
    """Upload a custom server JAR file"""
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
        
        # Save the JAR file
        filename = secure_filename(file.filename)
        file.save(os.path.join(server_dir, filename))
        
        # Create a symlink to server.jar for compatibility
        if filename != 'server.jar':
            server_jar_path = os.path.join(server_dir, "server.jar")
            if os.path.exists(server_jar_path):
                os.remove(server_jar_path)
            
            # On Windows, symlinks require admin privileges, so copy instead
            import shutil
            shutil.copy2(os.path.join(server_dir, filename), server_jar_path)
        
        flash(f'Server JAR file "{filename}" uploaded successfully', 'success')
    else:
        flash('Invalid file type. Please upload a JAR file.', 'error')
    
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/server/<server_id>/download-jar', methods=['POST'])
def download_server_jar(server_id):
    """Download a server JAR from a URL"""
    jar_url = request.form.get('jar_url', '')
    
    if not jar_url:
        flash('Please provide a download URL', 'error')
        return redirect(url_for('view_server', server_id=server_id))
    
    try:
        server_dir = os.path.join("servers", server_id)
        os.makedirs(server_dir, exist_ok=True)
        
        # Download the JAR file
        response = requests.get(jar_url, stream=True)
        if response.status_code == 200:
            # Get filename from URL or use default
            if 'Content-Disposition' in response.headers:
                content_disposition = response.headers['Content-Disposition']
                filename = re.findall('filename="(.+)"', content_disposition)[0]
            else:
                filename = jar_url.split('/')[-1]
            
            if not filename.endswith('.jar'):
                filename += '.jar'
            
            filename = secure_filename(filename)
            file_path = os.path.join(server_dir, filename)
            
            # Save the file
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # Create a symlink to server.jar for compatibility
            if filename != 'server.jar':
                server_jar_path = os.path.join(server_dir, "server.jar")
                if os.path.exists(server_jar_path):
                    os.remove(server_jar_path)
                
                # On Windows, symlinks require admin privileges, so copy instead
                import shutil
                shutil.copy2(file_path, server_jar_path)
            
            flash(f'Server JAR file "{filename}" downloaded successfully', 'success')
        else:
            flash(f'Failed to download JAR file: {response.status_code}', 'error')
    except Exception as e:
        logger.error(f"Error downloading JAR file: {e}")
        flash(f'Error downloading JAR file: {str(e)}', 'error')
    
    return redirect(url_for('view_server', server_id=server_id))

@app.route('/shutdown', methods=['POST'])
def shutdown_server_route():
    """Shutdown the admin panel"""
    # Create a flag file to signal the workflow to stop
    with open("SHUTDOWN_REQUESTED", "w") as f:
        f.write("Shutdown requested at " + str(datetime.datetime.now()))
    
    # Return a message
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
    os.makedirs("servers", exist_ok=True)  # Main server directory
    os.makedirs(".github/workflows", exist_ok=True)  # Ensure workflows directory exists
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs("admin_panel/templates", exist_ok=True)
    os.makedirs("admin_panel/static/css", exist_ok=True)
    
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