import os
import json
import flask
import zipfile
import requests
import logging
import threading
import time
from flask import Flask, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename
from pyngrok import ngrok, conf

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'minecraft-admin-secret')

# GitHub API settings
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_OWNER = os.environ.get('REPO_OWNER')
REPO_NAME = os.environ.get('REPO_NAME')
GITHUB_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

# Configuration
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'zip', 'jar', 'properties', 'json', 'txt'}
COMMAND_FILE = 'server_commands.json'
STATUS_FILE = 'server_status.json'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB max upload

# Track server status
server_info = {
    'status': 'unknown',
    'address': 'Not available',
    'players': [],
    'version': 'Unknown',
    'last_update': time.time()
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def send_github_dispatch(event_type, payload=None):
    """Send a repository dispatch event to GitHub Actions"""
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
    
    response = requests.post(f"{GITHUB_API}/dispatches", headers=headers, json=data)
    return response.status_code == 204

def check_server_status():
    """Check server status periodically"""
    while True:
        try:
            if os.path.exists(STATUS_FILE):
                with open(STATUS_FILE, 'r') as f:
                    status_data = json.load(f)
                    if time.time() - status_data.get('timestamp', 0) < 60:  # Only use recent status updates
                        server_info.update(status_data)
                        server_info['last_update'] = time.time()
            time.sleep(10)
        except Exception as e:
            logger.error(f"Error checking server status: {e}")
            time.sleep(30)

@app.route('/')
def index():
    """Main admin dashboard"""
    world_backups = []
    
    # Find all backup files
    for file in os.listdir('.'):
        if file.startswith('backup_') and file.endswith('.zip'):
            backup_time = file[7:-4]  # Extract timestamp from filename
            world_backups.append({'filename': file, 'timestamp': backup_time})
    
    # Sort backups by timestamp (newest first)
    world_backups.sort(key=lambda x: x['timestamp'], reverse=True)
    
    return render_template('dashboard.html', 
                          server=server_info,
                          backups=world_backups)

@app.route('/command', methods=['POST'])
def send_command():
    """Send a command to the Minecraft server"""
    command = request.form.get('command')
    if not command:
        flash('No command provided', 'error')
        return redirect(url_for('index'))
    
    # Send a repository dispatch event with the command
    success = send_github_dispatch('minecraft-command', {'command': command})
    
    if success:
        flash(f'Command sent: {command}', 'success')
    else:
        flash('Failed to send command', 'error')
    
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_file():
    """Upload a file to be used by the Minecraft server"""
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    file_type = request.form.get('file_type', 'config')
    
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('index'))
        
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Tell the server about the uploaded file
        success = send_github_dispatch('minecraft-file-upload', {
            'file_path': file_path,
            'file_type': file_type,
            'original_name': file.filename
        })
        
        if success:
            flash(f'File uploaded: {filename}', 'success')
        else:
            flash('File uploaded but server notification failed', 'warning')
    else:
        flash('Invalid file type', 'error')
    
    return redirect(url_for('index'))

@app.route('/backup/restore/<filename>')
def restore_backup(filename):
    """Restore a specific backup"""
    if not filename.startswith('backup_') or not filename.endswith('.zip'):
        flash('Invalid backup file', 'error')
        return redirect(url_for('index'))
    
    # Send a repository dispatch event to restore the backup
    success = send_github_dispatch('minecraft-restore-backup', {'backup_name': filename})
    
    if success:
        flash(f'Restore request sent for: {filename}', 'success')
    else:
        flash('Failed to send restore request', 'error')
    
    return redirect(url_for('index'))

@app.route('/server/restart')
def restart_server():
    """Request a server restart"""
    success = send_github_dispatch('minecraft-restart')
    
    if success:
        flash('Server restart requested', 'success')
    else:
        flash('Failed to send restart request', 'error')
    
    return redirect(url_for('index'))

@app.route('/server/settings', methods=['POST'])
def update_settings():
    """Update server settings"""
    settings = {
        'max_players': request.form.get('max_players'),
        'difficulty': request.form.get('difficulty'),
        'gamemode': request.form.get('gamemode'),
        'pvp': 'true' if request.form.get('pvp') == 'on' else 'false',
        'motd': request.form.get('motd')
    }
    
    # Send settings to the server
    success = send_github_dispatch('minecraft-update-settings', {'settings': settings})
    
    if success:
        flash('Settings update requested', 'success')
    else:
        flash('Failed to send settings update', 'error')
    
    return redirect(url_for('index'))

def main():
    """Main function to run the admin panel"""
    # Get settings from environment
    admin_port = int(os.environ.get('ADMIN_PORT', '8080'))
    ngrok_auth_token = os.environ.get('NGROK_AUTH_TOKEN')
    
    # Start the status checking thread
    status_thread = threading.Thread(target=check_server_status, daemon=True)
    status_thread.start()
    
    # Set up ngrok
    if ngrok_auth_token:
        conf.get_default().auth_token = ngrok_auth_token
    
    public_url = ngrok.connect(admin_port, "http").public_url
    logger.info(f"Admin panel available at: {public_url}")
    
    # Run Flask app
    app.run(host='0.0.0.0', port=admin_port)

if __name__ == '__main__':
    main()