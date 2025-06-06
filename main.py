from fastapi import FastAPI, HTTPException, Form, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
import shutil
import json
from datetime import datetime
import hashlib
import zipfile

app = FastAPI()

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
        for file in latest_commit.iterdir():
            if file.is_file() and file.name != "metadata.json":
                zipf.write(file, arcname=file.name)

        # Add .pit file to mark repo folder
        pit_info = {"username": username, "repo_name": repo_name}
        pit_path = latest_commit / ".pit"
        with open(pit_path, "w") as f:
            json.dump(pit_info, f)
        zipf.write(pit_path, arcname=".pit")
        pit_path.unlink()

    return FileResponse(zip_path, filename=f"{repo_name}.zip")

@app.get("/repos/{username}/{repo_name}/pull")
async def pull_repo(username: str, repo_name: str):
    repo_path = STORAGE_DIR / username / repo_name / "commits"
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")

    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()])
    if not commit_dirs:
        raise HTTPException(status_code=404, detail="No commits to pull")

    latest_commit = commit_dirs[-1]

    zip_buffer = Path("temp") / f"{username}_{repo_name}_pull.zip"
    zip_buffer.parent.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_buffer, 'w') as zipf:
        for file in latest_commit.iterdir():
            if file.is_file() and file.name != "metadata.json":
                zipf.write(file, arcname=file.name)

    return FileResponse(zip_buffer, filename=f"{repo_name}.zip")

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
