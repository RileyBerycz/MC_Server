
# Minecraft Server Admin Panel

A web-based dashboard to easily create, manage, and monitor Minecraft servers using GitHub Actions.

## Overview
The Minecraft Server Admin Panel is a web-based application designed to facilitate the management of Minecraft servers. It provides an intuitive interface for creating, configuring, and monitoring servers, as well as managing players and backups.

## Features
- **Server Creation**: Easily create new Minecraft servers with customizable settings.
- **Player Management**: Add, remove, and manage players on your servers, including whitelisting and banning.
- **Server Monitoring**: View real-time status and player information for each server.
- **Backup Management**: Schedule and manage backups of your server worlds and configurations.
- **GitHub Actions Integration**: Deploy and manage servers using GitHub Actions for continuous integration and deployment.

## Quick Start

1. **Run the Admin Panel**:
   - Go to the "Actions" tab in your repository
   - Select the "Minecraft Admin Panel" workflow
   - Click "Run workflow" button
   - Leave the default values or adjust as needed
   - Click the green "Run workflow" button

2. **Access the Admin Panel**:
   - Wait about 30-60 seconds for the workflow to start
   - In the running workflow logs, look for:
   ```
   ✨ ADMIN PANEL URL: https://interaction-republican-ownership-pregnant.trycloudflare.com ✨
   ```
   - Open this URL in your browser to access the admin panel

## Creating a Server

1. Click "Create New Server" on the dashboard
2. Fill out the server configuration:
   - Server Name: Give your server a name
   - Server Type: Choose from Vanilla, Paper, Forge, Fabric, or Bedrock
   - Memory: Amount of RAM to allocate (e.g., 2G)
   - Other settings as desired
3. Click "Create Server"

## Managing Servers

From the dashboard, you can:
- Start/Stop servers
- View server status and connected players
- Access server console and send commands
- Configure server settings
- Manage players (ops, whitelist, bans)

## Required Secrets

This application requires a GitHub Personal Access Token (PAT) with these permissions:
- `workflow` - To trigger server workflow actions
- `contents` - To read/write repository files

Your PAT should be stored as a repository secret named `WORKFLOW_PAT`.

## Project Structure
- **.github/workflows**: Contains GitHub Actions workflows for automating server deployment and management.
- **admin_panel**: Contains the Flask application for the admin panel, including static files (CSS and JS) and HTML templates.
- **server_configs**: Stores default configuration files for Minecraft servers.
- **server_templates**: Contains server property files for different types of Minecraft servers (vanilla, paper, forge, fabric, bedrock).
- **uploads**: Directory for storing uploaded files related to server management.
- **utils**: Contains utility scripts for GitHub API interactions and Minecraft server management.

## Installation
1. Clone the repository:
   ```
   git clone https://github.com/yourusername/minecraft-server-manager.git
   ```
2. Navigate to the project directory:
   ```
   cd minecraft-server-manager
   ```
3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage
1. Start the admin panel:
   ```
   python admin_panel.py
   ```
2. Access the admin panel in your web browser at `http://localhost:8080`.

## Shutting Down

When finished, click the "Quit Admin Panel" button to properly shut down the admin panel and terminate the GitHub Action.

## Contributing
Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.
