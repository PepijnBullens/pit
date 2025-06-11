from fastapi import FastAPI, HTTPException, Form, File, UploadFile, Request, Depends, Query
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from pathlib import Path
import shutil
import json
from datetime import datetime
import hashlib
import zipfile
import asyncpg
import os
from dotenv import load_dotenv

app = FastAPI()

load_dotenv()
STORAGE_DIR = Path("storage")
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set in .env file")

# --- Database helpers ---

async def get_db_pool(request: Request):
    return request.app.state.pool

async def init_db(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DATABASE_URL)
    pool = app.state.pool
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            UNIQUE(name, owner_id)
        );
        """)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db(app)
    yield
    await app.state.pool.close()

app = FastAPI(lifespan=lifespan)

async def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

async def verify_user(username: str, password: str, pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT password_hash FROM users WHERE username=$1", username)
        if not row:
            return False
        return row["password_hash"] == await hash_password(password)

async def get_user_id(username: str, pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE username=$1", username)
        if not row:
            return None
        return row["id"]

async def repo_exists(username: str, repo_name: str, pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT repos.id FROM repos
            JOIN users ON repos.owner_id = users.id
            WHERE users.username=$1 AND repos.name=$2
        """, username, repo_name)
        return row is not None

async def user_owns_repo(username: str, repo_name: str, pool):
    return await repo_exists(username, repo_name, pool)

async def create_repo_db(username: str, repo_name: str, pool):
    async with pool.acquire() as conn:
        user_id = await get_user_id(username, pool)
        if user_id is None:
            return False
        try:
            await conn.execute("INSERT INTO repos (name, owner_id) VALUES ($1, $2)", repo_name, user_id)
        except asyncpg.UniqueViolationError:
            return False
    return True

async def list_user_repos(username: str, pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT name FROM repos
            JOIN users ON repos.owner_id = users.id
            WHERE users.username=$1
        """, username)
        return [row["name"] for row in rows]

# --- Models ---

class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class RepoCreateRequest(BaseModel):
    username: str
    password: str
    repo_name: str

# --- User endpoints ---

@app.post("/register")
async def register(payload: RegisterRequest, request: Request):
    pool = await get_db_pool(request)
    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE username=$1", payload.username)
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        pw_hash = await hash_password(payload.password)
        await conn.execute("INSERT INTO users (username, password_hash) VALUES ($1, $2)", payload.username, pw_hash)
    return {"message": "User registered"}

@app.post("/login")
async def login(payload: LoginRequest, request: Request):
    pool = await get_db_pool(request)
    if await verify_user(payload.username, payload.password, pool):
        return {"message": "Login successful"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

# --- Repo endpoints ---

@app.post("/repos/create")
async def create_repo(payload: RepoCreateRequest, request: Request):
    pool = await get_db_pool(request)
    if not await verify_user(payload.username, payload.password, pool):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if await repo_exists(payload.username, payload.repo_name, pool):
        raise HTTPException(status_code=400, detail="Repository already exists")
    if not await create_repo_db(payload.username, payload.repo_name, pool):
        raise HTTPException(status_code=500, detail="Could not create repo in database")
    user_dir = STORAGE_DIR / payload.username
    repo_dir = user_dir / payload.repo_name / "commits"
    try:
        repo_dir.mkdir(parents=True, exist_ok=False)
        initial_commit = repo_dir / "000_initial"
        initial_commit.mkdir()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "Repository created successfully", "path": str(repo_dir)}

@app.get("/repos/{username}/{repo_name}/clone")
async def clone_repo(username: str, repo_name: str, password: str = Query(...), request: Request = None):
    pool = await get_db_pool(request)
    if not await verify_user(username, password, pool):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not await user_owns_repo(username, repo_name, pool):
        raise HTTPException(status_code=403, detail="Not allowed")
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
        for file in latest_commit.rglob("*"):
            if file.is_file() and file.name != "metadata.json":
                arcname = file.relative_to(latest_commit)
                zipf.write(file, arcname=arcname)
        pit_info = {"username": username, "repo_name": repo_name}
        pit_path = latest_commit / ".pit"
        with open(pit_path, "w") as f:
            json.dump(pit_info, f)
        zipf.write(pit_path, arcname=".pit")
        pit_path.unlink()
    return FileResponse(zip_path, filename=f"{repo_name}.zip")

@app.get("/repos/{username}/{repo_name}/pull")
async def pull_repo(username: str, repo_name: str, password: str = Query(...), commit_id: str = Query(None), request: Request = None):
    pool = await get_db_pool(request)
    if not await verify_user(username, password, pool):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not await user_owns_repo(username, repo_name, pool):
        raise HTTPException(status_code=403, detail="Not allowed")
    repo_path = STORAGE_DIR / username / repo_name / "commits"
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")
    commit_dirs = sorted([d for d in repo_path.iterdir() if d.is_dir()])
    if not commit_dirs:
        raise HTTPException(status_code=404, detail="No commits to pull")
    if commit_id:
        commit_dir = repo_path / commit_id
        if not commit_dir.exists() or not commit_dir.is_dir():
            raise HTTPException(status_code=404, detail="Commit not found")
        target_commit = commit_dir
    else:
        target_commit = commit_dirs[-1]
    zip_buffer = Path("temp") / f"{username}_{repo_name}_pull.zip"
    zip_buffer.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_buffer, 'w') as zipf:
        for file in target_commit.rglob("*"):
            if file.is_file() and file.name != "metadata.json":
                arcname = file.relative_to(target_commit)
                zipf.write(file, arcname=arcname)
    return FileResponse(zip_buffer, filename=f"{repo_name}.zip")

@app.get("/repos/{username}/list")
async def list_repos(username: str, password: str = Query(...), request: Request = None):
    pool = await get_db_pool(request)
    if not await verify_user(username, password, pool):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    repos = await list_user_repos(username, pool)
    return {"repositories": repos}

@app.post("/repos/{username}/{repo_name}/commit")
async def commit_files(
    username: str,
    repo_name: str,
    password: str = Form(...),
    commit_message: str = Form(...),
    files: list[UploadFile] = File(...),
    request: Request = None
):
    pool = await get_db_pool(request)
    if not await verify_user(username, password, pool):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not await user_owns_repo(username, repo_name, pool):
        raise HTTPException(status_code=403, detail="Not allowed")
    FILE_SIZE_CAP = 100 * 1024 * 1024  # 100 MB
    repo_path = STORAGE_DIR / username / repo_name / "commits"
    if not repo_path.exists():
        raise HTTPException(status_code=404, detail="Repository not found")
    for file in files:
        file.file.seek(0, 2)
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
        file_path.parent.mkdir(parents=True, exist_ok=True)
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
