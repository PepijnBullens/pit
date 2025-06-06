#!/usr/bin/env python3

import requests
import sys
import zipfile
import json
from pathlib import Path
import base64
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
import hashlib

SERVER_URL = "http://127.0.0.1:8000"
CONFIG_PATH = Path.home() / ".pitconfig"

def set_username(username):
    with open(CONFIG_PATH, "w") as f:
        json.dump({"username": username}, f)

def get_username():
    if not CONFIG_PATH.exists():
        print("No username configured. Please run 'pit login <username>'.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f).get("username")

def get_pubkey_bytes():
    pub_path = Path.home() / ".pit_id_rsa.pub"
    if not pub_path.exists():
        print("No public key found. Please run 'pit login <username>'.")
        sys.exit(1)
    with open(pub_path, "rb") as pub_file:
        return pub_file.read()

def get_hashed_username():
    pubkey_bytes = get_pubkey_bytes()
    return hashlib.sha256(pubkey_bytes).hexdigest()[:16]

def create_repo(repo_name):
    username = get_hashed_username()
    res = requests.post(f"{SERVER_URL}/repos/create", json={"username": username, "repo_name": repo_name}, headers=auth_headers())
    result = res.json()
    if res.status_code != 200:
        print(result.get("detail", "Unknown error"))
        return

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

    # File size cap: 100 MB
    FILE_SIZE_CAP = 100 * 1024 * 1024  # 100 MB

    # Gather all files in the repo folder except .pit
    files_to_commit = []
    for file_path in repo_path.iterdir():
        if file_path.is_file() and file_path.name != ".pit":
            if file_path.stat().st_size > FILE_SIZE_CAP:
                print(f"Error: '{file_path.name}' exceeds the 100 MB file size limit and will not be committed.")
                continue
            files_to_commit.append(("files", (file_path.name, open(file_path, "rb"))))

    if not files_to_commit:
        print("No files found to commit.")
        return

    data = {"commit_message": message}
    res = requests.post(
        f"{SERVER_URL}/repos/{username}/{repo_name}/commit",
        data=data,
        files=files_to_commit,
        headers=auth_headers()
    )
    # Close files after upload
    for _, filetuple in files_to_commit:
        filetuple[1].close()

    result = res.json()
    if res.status_code != 200:
        print(result.get("detail", "Unknown error"))
        return

def clone_repo(repo_name):
    username = get_hashed_username()
    res = requests.get(f"{SERVER_URL}/repos/{username}/{repo_name}/clone", headers=auth_headers())
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

    res = requests.get(f"{SERVER_URL}/repos/{username}/{repo_name}/pull", headers=auth_headers())
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

def list_repos():
    username = get_hashed_username()
    res = requests.get(f"{SERVER_URL}/repos/{username}/list", headers=auth_headers())
    result = res.json()
    if res.status_code != 200:
        print(result.get("detail", "Unknown error"))
        return
    
    print(f"List: {result.get('repositories', [])}")

def load_private_key():
    key_path = Path.home() / ".pit_id_rsa"
    if not key_path.exists():
        print("No private key found. Please generate one with 'pit keygen'.")
        sys.exit(1)
    with open(key_path, "rb") as key_file:
        return serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )

def get_public_key():
    pub_path = Path.home() / ".pit_id_rsa.pub"
    if not pub_path.exists():
        print("No public key found. Please run 'pit login <username>'.")
        sys.exit(1)
    with open(pub_path, "rb") as pub_file:
        pubkey_bytes = pub_file.read()
        return base64.b64encode(pubkey_bytes).decode()

def sign_message(message: str):
    private_key = load_private_key()
    signature = private_key.sign(
        message.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode()

def auth_headers():
    # Use a timestamp as a nonce
    import time
    nonce = str(int(time.time()))
    signature = sign_message(nonce)
    pubkey = get_public_key()
    return {
        "X-Pit-Pubkey": pubkey,
        "X-Pit-Signature": signature,
        "X-Pit-Nonce": nonce
    }

def login(username):
    set_username(username)
    key_path = Path.home() / ".pit_id_rsa"
    pub_path = Path.home() / ".pit_id_rsa.pub"
    if key_path.exists() or pub_path.exists():
        print(f"Username set to {username}. Key already exists.")
        return
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    with open(pub_path, "wb") as f:
        f.write(private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    print(f"Username set to {username}. Keys generated at {key_path} and {pub_path}")

def main():
    if len(sys.argv) < 2:
        print("Usage: cli.py [login|create|clone|commit|pull|list] ...")
        return
    cmd = sys.argv[1]
    if cmd == "login" and len(sys.argv) == 3:
        login(sys.argv[2])
    elif cmd == "create" and len(sys.argv) == 3:
        create_repo(sys.argv[2])
    elif cmd == "clone" and len(sys.argv) == 3:
        clone_repo(sys.argv[2])
    elif cmd == "commit" and len(sys.argv) == 3:
        commit_repo(sys.argv[2])
    elif cmd == "pull" and len(sys.argv) == 2:
        pull_repo()
    elif cmd == "list" and len(sys.argv) == 2:
        list_repos()
    else:
        print("Invalid command or arguments.")

if __name__ == "__main__":
    main()
