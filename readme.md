# 🕳️ Pit – A Minimal Git-like CLI Tool

Pit is a simple version control client that lets you create, commit, clone, and pull repositories, similar to Git — but lightweight and backend-powered via FastAPI.

<br />

## 📦 Features

- Create repositories remotely
- Commit changes locally
- Push changes to the server
- Clone repositories to your machine
- Pull updates from the server
- Detects if you’re inside a valid `pit` repo

---

<br />

## ⚠️ Requirements

- python 3.7+
- pip 25.1+

---

<br />

## 🚀 Global installation

```bash
# Clone the repository
git clone https://github.com/PepijnBullens/pit.git
cd pit

# Install all required dependencies and the Pit client
pip install -r requirements.txt
pip install .
```

After installation, you can use the `pit` command anywhere in your terminal.

---

<br />

<details>
<summary><h2>🚀 Local installation</h2></summary>

### Clone

```bash
git clone https://github.com/PepijnBullens/pit.git
cd pit
```

<br />

### Client

```bash
pip install -r requirements.txt
pip install .
```

Now you can call `pit` anywhere in your terminal to execute commands.

<br />

### Server

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic python-multipart typing-extensions
uvicorn main:app --reload
```

Now you're running a virtual environment for the serverside of this project.
Make sure the serverside is running on `http://127.0.0.1:8000`. If not, change it in `/pit/cli.py`.

</details>
