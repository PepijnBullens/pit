#!/usr/bin/env python3

import requests
import sys
import zipfile
import json
from pathlib import Path

SERVER_URL = "http://127.0.0.1:8000"

def create_repo(username, repo_name):
    res = requests.post(f"{SERVER_URL}/repos/create", json={"username": username, "repo_name": repo_name})
    print(res.json())

def commit_repo(message):
    repo_path = Path.cwd()
    pit_file = repo_path / ".pit"
    if not pit_file.exists():
        print("Not inside a pit repo (missing .pit file).")
        return
    
    with pit_file.open() as f:
        info = json.load(f)
    username = info.get("username")
    repo_name = info.get("repo_name")
    if not username or not repo_name:
        print("Invalid .pit file.")
        return

    # Gather all files in the repo folder except .pit
    files_to_commit = []
    for file_path in repo_path.iterdir():
        if file_path.is_file() and file_path.name != ".pit":
            files_to_commit.append(("files", (file_path.name, open(file_path, "rb"))))

    if not files_to_commit:
        print("No files found to commit.")
        return

    data = {"commit_message": message}
    res = requests.post(
        f"{SERVER_URL}/repos/{username}/{repo_name}/commit",
        data=data,
        files=files_to_commit
    )
    # Close files after upload
    for _, filetuple in files_to_commit:
        filetuple[1].close()

    print(res.json())

def clone_repo(username, repo_name):
    res = requests.get(f"{SERVER_URL}/repos/{username}/{repo_name}/clone")
    if res.status_code != 200:
        print(res.json())
        return

    repo_path = Path.cwd() / repo_name
    if repo_path.exists():
        print(f"Folder '{repo_name}' already exists in current directory.")
        return

    repo_path.mkdir(parents=True, exist_ok=False)

    zip_path = Path("temp") / f"{username}_{repo_name}.zip"
    zip_path.parent.mkdir(exist_ok=True)
    with open(zip_path, "wb") as f:
        f.write(res.content)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(repo_path)

    zip_path.unlink()
    print(f"Cloned into {repo_path}")

def pull_repo():
    repo_path = Path.cwd()
    pit_file = repo_path / ".pit"
    if not pit_file.exists():
        print("Error: Not inside a pit repository (missing .pit file).")
        return
    
    with pit_file.open() as f:
        info = json.load(f)
    username = info.get("username")
    repo_name = info.get("repo_name")
    if not username or not repo_name:
        print("Error: Invalid .pit file.")
        return

    res = requests.get(f"{SERVER_URL}/repos/{username}/{repo_name}/pull")
    if res.status_code == 200:
        zip_path = repo_path / "pull_temp.zip"
        with open(zip_path, "wb") as f:
            f.write(res.content)

        # Extract and overwrite existing files
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(repo_path)
        zip_path.unlink()
        print(f"Pulled latest changes for {repo_name}.")
    else:
        print(f"Failed to pull: {res.json()}")

def main():
    if len(sys.argv) < 2:
        print("Usage: client.py [create|clone|commit|pull] ...")
        return

    cmd = sys.argv[1]

    if cmd == "create" and len(sys.argv) == 4:
        create_repo(sys.argv[2], sys.argv[3])
    elif cmd == "clone" and len(sys.argv) == 4:
        clone_repo(sys.argv[2], sys.argv[3])
    elif cmd == "commit" and len(sys.argv) == 3:
        commit_repo(sys.argv[2])
    elif cmd == "pull" and len(sys.argv) == 2:
        pull_repo()
    else:
        print("Invalid command or arguments.")

if __name__ == "__main__":
    main()
