# Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
# Developed by: Richard R. Ayuyang, PhD
#               Professor II, CSU
# All rights reserved.

"""Backup & restore API — lists backups, triggers manual backup, restores, deletes."""

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import yaml

from container_names import SINKHOLE as SELF_CONTAINER

CONFIG_PATH = "/config/config.yml"
BACKUP_SCRIPT = "/usr/local/bin/sinkhole-backup.sh"
DATA_DIR = "/data"       # NAS-backed: updater status files only
LOCAL_DIR = "/local"     # SD-backed: sinkhole.db, blocklist.db, geoip-country.csv, config
DEFAULT_BACKUP_DIR = "/mnt/nas/richsinkhole-backups"
DOCKER_SOCK = "/var/run/docker.sock"


async def _docker_exec_as_root(cmd: list[str], timeout: float = 180) -> tuple[int, str]:
    """Run a command inside this container as root via the Docker API.

    Needed for operations that must run as root (mkdir under /mnt/nas, chown,
    etc.) because the dashboard itself runs as the unprivileged `app` user.
    Uses the host's docker socket (bind-mounted in docker-compose.yml) the
    same way unbound_settings._reload_unbound() does.
    """
    if not os.path.exists(DOCKER_SOCK):
        raise HTTPException(status_code=503, detail="Docker socket not available")
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCK)
    async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=timeout) as client:
        r = await client.post(
            f"/containers/{SELF_CONTAINER}/exec",
            json={"Cmd": cmd, "User": "root", "AttachStdout": True, "AttachStderr": True},
        )
        if r.status_code != 201:
            raise HTTPException(status_code=500, detail=f"docker exec create failed: {r.text}")
        exec_id = r.json()["Id"]
        r2 = await client.post(f"/exec/{exec_id}/start", json={"Detach": False},
                               headers={"Content-Type": "application/json"})
        raw = r2.content or b""
        # Docker multiplexes stdout/stderr using 8-byte frame headers:
        # [type(1), 0, 0, 0, size(4 big-endian)][payload]. Parse on raw bytes;
        # decoding to text before framing corrupts non-UTF-8 size bytes.
        chunks: list[bytes] = []
        i = 0
        while i + 8 <= len(raw):
            size = int.from_bytes(raw[i + 4:i + 8], "big")
            chunks.append(raw[i + 8:i + 8 + size])
            i += 8 + size
        text = (b"".join(chunks) if chunks else raw).decode("utf-8", errors="replace")
        inspect = await client.get(f"/exec/{exec_id}/json")
        exit_code = inspect.json().get("ExitCode", -1) if inspect.status_code == 200 else -1
        return exit_code, text


def _get_backup_root() -> str:
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("backup_dir", DEFAULT_BACKUP_DIR)
    except Exception:
        return DEFAULT_BACKUP_DIR

router = APIRouter()


@router.get("/backups")
async def list_backups():
    """List available backup folders sorted by date (newest first)."""
    if not os.path.isdir(_get_backup_root()):
        return {"backups": [], "backup_dir": _get_backup_root()}
    backups = []
    for entry in sorted(os.listdir(_get_backup_root()), reverse=True):
        path = os.path.join(_get_backup_root(), entry)
        if os.path.isdir(path) and entry[:4].isdigit():
            files = os.listdir(path)
            size_bytes = sum(os.path.getsize(os.path.join(path, f)) for f in files)
            backups.append({
                "date": entry,
                "files": files,
                "size_mb": round(size_bytes / 1024 / 1024, 1),
            })
    return {"backups": backups, "backup_dir": _get_backup_root()}


# ── Async backup job state ───────────────────────────────────────────────────
# A full backup can take 60-120s on a Pi + NFS (650 MB over ethernet), longer
# than nginx's proxy_read_timeout. We run the script in a background task and
# let the UI poll for completion via /api/backups/run/status.
_backup_job_lock = asyncio.Lock()
_backup_job_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "ok": None,
    "output": "",
}


async def _run_backup_background() -> None:
    """Background task: exec the backup script as root and stash the result."""
    global _backup_job_state
    try:
        exit_code, output = await _docker_exec_as_root([BACKUP_SCRIPT], timeout=600)
        _backup_job_state["ok"] = (exit_code == 0)
        _backup_job_state["output"] = output.strip()[:2000]
    except Exception as exc:
        _backup_job_state["ok"] = False
        _backup_job_state["output"] = f"backup failed: {exc}"
    finally:
        _backup_job_state["finished_at"] = time.time()
        _backup_job_state["running"] = False


@router.post("/backups/run", status_code=202)
async def trigger_backup():
    """Kick off a backup in the background and return immediately. The UI polls
    /api/backups/run/status to find out whether it succeeded."""
    if not os.path.isfile(BACKUP_SCRIPT):
        raise HTTPException(status_code=503, detail="Backup script not found")
    async with _backup_job_lock:
        if _backup_job_state["running"]:
            return {"status": "already_running", "started_at": _backup_job_state["started_at"]}
        _backup_job_state.update({
            "running": True,
            "started_at": time.time(),
            "finished_at": None,
            "ok": None,
            "output": "",
        })
        asyncio.create_task(_run_backup_background())
    return {"status": "started", "started_at": _backup_job_state["started_at"]}


@router.get("/backups/run/status")
async def backup_status():
    """Poll the most recent backup job. The UI calls this every few seconds
    after kicking off `/backups/run`."""
    return dict(_backup_job_state)


class RestoreIn(BaseModel):
    date: str  # e.g. "2026-04-03"


@router.post("/backups/restore")
async def restore_backup(body: RestoreIn):
    """Restore from a dated backup folder."""
    if ".." in body.date or "/" in body.date:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    backup_path = os.path.join(_get_backup_root(), body.date)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup {body.date} not found")

    restored = []
    # File → target dir mapping. All operational state lives on local SD;
    # NAS is only used for updater status files (not restored from backup).
    _restore_paths = {
        "sinkhole.db":        LOCAL_DIR,
        "blocklist.db":       LOCAL_DIR,
        "geoip-country.csv":  LOCAL_DIR,
        "config.yml":         os.path.join(LOCAL_DIR, "config"),
    }
    for filename, target_dir in _restore_paths.items():
        src = os.path.join(backup_path, filename)
        dst = os.path.join(target_dir, filename)
        if os.path.isfile(src):
            os.makedirs(target_dir, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(filename)

    return {"status": "restored", "date": body.date, "files": restored}


# ── Storage protocol constants ───────────────────────────────────────────────
_VALID_PROTOCOLS = ("local", "nfs", "smb", "rsync-ssh")
_SSH_KEY_PATH = "/local/config/backup_ssh_ed25519"
_SSH_KNOWN_HOSTS = "/local/config/backup_ssh_known_hosts"
_SAFE_PATH_PREFIXES = ("/mnt/", "/data/backups", "/backups")


@router.get("/backups/config")
async def get_backup_config():
    """Get backup configuration (no secrets)."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    return {
        "backup_protocol": cfg.get("backup_protocol", "nfs"),
        "backup_dir": cfg.get("backup_dir", DEFAULT_BACKUP_DIR),
        "backup_hour": cfg.get("backup_hour", 2),
        "backup_minute": cfg.get("backup_minute", 0),
        "backup_retention_days": cfg.get("backup_retention_days", 30),
        # nfs
        "backup_nfs_host": cfg.get("backup_nfs_host", ""),
        "backup_nfs_export": cfg.get("backup_nfs_export", ""),
        # smb
        "backup_smb_host": cfg.get("backup_smb_host", ""),
        "backup_smb_share": cfg.get("backup_smb_share", ""),
        "backup_smb_user": cfg.get("backup_smb_user", ""),
        # rsync-ssh
        "backup_ssh_host": cfg.get("backup_ssh_host", ""),
        "backup_ssh_user": cfg.get("backup_ssh_user", ""),
        "backup_ssh_port": cfg.get("backup_ssh_port", 22),
        "backup_ssh_path": cfg.get("backup_ssh_path", ""),
        "ssh_key_present": os.path.isfile(_SSH_KEY_PATH),
    }


class BackupConfigIn(BaseModel):
    backup_protocol: str = "nfs"
    backup_dir: str = ""
    backup_hour: int = 2
    backup_minute: int = 0
    backup_retention_days: int = 30
    # nfs
    backup_nfs_host: str = ""
    backup_nfs_export: str = ""
    # smb
    backup_smb_host: str = ""
    backup_smb_share: str = ""
    backup_smb_user: str = ""
    backup_smb_password: str = ""  # written to /local/config/smb-creds, never to YAML
    # rsync-ssh
    backup_ssh_host: str = ""
    backup_ssh_user: str = ""
    backup_ssh_port: int = 22
    backup_ssh_path: str = ""


@router.post("/backups/config")
async def save_backup_config(body: BackupConfigIn):
    """Save backup configuration. For NFS/SMB the actual mount setup is done
    by install.sh on the host (this endpoint can't mount/remount across the
    container boundary safely). For rsync-ssh everything is self-contained."""
    if body.backup_protocol not in _VALID_PROTOCOLS:
        raise HTTPException(status_code=400, detail=f"backup_protocol must be one of {_VALID_PROTOCOLS}")
    if not (0 <= body.backup_hour <= 23):
        raise HTTPException(status_code=400, detail="Hour must be 0-23")
    if not (0 <= body.backup_minute <= 59):
        raise HTTPException(status_code=400, detail="Minute must be 0-59")
    if not (1 <= body.backup_retention_days <= 365):
        raise HTTPException(status_code=400, detail="Retention must be 1-365 days")

    # Per-protocol validation.
    if body.backup_protocol in ("local", "nfs", "smb"):
        path = body.backup_dir.strip()
        if not path:
            raise HTTPException(status_code=400, detail="backup_dir is required for local/nfs/smb")
        resolved = os.path.realpath(path)
        if not any(resolved.startswith(p) for p in _SAFE_PATH_PREFIXES):
            raise HTTPException(status_code=400, detail=f"backup_dir must be under {' or '.join(_SAFE_PATH_PREFIXES)}")
    # NFS/SMB host/export/share are optional — if the user set up the mount
    # out-of-band (install.sh or manual fstab entry), they may only want to
    # adjust schedule/retention here and not re-enter the NAS details.
    # rsync-ssh fields ARE required because the script assembles the SSH cmd
    # from them; there's no out-of-band setup path.
    if body.backup_protocol == "rsync-ssh":
        for fld in ("backup_ssh_host", "backup_ssh_user", "backup_ssh_path"):
            if not getattr(body, fld):
                raise HTTPException(status_code=400, detail=f"rsync-ssh requires {fld}")
        if not (1 <= body.backup_ssh_port <= 65535):
            raise HTTPException(status_code=400, detail="backup_ssh_port must be 1-65535")

    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}

        cfg["backup_protocol"] = body.backup_protocol
        cfg["backup_hour"] = body.backup_hour
        cfg["backup_minute"] = body.backup_minute
        cfg["backup_retention_days"] = body.backup_retention_days

        if body.backup_protocol in ("local", "nfs", "smb"):
            cfg["backup_dir"] = body.backup_dir.strip()
        if body.backup_protocol == "nfs":
            cfg["backup_nfs_host"] = body.backup_nfs_host.strip()
            cfg["backup_nfs_export"] = body.backup_nfs_export.strip()
        if body.backup_protocol == "smb":
            cfg["backup_smb_host"] = body.backup_smb_host.strip()
            cfg["backup_smb_share"] = body.backup_smb_share.strip()
            cfg["backup_smb_user"] = body.backup_smb_user.strip()
            if body.backup_smb_password:
                _write_smb_creds(body.backup_smb_user, body.backup_smb_password)
        if body.backup_protocol == "rsync-ssh":
            cfg["backup_ssh_host"] = body.backup_ssh_host.strip()
            cfg["backup_ssh_user"] = body.backup_ssh_user.strip()
            cfg["backup_ssh_port"] = body.backup_ssh_port
            cfg["backup_ssh_path"] = body.backup_ssh_path.strip()

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

        _update_cron(body.backup_hour, body.backup_minute)
        # Only flag "remount needed" when the user actually changed NAS details
        # (non-empty NFS host/export or SMB host/share). Saving just schedule
        # or retention on an already-mounted share shouldn't scare the user.
        nfs_changed = body.backup_protocol == "nfs" and bool(body.backup_nfs_host and body.backup_nfs_export)
        smb_changed = body.backup_protocol == "smb" and bool(body.backup_smb_host and body.backup_smb_share)
        return {"status": "saved", "remount_required": nfs_changed or smb_changed}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save backup config: {exc}")


def _write_smb_creds(user: str, password: str) -> None:
    """Write CIFS credentials file in the format mount.cifs expects.
    Lives on /local so it's persisted on the SD card (not NAS), readable by
    root inside the container which is what cifs-utils needs."""
    path = "/local/config/smb-creds"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"username={user}\npassword={password}\n")
    os.chmod(path, 0o600)


@router.get("/backups/ssh-key")
async def get_ssh_pubkey():
    """Return the public SSH key the user must add to the remote ~/.ssh/authorized_keys."""
    pub = _SSH_KEY_PATH + ".pub"
    if not os.path.isfile(pub):
        return {"public_key": "", "exists": False}
    return {"public_key": open(pub).read().strip(), "exists": True}


@router.post("/backups/ssh-key/generate")
async def generate_ssh_key():
    """Generate a fresh ed25519 keypair for backup transport. No-op if a key
    already exists — won't silently break a working setup."""
    if os.path.isfile(_SSH_KEY_PATH):
        raise HTTPException(status_code=409, detail="SSH key already present — delete it first if you want to regenerate")
    os.makedirs(os.path.dirname(_SSH_KEY_PATH), exist_ok=True)
    result = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", _SSH_KEY_PATH, "-N", "", "-C", "richsinkhole-backup"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"ssh-keygen failed: {result.stderr.strip()}")
    os.chmod(_SSH_KEY_PATH, 0o600)
    return {"public_key": open(_SSH_KEY_PATH + ".pub").read().strip()}


class TestStorageIn(BaseModel):
    protocol: str
    # Shared
    path: str = ""           # local: directory; rsync-ssh: remote path
    # NFS
    nfs_host: str = ""
    nfs_export: str = ""
    # SMB
    smb_host: str = ""
    smb_share: str = ""
    smb_user: str = ""
    smb_password: str = ""
    # rsync-ssh
    host: str = ""
    user: str = ""
    port: int = 22


@router.post("/backups/test")
async def test_storage(body: TestStorageIn):
    """Probe that the target storage is actually reachable with the details
    the user just typed.

    Behaviour per protocol:
      local       — the path exists and is a directory
      nfs         — `showmount -e nfs_host` lists nfs_export; falls back to a
                    path check if nfs_host wasn't provided
      smb         — `smbclient -L //smb_host` succeeds and `ls` on the share
                    works with smb_user / smb_password (or saved creds file)
      rsync-ssh   — SSH in with the generated key and create+delete a probe
                    file under `path` on the remote host
    """
    if body.protocol not in _VALID_PROTOCOLS:
        raise HTTPException(status_code=400, detail=f"protocol must be one of {_VALID_PROTOCOLS}")

    if body.protocol == "local":
        target = body.path.strip()
        if not target:
            raise HTTPException(status_code=400, detail="path required")
        if not os.path.isdir(target):
            return {"ok": False, "detail": f"{target} is not a directory"}
        return {"ok": True, "detail": f"{target} exists and is a directory"}

    if body.protocol == "nfs":
        if body.nfs_host and body.nfs_export:
            try:
                result = subprocess.run(
                    ["showmount", "-e", "--no-headers", body.nfs_host],
                    capture_output=True, text=True, timeout=15,
                )
            except subprocess.TimeoutExpired:
                return {"ok": False, "detail": f"showmount timed out — {body.nfs_host} is unreachable or not running NFS"}
            except FileNotFoundError:
                return {"ok": False, "detail": "showmount not installed (rebuild sinkhole image)"}
            if result.returncode != 0:
                return {"ok": False, "detail": (result.stderr or "showmount failed — is the NFS server reachable?").strip()[:300]}
            exports = [line.split()[0] for line in result.stdout.splitlines() if line.strip()]
            # An NFS client can mount a subpath of an exported directory, so the
            # requested export is valid if it equals OR lives beneath any export.
            requested = body.nfs_export.rstrip("/") or "/"
            match = next((e for e in exports if requested == e.rstrip("/") or requested.startswith(e.rstrip("/") + "/")), None)
            if not match:
                return {"ok": False, "detail": f"server {body.nfs_host} does not export {body.nfs_export}. Available: {', '.join(exports) or '(none)'}"}
            note = "" if match.rstrip("/") == requested else f" (via parent export {match})"
            return {"ok": True, "detail": f"NFS server {body.nfs_host} reachable; {body.nfs_export} is exportable{note} — run install.sh to mount"}
        return _probe_existing_path(body.path.strip() or DEFAULT_BACKUP_DIR)

    if body.protocol == "smb":
        if body.smb_host and body.smb_share:
            # Password: use the one posted, OR fall back to the saved creds file
            # (so "change retention only, leave password blank" still tests).
            smb_password = body.smb_password
            if not smb_password and os.path.isfile("/local/config/smb-creds"):
                try:
                    for line in open("/local/config/smb-creds"):
                        if line.startswith("password="):
                            smb_password = line.partition("=")[2].rstrip("\n")
                            break
                except OSError:
                    pass
            auth = f"{body.smb_user}%{smb_password}" if body.smb_user else "-N"
            cmd = ["smbclient", f"//{body.smb_host}/{body.smb_share}",
                   "-U" if body.smb_user else "-N",
                   *([auth] if body.smb_user else []),
                   "-c", "ls"]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired:
                return {"ok": False, "detail": f"smbclient timed out — {body.smb_host} unreachable on SMB port"}
            except FileNotFoundError:
                return {"ok": False, "detail": "smbclient not installed (rebuild sinkhole image)"}
            if result.returncode != 0:
                return {"ok": False, "detail": (result.stderr or result.stdout or "smbclient failed").strip()[:300]}
            return {"ok": True, "detail": f"SMB share //{body.smb_host}/{body.smb_share} is reachable with these credentials — run install.sh to mount"}
        return _probe_existing_path(body.path.strip() or DEFAULT_BACKUP_DIR)

    if body.protocol == "rsync-ssh":
        if not os.path.isfile(_SSH_KEY_PATH):
            return {"ok": False, "detail": "SSH key not generated yet — click 'Generate Key' first"}
        if not (body.host and body.user and body.path):
            raise HTTPException(status_code=400, detail="host, user, and path are required")
        cmd = [
            "ssh", "-i", _SSH_KEY_PATH, "-p", str(body.port),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={_SSH_KNOWN_HOSTS}",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes",
            f"{body.user}@{body.host}",
            f"mkdir -p {body.path!r} && touch {body.path!r}/.sinkhole-probe && rm {body.path!r}/.sinkhole-probe && echo OK",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            return {"ok": False, "detail": f"ssh timed out — {body.host}:{body.port} unreachable"}
        if result.returncode != 0:
            return {"ok": False, "detail": (result.stderr or result.stdout or "ssh failed").strip()[:300]}
        return {"ok": True, "detail": f"connected to {body.user}@{body.host}:{body.path} and wrote a probe file"}

    return {"ok": False, "detail": "unsupported protocol"}


def _probe_existing_path(target: str) -> dict:
    """Fallback probe: verify the already-mounted path is reachable + writable
    when the user didn't provide server details (e.g. save-retention-only)."""
    if not target:
        return {"ok": False, "detail": "no path to probe"}
    if not os.path.isdir(target):
        return {"ok": False, "detail": f"{target} is not a directory (mount missing — re-run install.sh)"}
    probe = os.path.join(target, ".sinkhole-probe")
    try:
        with open(probe, "w") as f:
            f.write("ok")
        os.unlink(probe)
        return {"ok": True, "detail": f"existing mount at {target} is reachable and writable"}
    except OSError:
        pass
    try:
        os.listdir(target)
    except OSError as exc:
        return {"ok": False, "detail": f"{target} unreadable: {exc}"}
    return {"ok": True, "detail": f"existing mount at {target} is reachable (nightly backup runs as root and can write)"}


def _update_cron(hour: int, minute: int) -> None:
    """Update the backup cron schedule on the host.

    The cron entry must invoke the script INSIDE the sinkhole container
    (`docker exec -u root ...`) because the script's paths (/local, /data,
    /config, /mnt/nas/...) only resolve there. Running on the host directly
    silently produces 0-byte backups every night.
    """
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=5,
        )
        lines = [l for l in result.stdout.splitlines() if "sinkhole-backup" not in l]
        lines.append(
            f"{minute} {hour} * * * docker exec -u root {SELF_CONTAINER} "
            f"/usr/local/bin/sinkhole-backup.sh >> /var/log/sinkhole-backup.log 2>&1"
        )
        subprocess.run(
            ["crontab", "-"], input="\n".join(lines) + "\n",
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        pass  # cron update is best-effort from inside container


@router.delete("/backups/{date}")
async def delete_backup(date: str):
    """Delete a backup folder by date."""
    # Validate format to prevent path traversal (YYYY-MM-DD or YYYY-MM-DD_HH-MM)
    clean = date.replace("-", "").replace("_", "")
    if not clean.isdigit() or len(date) not in (10, 16) or ".." in date or "/" in date:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    backup_path = os.path.join(_get_backup_root(), date)
    if not os.path.isdir(backup_path):
        raise HTTPException(status_code=404, detail=f"Backup {date} not found")
    shutil.rmtree(backup_path)
    return {"status": "deleted", "date": date}
