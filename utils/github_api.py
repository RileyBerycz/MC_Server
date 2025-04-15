import requests
import os

GITHUB_API_URL = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

def create_repo(repo_name, private=True):
    """Create a new GitHub repository."""
    url = f"{GITHUB_API_URL}/user/repos"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "name": repo_name,
        "private": private
    }
    response = requests.post(url, headers=headers, json=data)
    return response.json()

def get_repo(repo_name):
    """Get details of a GitHub repository."""
    url = f"{GITHUB_API_URL}/repos/{repo_name}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)
    return response.json()

def delete_repo(repo_name):
    """Delete a GitHub repository."""
    url = f"{GITHUB_API_URL}/repos/{repo_name}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.delete(url, headers=headers)
    return response.status_code

def list_repos():
    """List all repositories for the authenticated user."""
    url = f"{GITHUB_API_URL}/user/repos"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)
    return response.json()