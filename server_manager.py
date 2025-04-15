#!/usr/bin/env python3
import os
import subprocess
import time
import logging
import threading
import signal
import json
import zipfile
from flask import Flask, request, jsonify

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ServerManager:
    """Manager for Minecraft server instances"""
    
    def __init__(self):
        self.servers = {}  # Dictionary to store server processes
        self.tunnels = {}  # Dictionary to store tunnel processes
        self.shutdown_requested = False
    
    def start_server(self, server_id, server_type, memory="2G", max_players=20, port=25565,
                    difficulty="normal", gamemode="survival", seed=None):
        """
        Start a Minecraft server
        
        Args:
            server_id: Unique identifier for the server
            server_type: Type of server (vanilla, paper, forge, fabric, bedrock)
            memory: Memory allocation (e.g., "2G")
            max_players: Maximum number of players
            port: Server port
            difficulty: Game difficulty
            gamemode: Game mode
            seed: World seed (optional)
            
        Returns:
            bool: Whether the server started successfully
        """
        logger.info(f"Starting {server_type} server with ID: {server_id}")
        
        # Create server directory if it doesn't exist
        server_dir = f"server/{server_id}"
        os.makedirs(server_dir, exist_ok=True)
        
        # Change to server directory
        original_dir = os.getcwd()
        os.chdir(server_dir)
        
        try:
            # Create required server files
            self.create_server_properties(max_players, difficulty, gamemode, seed, port)
            
            # Create EULA file
            with open("eula.txt", "w") as eula_file:
                eula_file.write("eula=true\n")
            
            # Start server based on type
            if server_type == 'bedrock':
                process = self.start_bedrock_server()
            else:
                jar_file = self.prepare_server_jar(server_type)
                java_args = self.get_java_args(server_type, memory)
                process = self.start_java_server(jar_file, java_args)
            
            # Set up cloudflared tunnel
            tunnel_process, public_url = self.setup_cloudflared_tunnel(port)
            
            if process and process.poll() is None:
                # Store server process and info
                self.servers[server_id] = {
                    'process': process,
                    'type': server_type,
                    'start_time': time.time(),
                    'public_url': public_url,
                    'port': port,
                    'tunnel_process': tunnel_process
                }
                
                # Set up background threads for status updates and command processing
                self.start_monitor_threads(server_id)
                
                logger.info(f"Server {server_id} started successfully")
                return True
            else:
                logger.error(f"Failed to start server {server_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error starting server {server_id}: {e}")
            return False
        finally:
            # Return to original directory
            os.chdir(original_dir)
    
    def stop_server(self, server_id):
        """
        Stop a running Minecraft server
        
        Args:
            server_id: Server ID to stop
            
        Returns:
            bool: Whether the server was successfully stopped
        """
        if server_id not in self.servers:
            logger.warning(f"Server {server_id} not found")
            return False
        
        server = self.servers[server_id]
        process = server.get('process')
        
        if not process or process.poll() is not None:
            logger.warning(f"Server {server_id} is not running")
            return False
        
        try:
            # Send stop command to server
            logger.info(f"Stopping server {server_id}")
            self.send_command(server_id, "stop")
            
            # Wait for server to stop gracefully
            for _ in range(30):
                if process.poll() is not None:
                    break
                time.sleep(1)
            
            # Force terminate if still running
            if process.poll() is None:
                logger.warning(f"Server {server_id} did not stop gracefully, terminating")
                process.terminate()
                process.wait(timeout=10)
            
            # Clean up tunnel process
            if 'tunnel_process' in server and server['tunnel_process']:
                server['tunnel_process'].terminate()
            
            # Remove from active servers
            del self.servers[server_id]
            
            logger.info(f"Server {server_id} stopped successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error stopping server {server_id}: {e}")
            return False
    
    def send_command(self, server_id, command):
        """
        Send a command to a running server
        
        Args:
            server_id: Server ID
            command: Command to send
            
        Returns:
            bool: Whether the command was sent successfully
        """
        if server_id not in self.servers:
            logger.warning(f"Server {server_id} not found")
            return False
        
        process = self.servers[server_id].get('process')
        
        if not process or process.poll() is not None:
            logger.warning(f"Server {server_id} is not running")
            return False
        
        try:
            logger.info(f"Sending command to server {server_id}: {command}")
            process.stdin.write(f"{command}\n")
            process.stdin.flush()
            return True
        except Exception as e:
            logger.error(f"Error sending command to server {server_id}: {e}")
            return False
    
    def get_server_status(self, server_id):
        """
        Get the status of a server
        
        Args:
            server_id: Server ID
            
        Returns:
            dict: Server status information
        """
        if server_id not in self.servers:
            return {
                'running': False,
                'address': None,
                'uptime': 0,
                'online_players': 0,
                'version': 'Unknown'
            }
        
        server = self.servers[server_id]
        process = server.get('process')
        
        # Check if server process is still running
        is_running = process and process.poll() is None
        
        if is_running:
            status = {
                'running': True,
                'address': server.get('public_url', 'Not available'),
                'uptime': time.time() - server.get('start_time', time.time()),
                'online_players': 0,  # We would need to query the server for this
                'version': 'Running'  # Similarly would need server query
            }
        else:
            # Server process died unexpectedly
            status = {
                'running': False,
                'address': None,
                'uptime': 0,
                'online_players': 0,
                'version': 'Offline'
            }
            
            # Clean up dead server
            if server_id in self.servers:
                del self.servers[server_id]
        
        return status
    
    def create_backup(self, server_id):
        """
        Create a backup of the server world
        
        Args:
            server_id: Server ID
            
        Returns:
            str: Path to the backup file or None if failed
        """
        if server_id not in self.servers:
            logger.warning(f"Server {server_id} not found")
            return None
        
        server_dir = f"server/{server_id}"
        if not os.path.exists(server_dir):
            logger.warning(f"Server directory {server_dir} not found")
            return None
        
        try:
            # Change to server directory
            original_dir = os.getcwd()
            os.chdir(server_dir)
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{timestamp}.zip"
            
            # Determine world directory name
            world_dir = "world"  # Default
            if os.path.exists("server.properties"):
                with open("server.properties", "r") as f:
                    for line in f:
                        if line.startswith("level-name="):
                            world_dir = line.split("=")[1].strip()
            
            # Create backup
            with zipfile.ZipFile(backup_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Add world files
                if os.path.exists(world_dir):
                    for root, dirs, files in os.walk(world_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(file_path, os.path.relpath(file_path, start="."))
                
                # Add config files
                config_files = ["server.properties", "ops.json", "whitelist.json", 
                                "banned-players.json", "banned-ips.json"]
                for file in config_files:
                    if os.path.exists(file):
                        zipf.write(file)
            
            # Return to original directory
            os.chdir(original_dir)
            
            logger.info(f"Backup created for server {server_id}: {backup_filename}")
            return os.path.join(server_dir, backup_filename)
            
        except Exception as e:
            logger.error(f"Error creating backup for server {server_id}: {e}")
            # Return to original directory in case of error
            if 'original_dir' in locals():
                os.chdir(original_dir)
            return None
    
    def create_server_properties(self, max_players, difficulty, gamemode, seed, port):
        """Create server.properties file with specified settings"""
        with open("server.properties", "w") as f:
            f.write(f"max-players={max_players}\n")
            f.write(f"difficulty={difficulty}\n")
            f.write(f"gamemode={gamemode}\n")
            f.write(f"server-port={port}\n")
            f.write("enable-command-block=true\n")
            f.write("spawn-protection=0\n")
            
            if seed:
                f.write(f"level-seed={seed}\n")
    
    def prepare_server_jar(self, server_type):
        """Download or prepare the server JAR file based on type"""
        # Check if server jar already exists
        if os.path.exists("server.jar"):
            return "server.jar"
        
        # Download URLs based on server type
        download_urls = {
            'vanilla': 'https://piston-data.mojang.com/v1/objects/2b95cc780c99ed04682fa1355e1144a4c5aaf214/server.jar',
            'paper': 'https://api.papermc.io/v2/projects/paper/versions/1.21.2/builds/324/downloads/paper-1.21.2-324.jar',
            'forge': 'https://maven.minecraftforge.net/net/minecraftforge/forge/1.21.1-48.0.6/forge-1.21.1-48.0.6-installer.jar',
            'fabric': 'https://maven.fabricmc.net/net/fabricmc/fabric-installer/0.14.21/fabric-installer-0.14.21.jar',
        }
        
        if server_type not in download_urls:
            logger.warning(f"Unknown server type: {server_type}")
            raise ValueError(f"Unknown server type: {server_type}")
        
        # Download the server JAR
        import requests
        url = download_urls[server_type]
        logger.info(f"Downloading {server_type} server JAR from {url}")
        
        try:
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                with open("server.jar", 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                logger.info(f"Server JAR downloaded successfully")
                return "server.jar"
            else:
                logger.error(f"Failed to download server JAR: {response.status_code}")
                raise Exception(f"Failed to download server JAR: {response.status_code}")
        except Exception as e:
            logger.error(f"Error downloading server JAR: {e}")
            raise
    
    def get_java_args(self, server_type, memory):
        """Get Java arguments based on server type"""
        if server_type == 'vanilla':
            return f"-Xmx{memory} -Xms{memory}"
        elif server_type == 'paper':
            return f"-Xmx{memory} -Xms{memory} -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200"
        elif server_type == 'forge':
            return f"-Xmx{memory} -Xms{memory} -XX:+UseG1GC"
        elif server_type == 'fabric':
            return f"-Xmx{memory} -Xms{memory}"
        else:
            return f"-Xmx{memory} -Xms{memory}"
    
    def start_java_server(self, jar_file, java_args):
        """Start a Java-based Minecraft server"""
        cmd = f"java {java_args} -jar {jar_file} nogui"
        logger.info(f"Starting Java server with command: {cmd}")
        
        process = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Wait a bit for server to start initializing
        time.sleep(5)
        return process
    
    def start_bedrock_server(self):
        """Start a Bedrock server"""
        if not os.path.exists("bedrock_server"):
            logger.error("Bedrock server executable not found")
            return None
        
        cmd = "LD_LIBRARY_PATH=. ./bedrock_server"
        logger.info("Starting Bedrock server")
        
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            universal_newlines=True
        )
        
        # Wait a bit for server to start initializing
        time.sleep(5)
        return process
    
    def setup_cloudflared_tunnel(self, port):
        """Set up a cloudflared tunnel for the server"""
        try:
            logger.info(f"Starting cloudflared tunnel for port {port}")
            
            process = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"tcp://localhost:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for tunnel to establish and extract URL
            time.sleep(5)
            
            # Check stderr for tunnel URL
            for _ in range(20):
                if process.stderr.peek():
                    line = process.stderr.readline().decode('utf-8')
                    if "tcp://" in line:
                        match = re.search(r'tcp://[a-z0-9\-]+\.trycloudflare\.com', line)
                        if match:
                            url = match.group(0)
                            logger.info(f"Cloudflared tunnel established: {url}")
                            return process, url
                time.sleep(0.5)
            
            logger.warning("Could not find tunnel URL in cloudflared output")
            return process, None
        
        except Exception as e:
            logger.error(f"Failed to set up cloudflared tunnel: {e}")
            return None, None
    
    def start_monitor_threads(self, server_id):
        """Start monitoring threads for the server"""
        # This would track server status, process output, etc.
        server = self.servers[server_id]
        
        def monitor_output():
            """Monitor and log server output"""
            process = server['process']
            while process and process.poll() is None:
                try:
                    output = process.stdout.readline()
                    if output:
                        output = output.strip()
                        logger.info(f"[Server {server_id}] {output}")
                except Exception:
                    break
        
        thread = threading.Thread(target=monitor_output, daemon=True)
        thread.start()
        
        # Store thread reference
        server['monitor_thread'] = thread
    
    def cleanup(self):
        """Clean up all running servers"""
        server_ids = list(self.servers.keys())
        
        for server_id in server_ids:
            try:
                self.stop_server(server_id)
            except Exception as e:
                logger.error(f"Error cleaning up server {server_id}: {e}")