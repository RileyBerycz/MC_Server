#!/usr/bin/env python3
import os
import subprocess
import time
import logging
import threading
import signal
import json
from flask import Flask, request, jsonify
from pyngrok import ngrok, conf

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False

# Global variables for command API
command_queue = []
app = Flask(__name__)

def create_backup():
    """Create a zip backup of the Minecraft server world."""
    try:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.zip"
        logger.info(f"Creating backup: {backup_filename}")
        
        world_dir = "world"  # Default world directory name
        if os.path.exists("server.properties"):
            with open("server.properties", "r") as f:
                for line in f:
                    if line.startswith("level-name="):
                        world_dir = line.split("=")[1].strip()
        
        if not os.path.exists(world_dir):
            logger.warning(f"World directory '{world_dir}' not found. Backing up all files.")
            with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk("."):
                    for file in files:
                        if not file.endswith(".zip"):
                            zipf.write(os.path.join(root, file))
        else:
            with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(world_dir):
                    for file in files:
                        zipf.write(os.path.join(root, file))
            
            config_files = ["server.properties", "ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"]
            for file in config_files:
                if os.path.exists(file):
                    zipf.write(file)
        
        logger.info(f"Backup completed: {backup_filename}")
        return backup_filename
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return None

def send_server_command(server_process, command):
    """Send a command to the Minecraft server."""
    if server_process and server_process.stdin:
        logger.info(f"Sending command to server: {command}")
        server_process.stdin.write(f"{command}\n")
        server_process.stdin.flush()
        return True
    return False

def schedule_backup(server_process, interval_hours=6):
    """Schedule a backup every X hours."""
    global shutdown_requested
    
    if shutdown_requested:
        return
    
    logger.info(f"Scheduling next backup in {interval_hours} hours")
    
    backup_timer = threading.Timer(interval_hours * 3600, lambda: execute_backup(server_process, interval_hours))
    backup_timer.daemon = True
    backup_timer.start()

def execute_backup(server_process, interval_hours=6):
    """Execute the backup process with minimal downtime."""
    global shutdown_requested
    
    if shutdown_requested:
        return
    
    try:
        logger.info("Starting scheduled backup process...")
        
        send_server_command(server_process, "say §6[SERVER] §fBackup starting in 30 seconds. Expect brief lag.")
        time.sleep(20)
        send_server_command(server_process, "say §6[SERVER] §fBackup in 10 seconds...")
        time.sleep(5)
        send_server_command(server_process, "say §6[SERVER] §fBackup in 5 seconds...")
        time.sleep(5)
        
        send_server_command(server_process, "say §6[SERVER] §fBackup starting now. Server may lag for a few seconds.")
        
        send_server_command(server_process, "save-all flush")
        send_server_command(server_process, "save-off")
        logger.info("World saved and auto-save disabled")
        
        time.sleep(3)
        
        backup_file = create_backup()
        
        send_server_command(server_process, "save-on")
        logger.info("Auto-save re-enabled")
        
        send_server_command(server_process, "say §6[SERVER] §fBackup completed successfully!")
        
        logger.info(f"Backup process completed: {backup_file}")
        
        schedule_backup(server_process, interval_hours)
        
    except Exception as e:
        logger.error(f"Error during backup process: {e}")
        send_server_command(server_process, "save-on")
        schedule_backup(server_process, interval_hours)

def signal_handler(sig, frame):
    """Handle termination signals."""
    global shutdown_requested
    shutdown_requested = True
    logger.info("Shutdown signal received, will terminate after current operations complete")

def launch_minecraft_server(jar_path, java_args="-Xmx1024M -Xms1024M"):
    """Launch a Minecraft server using the specified JAR file."""
    try:
        cmd = f"java {java_args} -jar {jar_path} nogui"
        logger.info(f"Launching Minecraft server with command: {cmd}")
        
        process = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True
        )
        
        time.sleep(10)
        return process
    except Exception as e:
        logger.error(f"Failed to launch Minecraft server: {e}")
        raise

def setup_ngrok(port=25565, auth_token=None):
    """Set up and start ngrok to expose the Minecraft server port."""
    try:
        if auth_token:
            conf.get_default().auth_token = auth_token
            logger.info("ngrok authentication token set")
        
        logger.info(f"Starting ngrok tunnel for port {port}...")
        public_url = ngrok.connect(port, "tcp").public_url
        
        _, host_port = public_url.split("://")
        host, ngrok_port = host_port.split(":")
        
        logger.info(f"ngrok tunnel established: {public_url}")
        logger.info(f"Minecraft server accessible at: {host}:{ngrok_port}")
        
        return public_url
    except Exception as e:
        logger.error(f"Failed to set up ngrok: {e}")
        raise

def graceful_shutdown(server_process):
    """Gracefully shut down the server with proper player warnings."""
    if server_process and server_process.poll() is None:
        logger.info("Initiating graceful shutdown sequence...")
        
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 60 seconds. Your progress will be saved.")
        time.sleep(30)
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 30 seconds.")
        time.sleep(20)
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 10 seconds!")
        time.sleep(5)
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 5 seconds!")
        time.sleep(5)
        
        send_server_command(server_process, "say §c[SERVER] §fSaving world and restarting now. Please reconnect in about 2 minutes.")
        send_server_command(server_process, "save-all flush")
        time.sleep(3)
        send_server_command(server_process, "stop")
        
        logger.info("Waiting for server to stop...")
        for _ in range(30):
            if server_process.poll() is not None:
                break
            time.sleep(1)
        
        if server_process.poll() is None:
            logger.warning("Server did not stop gracefully, forcing termination")
            server_process.terminate()
            server_process.wait(timeout=10)
        
        logger.info("Minecraft server stopped")

def setup_command_api():
    """Set up a simple API for receiving commands."""
    
    @app.route('/api/command', methods=['POST'])
    def receive_command():
        data = request.json
        if 'command' in data and 'secret' in data:
            command_queue.append(data['command'])
            return jsonify({"status": "success"}), 200
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    
    @app.route('/api/status', methods=['GET'])
    def get_status():
        return jsonify({
            "status": "online",
            "timestamp": time.time()
        })
    
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('API_PORT', '8081'))), daemon=True).start()

def process_command_queue(server_process):
    """Process commands from the queue."""
    while not shutdown_requested:
        if command_queue:
            command = command_queue.pop(0)
            send_server_command(server_process, command)
        time.sleep(1)

def update_status_file(server_process, ngrok_url):
    """Update status file periodically."""
    global shutdown_requested
    
    status_file = 'server_status.json'
    
    while not shutdown_requested:
        try:
            status = {
                "status": "online" if server_process.poll() is None else "offline",
                "ngrok_url": ngrok_url,
                "timestamp": time.time()
            }
            with open(status_file, 'w') as f:
                json.dump(status, f)
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error updating status file: {e}")

def main():
    """Main function to launch Minecraft server and expose it via ngrok."""
    global shutdown_requested
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    jar_path = os.environ.get("MINECRAFT_JAR", "server.jar")
    java_args = os.environ.get("JAVA_ARGS", "-Xmx1024M -Xms1024M")
    ngrok_auth_token = os.environ.get("NGROK_AUTH_TOKEN")
    minecraft_port = int(os.environ.get("MINECRAFT_PORT", "25565"))
    backup_interval = float(os.environ.get("BACKUP_INTERVAL_HOURS", "6"))
    max_runtime = int(os.environ.get("MAX_RUNTIME_MINUTES", "340"))
    
    start_time = time.time()
    shutdown_time = start_time + (max_runtime * 60)
    
    try:
        setup_command_api()
        
        server_process = launch_minecraft_server(jar_path, java_args)
        
        ngrok_url = setup_ngrok(minecraft_port, ngrok_auth_token)
        
        status_thread = threading.Thread(target=update_status_file, args=(server_process, ngrok_url), daemon=True)
        status_thread.start()
        
        command_thread = threading.Thread(target=process_command_queue, args=(server_process,), daemon=True)
        command_thread.start()
        
        schedule_backup(server_process, backup_interval)
        
        while not shutdown_requested:
            output = server_process.stdout.readline()
            if output == b"" and server_process.poll() is not None:
                break
            if output:
                logger.info(output.strip())
                
            if time.time() > shutdown_time:
                logger.info("Max runtime reached, shutting down...")
                graceful_shutdown(server_process)
                break
                
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    finally:
        shutdown_requested = True
        
        if 'server_process' in locals() and server_process.poll() is None:
            graceful_shutdown(server_process)
        
        ngrok.kill()
        logger.info("ngrok tunnel closed")
        
        logger.info("Creating final backup before exit")
        create_backup()

if __name__ == "__main__":
    main()