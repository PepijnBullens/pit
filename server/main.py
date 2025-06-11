from fastapi import FastAPI, HTTPException, Form, File, UploadFile, Request, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import shutil
import json
from datetime import datetime
import hashlib
import zipfile
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64

app = FastAPI()

STORAGE_DIR = Path("storage")
USER_KEYS_DIR = Path("user_keys")

class RepoCreateRequest(BaseModel):
    username: str
    repo_name: str

def get_username_from_pubkey(pubkey_bytes: bytes):
    # hash the pubkey to get a username
    return hashlib.sha256(pubkey_bytes).hexdigest()[:16]

async def verify_auth(request: Request):
    pubkey_b64 = request.headers.get("X-Pit-Pubkey")
    signature = request.headers.get("X-Pit-Signature")
    nonce = request.headers.get("X-Pit-Nonce")
    if not pubkey_b64 or not signature or not nonce:
        raise HTTPException(status_code=401, detail="Missing authentication headers")
    try:
        pubkey_bytes = base64.b64decode(pubkey_b64)
        pubkey = serialization.load_pem_public_key(pubkey_bytes)
        pubkey.verify(
            base64.b64decode(signature),
            nonce.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid signature")
    username = get_username_from_pubkey(pubkey_bytes)
    return username

@app.post("/repos/create")
async def create_repo(payload: RepoCreateRequest, username: str = Depends(verify_auth)):
    user_dir = STORAGE_DIR / username
    repo_dir = user_dir / payload.repo_name / "commits"

    if repo_dir.exists():
        raise HTTPException(status_code=400, detail="Repository already exists")

    try:
        repo_dir.mkdir(parents=True, exist_ok=False)
        # Create initial empty commit folder to allow cloning immediately
        initial_commit = repo_dir / "000_initial"
        initial_commit.mkdir()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "Repository created successfully", "path": str(repo_dir)}

@app.get("/repos/{username}/{repo_name}/clone")
async def clone_repo(username: str, repo_name: str):
    repo_path = STORAGE_DIR / username / repo_name / "commits"
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")

    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()])
    if not commit_dirs:
        raise HTTPException(status_code=404, detail="No commits to clone")

    latest_commit = commit_dirs[-1]
    zip_path = Path("temp") / f"{username}_{repo_name}.zip"
    zip_path.parent.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_path, 'w') as zipf:
        # Recursively add all files except metadata.json
        for file in latest_commit.rglob("*"):
            if file.is_file() and file.name != "metadata.json":
                arcname = file.relative_to(latest_commit)
                zipf.write(file, arcname=arcname)

        # Add .pit file to mark repo folder
        pit_info = {"username": username, "repo_name": repo_name}
        pit_path = latest_commit / ".pit"
        with open(pit_path, "w") as f:
            json.dump(pit_info, f)
        zipf.write(pit_path, arcname=".pit")
        pit_path.unlink()

    return FileResponse(zip_path, filename=f"{repo_name}.zip")

@app.get("/repos/{username}/{repo_name}/pull")
async def pull_repo(username: str, repo_name: str, commit_id: str = Query(None)):
    repo_path = STORAGE_DIR / username / repo_name / "commits"
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")

    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()])
    if not commit_dirs:
        raise HTTPException(status_code=404, detail="No commits to pull")

    if commit_id:
        # Find the commit directory matching the commit_id
        commit_dir = repo_path / commit_id
        if not commit_dir.exists() or not commit_dir.is_dir():
            raise HTTPException(status_code=404, detail="Commit not found")
        target_commit = commit_dir
    else:
        target_commit = commit_dirs[-1]

    zip_buffer = Path("temp") / f"{username}_{repo_name}_pull.zip"
    zip_buffer.parent.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_buffer, 'w') as zipf:
        # Recursively add all files except metadata.json
        for file in target_commit.rglob("*"):
            if file.is_file() and file.name != "metadata.json":
                arcname = file.relative_to(target_commit)
                zipf.write(file, arcname=arcname)

    return FileResponse(zip_buffer, filename=f"{repo_name}.zip")

@app.get("/repos/{username}/list")
async def list_repos(username: str):
    user_dir = STORAGE_DIR / username
    if not user_dir.exists() or not user_dir.is_dir():
        raise HTTPException(status_code=404, detail="User not found")
    repos = [repo.name for repo in user_dir.iterdir() if (repo / "commits").exists()]
    return {"repositories": repos}
    

@app.post("/repos/{username}/{repo_name}/commit")
async def commit_files(
    username: str,
    repo_name: str,
    commit_message: str = Form(...),
    files: list[UploadFile] = File(...)
):
    # File size cap: 100 MB
    FILE_SIZE_CAP = 100 * 1024 * 1024  # 100 MB

    repo_path = STORAGE_DIR / username / repo_name / "commits"
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")

    # Check file sizes before processing
    for file in files:
        file.file.seek(0, 2)  # Seek to end
        size = file.file.tell()
        file.file.seek(0)
        if size > FILE_SIZE_CAP:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' exceeds the 100 MB file size limit."
            )

    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()])
    old_files_dict = {}
    if commit_dirs:
        latest_commit = commit_dirs[-1]
        for file_path in latest_commit.iterdir():
            if file_path.is_file() and file_path.name != "metadata.json":
                with file_path.open("rb") as f:
                    content = f.read()
                    old_files_dict[file_path.name] = hashlib.sha256(content).hexdigest()

    new_files_dict = {}
    for file in files:
        file.file.seek(0)
        content = file.file.read()
        new_files_dict[file.filename] = hashlib.sha256(content).hexdigest()
        file.file.seek(0)

    old_set = set(old_files_dict.keys())
    new_set = set(new_files_dict.keys())

    added = list(new_set - old_set)
    removed = list(old_set - new_set)
    changed = [fname for fname in (old_set & new_set) if old_files_dict[fname] != new_files_dict[fname]]

    different = bool(added or removed or changed)
    if not different:
        raise HTTPException(status_code=400, detail="No changes made")

    existing_commits = sorted(repo_path.glob("*"))
    commit_id = f"{len(existing_commits)+1:03d}_{commit_message.replace(' ', '_')[:20]}"
    commit_path = repo_path / commit_id
    commit_path.mkdir()

    for file in files:
        file_path = commit_path / file.filename
        file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure parent dirs exist
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    metadata = {
        "message": commit_message,
        "timestamp": datetime.utcnow().isoformat(),
        "files": [file.filename for file in files]
    }
    with (commit_path / "metadata.json").open("w") as meta_file:
        json.dump(metadata, meta_file, indent=2)

    return {"message": "Commit created", "commit_id": commit_id}
