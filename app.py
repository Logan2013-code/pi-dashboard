import os
import json
import subprocess
import shutil
import zipfile
import tempfile
import secrets
import hashlib
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

BASE_DIR = Path(__file__).parent
BOTS_DIR = Path.home() / "bots"
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
SERVICE_PREFIX = "pidash-"
HELPER = "/usr/local/bin/pidash-helper"

BOTS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)


# ── Config ──────────────────────────────────────────────────────────────

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"bots": {}, "password_hash": ""}


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


# ── Auth ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        config = load_config()
        if not config.get("password_hash"):
            return f(*args, **kwargs)          # no password set yet
        if not session.get("authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Niet ingelogd"}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET"])
def login_page():
    config = load_config()
    if not config.get("password_hash"):
        return redirect(url_for("setup_page"))
    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_submit():
    config = load_config()
    data = request.json or {}
    pw = data.get("password", "")
    if hash_password(pw) == config.get("password_hash"):
        session["authenticated"] = True
        session.permanent = True
        return jsonify({"status": "ok"})
    return jsonify({"error": "Verkeerd wachtwoord"}), 403


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


@app.route("/setup", methods=["GET"])
def setup_page():
    config = load_config()
    if config.get("password_hash"):
        return redirect(url_for("login_page"))
    return render_template("setup.html")


@app.route("/setup", methods=["POST"])
def setup_submit():
    config = load_config()
    if config.get("password_hash"):
        return jsonify({"error": "Wachtwoord is al ingesteld"}), 400
    data = request.json or {}
    pw = data.get("password", "").strip()
    if len(pw) < 4:
        return jsonify({"error": "Wachtwoord moet minimaal 4 tekens zijn"}), 400
    config["password_hash"] = hash_password(pw)
    save_config(config)
    session["authenticated"] = True
    session.permanent = True
    return jsonify({"status": "ok"})


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    config = load_config()
    data = request.json or {}
    old = data.get("old_password", "")
    new = data.get("new_password", "").strip()
    if config.get("password_hash") and hash_password(old) != config["password_hash"]:
        return jsonify({"error": "Huidig wachtwoord klopt niet"}), 403
    if len(new) < 4:
        return jsonify({"error": "Nieuw wachtwoord moet minimaal 4 tekens zijn"}), 400
    config["password_hash"] = hash_password(new)
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/tunnel-url")
@login_required
def tunnel_url():
    """Return the current cloudflared tunnel URL if running."""
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "pidash-tunnel"],
            capture_output=True, text=True, timeout=5
        )
        active = r.stdout.strip() == "active"
    except Exception:
        active = False

    url = ""
    url_file = DATA_DIR / "tunnel_url.txt"
    if url_file.exists():
        url = url_file.read_text().strip()

    return jsonify({"active": active, "url": url})


# ── Helpers ─────────────────────────────────────────────────────────────

def run_helper(*args):
    try:
        r = subprocess.run(
            ["sudo", HELPER, *args],
            capture_output=True, text=True, timeout=30
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"


def get_service_status(bot_name):
    code, out, _ = run_helper("status", bot_name)
    status = out.strip() if out.strip() else "inactive"
    # systemctl is-active returns the real status on stdout regardless of exit code
    if status in ("active", "inactive", "activating", "deactivating", "failed"):
        return status
    return "inactive"


def resolve_command(command):
    """Resolve the executable in a command to its absolute path for systemd."""
    if not command or command.startswith("/"):
        return command
    parts = command.split(None, 1)
    executable = parts[0]
    # Already absolute
    if executable.startswith("/"):
        return command
    # Look up on the system
    full_path = shutil.which(executable)
    if full_path:
        parts[0] = full_path
        return " ".join(parts)
    # Common fallbacks for Pi
    common = {
        "python3": "/usr/bin/python3",
        "python": "/usr/bin/python3",
        "node": "/usr/bin/node",
        "npm": "/usr/bin/npm",
    }
    if executable in common:
        parts[0] = common[executable]
        return " ".join(parts)
    return command


def detect_start_command(bot_dir):
    pkg = bot_dir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            if "start" in data.get("scripts", {}):
                return "/usr/bin/npm start"
            main = data.get("main", "index.js")
            return f"/usr/bin/node {main}"
        except json.JSONDecodeError:
            pass

    for name in ["bot.py", "main.py", "app.py", "run.py"]:
        if (bot_dir / name).exists():
            return f"/usr/bin/python3 {name}"

    procfile = bot_dir / "Procfile"
    if procfile.exists():
        for line in procfile.read_text().splitlines():
            if ":" in line:
                return resolve_command(line.split(":", 1)[1].strip())

    return ""


def build_service_file(bot_name, bot_config):
    bot_dir = BOTS_DIR / bot_name
    command = bot_config["command"]

    # Ensure absolute path for systemd
    command = resolve_command(command)

    venv = bot_dir / "venv"
    if venv.exists() and "python" in command:
        py = str(venv / "bin" / "python3")
        command = command.replace("/usr/bin/python3 ", f"{py} ")
        command = command.replace("/usr/bin/python ", f"{py} ")
        command = command.replace("python3 ", f"{py} ")
        command = command.replace("python ", f"{py} ")

    env_lines = "\n".join(
        f"Environment={k}={v}" for k, v in bot_config.get("env", {}).items()
    )
    restart = "always" if bot_config.get("auto_restart", True) else "no"
    user = os.environ.get("USER", "pi")

    return f"""[Unit]
Description=PiDash: {bot_name}
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={bot_dir}
ExecStart={command}
Restart={restart}
RestartSec=10
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
{env_lines}

[Install]
WantedBy=multi-user.target
"""


def deploy_service(bot_name, bot_config):
    content = build_service_file(bot_name, bot_config)
    subprocess.run(
        ["sudo", HELPER, "write-service", bot_name],
        input=content, text=True, capture_output=True
    )
    run_helper("reload")
    if bot_config.get("auto_start", True):
        run_helper("enable", bot_name)


def install_deps(bot_dir):
    messages = []
    req = bot_dir / "requirements.txt"
    if req.exists():
        venv = bot_dir / "venv"
        if not venv.exists():
            subprocess.run(
                ["python3", "-m", "venv", str(venv)],
                capture_output=True, cwd=str(bot_dir)
            )
        r = subprocess.run(
            [str(venv / "bin" / "pip"), "install", "-r", "requirements.txt"],
            capture_output=True, text=True, cwd=str(bot_dir)
        )
        messages.append(f"pip install: {'ok' if r.returncode == 0 else r.stderr[-200:]}")

    pkg = bot_dir / "package.json"
    if pkg.exists():
        r = subprocess.run(
            ["npm", "install"],
            capture_output=True, text=True, cwd=str(bot_dir)
        )
        messages.append(f"npm install: {'ok' if r.returncode == 0 else r.stderr[-200:]}")

    return messages


# ── Routes ──────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/system")
@login_required
def system_info():
    import psutil
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        if "cpu_thermal" in temps:
            temp = temps["cpu_thermal"][0].current
    except Exception:
        pass
    return jsonify({
        "cpu": cpu,
        "mem_percent": mem.percent,
        "mem_used_gb": round(mem.used / 1e9, 1),
        "mem_total_gb": round(mem.total / 1e9, 1),
        "disk_percent": disk.percent,
        "disk_used_gb": round(disk.used / 1e9, 1),
        "disk_total_gb": round(disk.total / 1e9, 1),
        "temp": temp,
    })


@app.route("/api/bots")
@login_required
def list_bots():
    config = load_config()
    bots = []
    for name, bc in config.get("bots", {}).items():
        bots.append({
            "name": name,
            "status": get_service_status(name),
            "command": bc.get("command", ""),
            "description": bc.get("description", ""),
            "auto_restart": bc.get("auto_restart", True),
            "auto_start": bc.get("auto_start", True),
            "env": bc.get("env", {}),
            "git_url": bc.get("git_url", ""),
        })
    return jsonify(bots)


@app.route("/api/bots", methods=["POST"])
@login_required
def add_bot():
    data = request.json
    name = data.get("name", "").strip().lower()
    name = "".join(c if c.isalnum() or c == "-" else "-" for c in name).strip("-")

    if not name:
        return jsonify({"error": "Naam is verplicht"}), 400

    config = load_config()
    if name in config.get("bots", {}):
        return jsonify({"error": "Bot bestaat al"}), 409

    bot_dir = BOTS_DIR / name
    bot_dir.mkdir(parents=True, exist_ok=True)

    git_url = data.get("git_url", "").strip()
    if git_url:
        r = subprocess.run(
            ["git", "clone", git_url, "."],
            capture_output=True, text=True, cwd=str(bot_dir)
        )
        if r.returncode != 0:
            shutil.rmtree(bot_dir, ignore_errors=True)
            return jsonify({"error": f"Git clone mislukt: {r.stderr[-300:]}"}), 400

    command = data.get("command", "").strip()
    if not command:
        command = detect_start_command(bot_dir)
    command = resolve_command(command)

    if not command:
        return jsonify({"error": "Geen start commando gevonden. Vul er handmatig een in (bijv. /usr/bin/python3 bot.py)"}), 400

    dep_msgs = install_deps(bot_dir)

    bot_config = {
        "command": command,
        "description": data.get("description", ""),
        "env": data.get("env", {}),
        "auto_restart": data.get("auto_restart", True),
        "auto_start": data.get("auto_start", True),
        "git_url": git_url,
    }

    deploy_service(name, bot_config)
    config.setdefault("bots", {})[name] = bot_config
    save_config(config)

    return jsonify({"status": "ok", "name": name, "command": command, "deps": dep_msgs})


@app.route("/api/bots/upload", methods=["POST"])
@login_required
def upload_bot():
    name = request.form.get("name", "").strip().lower()
    name = "".join(c if c.isalnum() or c == "-" else "-" for c in name).strip("-")

    if not name:
        return jsonify({"error": "Naam is verplicht"}), 400

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Geen bestand geüpload"}), 400

    config = load_config()
    if name in config.get("bots", {}):
        return jsonify({"error": "Bot bestaat al"}), 409

    bot_dir = BOTS_DIR / name
    bot_dir.mkdir(parents=True, exist_ok=True)

    if f.filename.endswith(".zip"):
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            f.save(tmp.name)
            with zipfile.ZipFile(tmp.name) as zf:
                zf.extractall(bot_dir)
            os.unlink(tmp.name)

        subdirs = [d for d in bot_dir.iterdir() if d.is_dir()]
        if len(subdirs) == 1 and not any(bot_dir.glob("*.py")) and not any(bot_dir.glob("*.js")):
            for item in subdirs[0].iterdir():
                shutil.move(str(item), str(bot_dir))
            subdirs[0].rmdir()
    else:
        f.save(str(bot_dir / f.filename))

    command = request.form.get("command", "").strip() or detect_start_command(bot_dir)
    dep_msgs = install_deps(bot_dir)

    env = {}
    env_raw = request.form.get("env", "")
    for line in env_raw.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    bot_config = {
        "command": command,
        "description": request.form.get("description", ""),
        "env": env,
        "auto_restart": request.form.get("auto_restart", "true") == "true",
        "auto_start": request.form.get("auto_start", "true") == "true",
        "git_url": "",
    }

    deploy_service(name, bot_config)
    config.setdefault("bots", {})[name] = bot_config
    save_config(config)

    return jsonify({"status": "ok", "name": name, "command": command, "deps": dep_msgs})


@app.route("/api/bots/<name>", methods=["PUT"])
@login_required
def update_bot(name):
    config = load_config()
    if name not in config.get("bots", {}):
        return jsonify({"error": "Bot niet gevonden"}), 404

    data = request.json
    bc = config["bots"][name]

    for key in ("command", "description", "env", "auto_restart", "auto_start"):
        if key in data:
            bc[key] = data[key]

    deploy_service(name, bc)
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/bots/<name>", methods=["DELETE"])
@login_required
def delete_bot(name):
    config = load_config()
    if name not in config.get("bots", {}):
        return jsonify({"error": "Bot niet gevonden"}), 404

    run_helper("stop", name)
    run_helper("disable", name)
    run_helper("remove-service", name)
    run_helper("reload")

    bot_dir = BOTS_DIR / name
    if bot_dir.exists():
        shutil.rmtree(bot_dir)

    del config["bots"][name]
    save_config(config)
    return jsonify({"status": "ok"})


@app.route("/api/bots/<name>/<action>", methods=["POST"])
@login_required
def bot_action(name, action):
    if action not in ("start", "stop", "restart"):
        return jsonify({"error": "Ongeldige actie"}), 400

    code, out, err = run_helper(action, name)
    return jsonify({
        "status": "ok" if code == 0 else "error",
        "output": err or out,
    })


@app.route("/api/bots/<name>/logs")
@login_required
def bot_logs(name):
    lines = request.args.get("lines", "150")
    code, out, err = run_helper("logs", name, lines)
    return jsonify({"logs": out or err})


@app.route("/api/bots/<name>/pull", methods=["POST"])
@login_required
def bot_pull(name):
    bot_dir = BOTS_DIR / name
    if not (bot_dir / ".git").exists():
        return jsonify({"error": "Geen git repository"}), 400

    r = subprocess.run(
        ["git", "pull"], capture_output=True, text=True, cwd=str(bot_dir)
    )

    config = load_config()
    dep_msgs = install_deps(bot_dir)
    bc = config.get("bots", {}).get(name, {})
    if bc:
        deploy_service(name, bc)

    return jsonify({
        "status": "ok" if r.returncode == 0 else "error",
        "output": r.stdout + r.stderr,
        "deps": dep_msgs,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
