# Minecraft Server Manager

## Overview
The Minecraft Server Manager is a web-based application designed to facilitate the management of Minecraft servers. It provides an intuitive interface for creating, configuring, and monitoring servers, as well as managing players and backups.

## Features
- **Server Creation**: Easily create new Minecraft servers with customizable settings.
- **Player Management**: Add, remove, and manage players on your servers, including whitelisting and banning.
- **Server Monitoring**: View real-time status and player information for each server.
- **Backup Management**: Schedule and manage backups of your server worlds and configurations.
- **GitHub Actions Integration**: Deploy and manage servers using GitHub Actions for continuous integration and deployment.

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

## Contributing
Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.