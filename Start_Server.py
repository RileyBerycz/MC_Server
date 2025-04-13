#!/usr/bin/env python3
import subprocess
import time
import os
import logging
from pyngrok import ngrok, conf

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def launch_minecraft_server(jar_path, java_args="-Xmx1024M -Xms1024M"):
    """Launch a Minecraft server using the specified JAR file."""
    try:
        cmd = f"java {java_args} -jar {jar_path} nogui"
        logger.info(f"Launching Minecraft server with command: {cmd}")
        
        # Start the Minecraft server process
        process = subprocess.Popen(
            cmd.split(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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

def main():
    """Main function to launch Minecraft server and expose it via ngrok."""
    # Get settings from environment variables or use defaults
    jar_path = os.environ.get("MINECRAFT_JAR", "server.jar")
    java_args = os.environ.get("JAVA_ARGS", "-Xmx1024M -Xms1024M")
    ngrok_auth_token = os.environ.get("NGROK_AUTH_TOKEN")
    minecraft_port = int(os.environ.get("MINECRAFT_PORT", "25565"))
    
    try:
        # Launch Minecraft server
        server_process = launch_minecraft_server(jar_path, java_args)
        
        # Set up ngrok tunnel
        ngrok_url = setup_ngrok(minecraft_port, ngrok_auth_token)
        
        # Monitor the Minecraft server output
        while True:
            output = server_process.stdout.readline()
            if output:
                logger.info(f"Server: {output.strip()}")
            
            # Check if the server process has exited
            if server_process.poll() is not None:
                logger.warning("Minecraft server has stopped. Exiting...")
                break
                
    except KeyboardInterrupt:
        logger.info("Stopping server and ngrok tunnel...")
    finally:
        # Clean up resources
        ngrok.kill()
        logger.info("ngrok tunnel closed")
        
        if 'server_process' in locals() and server_process.poll() is None:
            server_process.terminate()
            server_process.wait(timeout=10)
            logger.info("Minecraft server stopped")

if __name__ == "__main__":
    main()