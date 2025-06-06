from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from pydantic import BaseModel
from pathlib import Path
import shutil
import json
from datetime import datetime
import hashlib

app = FastAPI()

# Define a base directory to hold all repos
STORAGE_DIR = Path("storage")

class RepoCreateRequest(BaseModel):
    username: str
    repo_name: str

@app.post("/repos/create")
async def create_repo(payload: RepoCreateRequest):
    user_dir = STORAGE_DIR / payload.username
    repo_dir = user_dir / payload.repo_name / "commits"

    if repo_dir.exists():
        raise HTTPException(status_code=400, detail="Repository already exists")

    try:
        repo_dir.mkdir(parents=True, exist_ok=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "Repository created successfully", "path": str(repo_dir)}



@app.post("/repos/{username}/{repo_name}/compare")
async def compare_files(
    username: str,
    repo_name: str,
    files: list[UploadFile] = File(...)
):
    repo_path = STORAGE_DIR / username / repo_name / "commits"
    
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")

    # Get the latest commit directory
    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()], key=lambda d: d.name)
    old_files_dict = {}
    if not commit_dirs:
        old_files_dict = {}
    else:
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

    # Find added, removed, and changed files
    old_set = set(old_files_dict.keys())
    new_set = set(new_files_dict.keys())

    added = list(new_set - old_set)
    removed = list(old_set - new_set)
    changed = [
        fname for fname in (old_set & new_set)
        if old_files_dict[fname] != new_files_dict[fname]
    ]

    different = bool(added or removed or changed)

    return {
        "message": "Changes made" if different else "No changes made",
        "different": different,
        "added": added,
        "removed": removed,
        "changed": changed
    }
        



@app.post("/repos/{username}/{repo_name}/commit")
async def commit_files(
    username: str,
    repo_name: str,
    commit_message: str = Form(...),
    files: list[UploadFile] = File(...)
):
    repo_path = STORAGE_DIR / username / repo_name / "commits"

    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")

        # Get the latest commit directory
    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()], key=lambda d: d.name)
    old_files_dict = {}
    if not commit_dirs:
        old_files_dict = {}
    else:
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

    # Find added, removed, and changed files
    old_set = set(old_files_dict.keys())
    new_set = set(new_files_dict.keys())

    added = list(new_set - old_set)
    removed = list(old_set - new_set)
    changed = [
        fname for fname in (old_set & new_set)
        if old_files_dict[fname] != new_files_dict[fname]
    ]

    different = bool(added or removed or changed)

    if(different == False):
        raise HTTPException(status_code=400, detail="No changes made")

    # Generate commit ID (e.g., numbered folder)
    existing_commits = sorted(repo_path.glob("*"))
    commit_id = f"{len(existing_commits)+1:03d}_{commit_message.replace(' ', '_')[:20]}"
    commit_path = repo_path / commit_id
    commit_path.mkdir()

    # Save files
    for file in files:
        file_path = commit_path / file.filename
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    # Save metadata
    metadata = {
        "message": commit_message,
        "timestamp": datetime.utcnow().isoformat(),
        "files": [file.filename for file in files]
    }
    with (commit_path / "metadata.json").open("w") as meta_file:
        json.dump(metadata, meta_file, indent=2)

    return {"message": "Commit created", "commit_id": commit_id}
