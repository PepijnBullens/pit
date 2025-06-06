# 🕳️ Pit – A Minimal Git-like CLI Tool

Pit is a simple version control client that lets you create, commit, clone, and pull repositories, similar to Git — but lightweight and backend-powered via FastAPI.

## 📦 Features

- Create repositories remotely
- Commit changes to the server
- Clone repositories to your machine
- Pull updates from the server
- Detects if you’re inside a valid `pit` repo

---

## ⚠️ Requirements

- python 3.7+
- pip 25.1+

---

## 🚀 Global installation

### Windows

- Execute pit-setup.exe

### MacOS

```bash
git clone https://github.com/PepijnBullens/pit.git
cd pit
```

```bash
pip install setuptools
pip install .
```

---

## <details>

<summary>🚀 Local installation</summary>

```bash
git clone https://github.com/PepijnBullens/pit.git
cd pit
```

### Client

```bash
pip install setuptools
pip install .
```

Now you can call 'pit' anywhere in your terminal to execute commands

### Server

```bash
cd server
python -m venv .venv
pip install fastapi uvicorn pydantic python-multipart typing-extensions
source .venv/bin/activate
uvicorn main:app --reload
```

Now you're running a virtual environment for the serverside of this project.
Make sure the serverside is running on `http://127.0.0.1:8000`. If not change it in `/pit/cli.py`

---

</details>
