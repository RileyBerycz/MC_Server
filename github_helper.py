import os

def pull_latest():
    """Pull the latest changes from the remote repository."""
    os.system('git pull --rebase --autostash')

def commit_and_push(files, msg="Update via admin panel"):
    """
    Commit and push specified files to GitHub with a custom message.
    Args:
        files (str or list): File path(s) to add and commit.
        msg (str): Commit message.
    """
    if isinstance(files, str):
        files = [files]
    os.system('git config user.name "GitHub Actions"')
    os.system('git config user.email "actions@github.com"')
    for f in files:
        os.system(f'git add "{f}"')
    os.system(f'git commit -m "{msg}" || echo "No changes"')
    # Always pull before pushing to avoid non-fast-forward errors
    os.system('git pull --rebase --autostash')
    os.system('git push')