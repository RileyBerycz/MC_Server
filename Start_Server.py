#!/usr/bin/env python3
import subprocess
import time
import os
import logging
import zipfile
import datetime
import threading
import signal
import sys
from pyngrok import ngrok, conf

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False

def create_backup():
    """Create a zip backup of the Minecraft server world."""
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.zip"
        logger.info(f"Creating backup: {backup_filename}")
        
        # Get world directory name - usually "world" but can be specified in server.properties
        world_dir = "world"  # Default world directory name
        if os.path.exists("server.properties"):
            with open("server.properties", "r") as f:
                for line in f:
                    if line.startswith("level-name="):
                        world_dir = line.split("=")[1].strip()
                        break
        
        if not os.path.exists(world_dir):
            logger.warning(f"World directory '{world_dir}' not found. Backing up all files.")
            # Back up everything except large jar files and previous backups
            with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk('.'):
                    if "backup_" in root or "__pycache__" in root:
                        continue
                    for file in files:
                        if file.endswith('.jar') or file.startswith('backup_'):
                            continue
                        file_path = os.path.join(root, file)
                        zipf.write(file_path)
        else:
            # Back up only the world directory
            with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(world_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path)
            
            # Also backup essential config files
            config_files = ["server.properties", "ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"]
            for file in config_files:
                if os.path.exists(file):
                    with zipfile.ZipFile(backup_filename, 'a', zipfile.ZIP_DEFLATED) as zipf:
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
    
    # Schedule the next backup
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
        
        # Notify players with shorter warnings
        send_server_command(server_process, "say §6[SERVER] §fBackup starting in 30 seconds. Expect brief lag.")
        time.sleep(20)
        send_server_command(server_process, "say §6[SERVER] §fBackup in 10 seconds...")
        time.sleep(5)
        send_server_command(server_process, "say §6[SERVER] §fBackup in 5 seconds...")
        time.sleep(5)
        
        # Notify backup starting
        send_server_command(server_process, "say §6[SERVER] §fBackup starting now. Server may lag for a few seconds.")
        
        # Save the world and disable auto-save
        send_server_command(server_process, "save-all flush")
        send_server_command(server_process, "save-off")
        logger.info("World saved and auto-save disabled")
        
        # Wait for save to complete - reduced time
        time.sleep(3)
        
        # Create the backup
        backup_file = create_backup()
        
        # Re-enable auto-save
        send_server_command(server_process, "save-on")
        logger.info("Auto-save re-enabled")
        
        # Notify completion
        send_server_command(server_process, "say §6[SERVER] §fBackup completed successfully!")
        
        logger.info(f"Backup process completed: {backup_file}")
        
        # Schedule the next backup
        schedule_backup(server_process, interval_hours)
        
    except Exception as e:
        logger.error(f"Error during backup process: {e}")
        send_server_command(server_process, "save-on")  # Ensure save is re-enabled
        
        # Still try to schedule the next backup
        schedule_backup(server_process, interval_hours)

def signal_handler(sig, frame):
    """Handle termination signals."""
    global shutdown_requested
    shutdown_requested = True
    logger.info("Shutdown signal received, will terminate after current operations complete")

def launch_minecraft_server(jar_path, java_args="-Xmx1024M -Xms1024M"):
    """Launch a Minecraft server using the specified JAR file."""
    try:
        # Try different launch formats
        cmd = f"java {java_args} -jar {jar_path} nogui"  # Note: removed the -- prefix
        logger.info(f"Launching Minecraft server with command: {cmd}")
        
        # Start the Minecraft server process with stdin pipe for commands
        process = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Wait for server to start
        time.sleep(10)
        return process
    except Exception as e:
        logger.error(f"Failed to launch Minecraft server: {e}")
        raise

def setup_ngrok(port=25565, auth_token=None):
    """Set up and start ngrok to expose the Minecraft server port."""
    try:
        # Set ngrok auth token if provided
        if auth_token:
            conf.get_default().auth_token = auth_token
            logger.info("ngrok authentication token set")
        
        # Start ngrok tunnel
        logger.info(f"Starting ngrok tunnel for port {port}...")
        public_url = ngrok.connect(port, "tcp").public_url
        
        # Extract the host and port from the public URL
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
        
        # Warn players
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 60 seconds. Your progress will be saved.")
        time.sleep(30)
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 30 seconds.")
        time.sleep(20)
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 10 seconds!")
        time.sleep(5)
        send_server_command(server_process, "say §c[SERVER] §fServer restarting in 5 seconds!")
        time.sleep(5)
        
        # Final save and shutdown
        send_server_command(server_process, "say §c[SERVER] §fSaving world and restarting now. Please reconnect in about 2 minutes.")
        send_server_command(server_process, "save-all flush")
        time.sleep(3)
        send_server_command(server_process, "stop")
        
        # Wait for server to stop gracefully (up to 30 seconds)
        logger.info("Waiting for server to stop...")
        for _ in range(30):
            if server_process.poll() is not None:
                break
            time.sleep(1)
        
        # Force terminate if still running
        if server_process.poll() is None:
            logger.warning("Server did not stop gracefully, forcing termination")
            server_process.terminate()
            server_process.wait(timeout=10)
        
        logger.info("Minecraft server stopped")

def main():
    """Main function to launch Minecraft server and expose it via ngrok."""
    global shutdown_requested
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Get settings from environment variables or use defaults
    jar_path = os.environ.get("MINECRAFT_JAR", "server.jar")
    java_args = os.environ.get("JAVA_ARGS", "-Xmx1024M -Xms1024M")
    ngrok_auth_token = os.environ.get("NGROK_AUTH_TOKEN")
    minecraft_port = int(os.environ.get("MINECRAFT_PORT", "25565"))
    backup_interval = float(os.environ.get("BACKUP_INTERVAL_HOURS", "6"))
    max_runtime = int(os.environ.get("MAX_RUNTIME_MINUTES", "340"))
    
    # Calculate shutdown time
    start_time = time.time()
    shutdown_time = start_time + (max_runtime * 60)
    
    try:
        # Launch Minecraft server
        server_process = launch_minecraft_server(jar_path, java_args)
        
        # Set up ngrok tunnel
        ngrok_url = setup_ngrok(minecraft_port, ngrok_auth_token)
        
        # Schedule first backup
        schedule_backup(server_process, backup_interval)
        
        # Monitor the Minecraft server output and check for shutdown time
        while not shutdown_requested:
            # Check if we're approaching the max runtime
            if time.time() > shutdown_time - 70:  # 70 seconds before shutdown time
                logger.info("Approaching maximum runtime, initiating shutdown")
                shutdown_requested = True
                break
                
            # Process server output
            try:
                output = server_process.stdout.readline()
                if output:
                    logger.info(f"Server: {output.strip()}")
                
                # Check if the server process has exited
                if server_process.poll() is not None:
                    logger.warning("Minecraft server has stopped. Exiting...")
                    break
            except Exception as e:
                logger.error(f"Error reading server output: {e}")
                time.sleep(1)
                
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    finally:
        # Clean up resources
        shutdown_requested = True
        
        if 'server_process' in locals() and server_process.poll() is None:
            graceful_shutdown(server_process)
        
        ngrok.kill()
        logger.info("ngrok tunnel closed")
        
        # Create a final backup before exit
        logger.info("Creating final backup before exit")
        create_backup()

if __name__ == "__main__":
    main()