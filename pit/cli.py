#!/usr/bin/env python3

import requests
import sys
import zipfile
import json
from pathlib import Path
import getpass

SERVER_URL = "https://pit.pepijnbullens.nl"

def prompt_credentials():
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    return username, password

def pit_dir(repo_path=None):
    repo_path = repo_path or Path.cwd()
    return repo_path / ".pit"

def pit_config_path(repo_path=None):
    return pit_dir(repo_path) / ".config"

def pit_commits_dir(repo_path=None):
    return pit_dir(repo_path) / "commits"

def read_pit_file(repo_path=None):
    config_path = pit_config_path(repo_path)
    if not config_path.exists():
        print("Not inside a pit repo (missing .pit/.config file).")
        return None
    with config_path.open() as f:
        info = json.load(f)
    username = info.get("username")
    repo_name = info.get("repo_name")
    if not username or not repo_name:
        print("Invalid .pit/.config file.")
        return None
    return username, repo_name

def write_pit_config(username, repo_name, repo_path=None):
    pitdir = pit_dir(repo_path)
    pitdir.mkdir(exist_ok=True)
    config_path = pit_config_path(repo_path)
    with config_path.open("w") as f:
        json.dump({"username": username, "repo_name": repo_name}, f)

def handle_response(res):
    try:
        result = res.json()
    except Exception:
        print(f"Server returned non-JSON response (status {res.status_code}): {res.text}")
        return None
    if res.status_code != 200:
        print(result.get("detail", "Unknown error"))
        return None
    return result

def register():
    username = input("Choose username: ")
    password = getpass.getpass("Choose password: ")
    res = requests.post(f"{SERVER_URL}/register", json={"username": username, "password": password})
    result = handle_response(res)
    if result:
        print(result.get("message", "Registration complete."))

def login():
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    res = requests.post(f"{SERVER_URL}/login", json={"username": username, "password": password})
    result = handle_response(res)
    if result:
        print(result.get("message", "Login complete."))

def create_repo(repo_name):
    username, password = prompt_credentials()
    res = requests.post(f"{SERVER_URL}/repos/create", json={
        "username": username,
        "password": password,
        "repo_name": repo_name
    })
    result = handle_response(res)
    if not result:
        return
    print(result.get("message", "Repo created"))

def commit_repo(message):
    repo_path = Path.cwd()
    pit_info = read_pit_file(repo_path)
    if not pit_info:
        return
    username, repo_name = pit_info
    FILE_SIZE_CAP = 100 * 1024 * 1024  # 100 MB

    files_to_commit = []
    for file_path in repo_path.rglob("*"):
        if file_path.is_file() and not str(file_path).startswith(str(pit_dir(repo_path))):
            rel_path = file_path.relative_to(repo_path)
            if file_path.stat().st_size > FILE_SIZE_CAP:
                print(f"Error: '{rel_path}' exceeds the 100 MB file size limit and will not be committed.")
                continue
            files_to_commit.append((str(rel_path), file_path))
    if not files_to_commit:
        print("No files found to commit.")
        return

    # Save commit locally in .pit/commits/
    commits_dir = pit_commits_dir(repo_path)
    commits_dir.mkdir(parents=True, exist_ok=True)
    # Find next commit id
    existing = sorted(commits_dir.glob("*"))
    commit_id = f"{len(existing)+1:03d}_{message.replace(' ', '_')[:20]}"
    commit_path = commits_dir / commit_id
    commit_path.mkdir()
    for rel_path, file_path in files_to_commit:
        dest = commit_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "rb") as src, open(dest, "wb") as dst:
            dst.write(src.read())
    metadata = {
        "message": message,
        "files": [rel_path for rel_path, _ in files_to_commit]
    }
    with open(commit_path / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved commit locally: {commit_id}")

def push_repo():
    repo_path = Path.cwd()
    pit_info = read_pit_file(repo_path)
    if not pit_info:
        return
    username, repo_name = pit_info
    password = getpass.getpass("Password: ")
    commits_dir = pit_commits_dir(repo_path)
    if not commits_dir.exists():
        print("No local commits to push.")
        return
    commit_dirs = sorted([d for d in commits_dir.iterdir() if d.is_dir()])
    if not commit_dirs:
        print("No local commits to push.")
        return
    for commit_dir in commit_dirs:
        meta_path = commit_dir / "metadata.json"
        if not meta_path.exists():
            print(f"Skipping {commit_dir.name}: missing metadata.json")
            continue
        with open(meta_path) as f:
            metadata = json.load(f)
        files = []
        file_handles = []
        for rel_path in metadata["files"]:
            file_path = commit_dir / rel_path
            if not file_path.exists():
                print(f"Skipping file {rel_path} in {commit_dir.name}: not found")
                continue
            fh = open(file_path, "rb")
            file_handles.append(fh)
            files.append(("files", (rel_path, fh)))
        data = {
            "commit_message": metadata["message"],
            "password": password
        }
        res = requests.post(
            f"{SERVER_URL}/repos/{username}/{repo_name}/commit",
            data=data,
            files=files
        )
        for fh in file_handles:
            fh.close()
        result = handle_response(res)
        if not result:
            print(f"Failed to push commit {commit_dir.name}")
            return
        print(f"Pushed commit: {commit_dir.name}")
    # Clear local commits after successful push
    import shutil
    shutil.rmtree(commits_dir)
    commits_dir.mkdir(exist_ok=True)
    print("All local commits pushed and cleared.")

def pull_repo(commit_id=None):
    repo_path = Path.cwd()
    pit_info = read_pit_file(repo_path)
    if not pit_info:
        return
    username, repo_name = pit_info
    password = getpass.getpass("Password: ")
    url = f"{SERVER_URL}/repos/{username}/{repo_name}/pull"
    params = {"password": password}
    if commit_id:
        params["commit_id"] = commit_id
    res = requests.get(url, params=params)
    if res.status_code == 200:
        zip_path = repo_path / "pull_temp.zip"
        with open(zip_path, "wb") as f:
            f.write(res.content)
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            print("Error: Received empty or missing zip file from server.")
            return
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for path in repo_path.iterdir():
                    if path.name == ".pit":
                        continue
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        import shutil
                        shutil.rmtree(path)
                zip_ref.extractall(repo_path)
                print("Updated files:")
                for name in zip_ref.namelist():
                    print(f" - {name}")
        except zipfile.BadZipFile:
            print("Error: The downloaded file is not a valid zip archive.")
            return
        finally:
            if zip_path.exists():
                zip_path.unlink()
        print(f"Pulled changes for {repo_name} (commit: {commit_id or 'latest'}).")
    else:
        try:
            print(f"Failed to pull: {res.json()}")
        except Exception:
            print("Failed to pull: Unknown error")

def list_repos():
    username, password = prompt_credentials()
    res = requests.get(f"{SERVER_URL}/repos/{username}/list", params={"password": password})
    result = handle_response(res)
    if result:
        print(f"List: {result.get('repositories', [])}")

def clone_repo(repo_name):
    username, password = prompt_credentials()
    res = requests.get(
        f"{SERVER_URL}/repos/{username}/{repo_name}/clone",
        params={"password": password}
    )
    if res.status_code != 200:
        try:
            result = res.json()
            print(result.get("detail", "Unknown error"))
        except Exception:
            print("Unknown error")
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
    # Move .pit to .pit/.config and create .pit/commits
    pit_file = repo_path / ".pit"
    pit_dir_path = repo_path / ".pit"
    pit_config = pit_dir_path / ".config"
    if pit_file.exists():
        if pit_file.is_file():
            pit_file.unlink()  # Remove the file so we can create the directory
        if not pit_dir_path.exists():
            pit_dir_path.mkdir(exist_ok=True)
        # If .pit was a file, we need to recreate the config file
        with open(pit_config, "w") as f:
            json.dump({"username": username, "repo_name": repo_name}, f)
    else:
        if not pit_dir_path.exists():
            pit_dir_path.mkdir(exist_ok=True)
        if not pit_config.exists():
            with open(pit_config, "w") as f:
                json.dump({"username": username, "repo_name": repo_name}, f)
    (pit_dir_path / "commits").mkdir(exist_ok=True)
    print(f"Cloned into {repo_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: cli.py [register|login|create|clone|commit|push|pull|list] ...")
        return
    cmd = sys.argv[1]
    if cmd == "register":
        register()
    elif cmd == "login":
        login()
    elif cmd == "create" and len(sys.argv) == 3:
        create_repo(sys.argv[2])
    elif cmd == "clone" and len(sys.argv) == 3:
        clone_repo(sys.argv[2])
    elif cmd == "commit" and len(sys.argv) == 3:
        commit_repo(sys.argv[2])
    elif cmd == "push" and len(sys.argv) == 2:
        push_repo()
    elif cmd == "pull":
        if len(sys.argv) == 2:
            pull_repo()
        elif len(sys.argv) == 3:
            pull_repo(sys.argv[2])
        else:
            print("Usage: cli.py pull [commit_id]")
    elif cmd == "list" and len(sys.argv) == 2:
        list_repos()
    else:
        print("Invalid command or arguments.")

if __name__ == "__main__":
    main()
