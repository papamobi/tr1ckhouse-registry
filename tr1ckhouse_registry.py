"""
tr1ckhouse roster registry — central endpoint for the tr1ckhouse_roster
minqlx plugin. Receives per-server snapshots via HTTPS POST from any number
of QL servers, stores them keyed by "ip:port" in memory with a TTL, and
serves the aggregated view to the discord-gamestatus bot.

No Redis, no persistence, no per-VPS aggregators. One process on one machine.

Config via environment variables:
    TR1CKHOUSE_API_KEY      Shared secret for both POST and GET (required)
    TR1CKHOUSE_TTL_SEC      How long a snapshot lives without being refreshed
                            (default: 180)
    TR1CKHOUSE_BIND_HOST    Host to bind (default: 127.0.0.1)
    TR1CKHOUSE_BIND_PORT    Port to bind (default: 8766)
"""

import hmac
import os
import time
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn


API_KEY = os.environ.get("TR1CKHOUSE_API_KEY")
TTL_SEC = int(os.environ.get("TR1CKHOUSE_TTL_SEC", "180"))
BIND_HOST = os.environ.get("TR1CKHOUSE_BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("TR1CKHOUSE_BIND_PORT", "8766"))
# A roster snapshot is a few KB; anything far larger is a bug or abuse.
MAX_BODY_BYTES = 64 * 1024

if not API_KEY:
    raise SystemExit("TR1CKHOUSE_API_KEY env var is required")

app = FastAPI(title="tr1ckhouse-registry")

# In-memory store: { "ip:port": {"snapshot": <dict>, "expires_at": <float>} }
_store: dict = {}
_lock = Lock()


def _now() -> float:
    return time.time()


def _authorized(key) -> bool:
    # Constant-time compare so the key can't be guessed byte by byte from timing.
    return key is not None and hmac.compare_digest(key.encode(), API_KEY.encode())


def _prune_expired():
    """Called on read paths — cheap enough at low key count to skip a background sweeper."""
    now = _now()
    with _lock:
        expired = [k for k, v in _store.items() if v["expires_at"] < now]
        for k in expired:
            del _store[k]


@app.post("/roster")
async def post_roster(
    request: Request,
    x_tr1ckhouse_key: str = Header(None),
):
    if not _authorized(x_tr1ckhouse_key):
        raise HTTPException(status_code=401, detail="unauthorized")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="snapshot too large")
    try:
        snapshot = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=400, detail="snapshot must be an object")

    # Determine identity: the client tells us its public net_ip and net_port.
    # For servers behind NAT where the reported net_ip may be internal, we
    # fall back to the source IP from the connection.
    net_port = snapshot.get("net_port")
    net_ip = snapshot.get("net_ip") or (request.client.host if request.client else None)

    try:
        net_port = int(net_port)
    except (TypeError, ValueError):
        net_port = 0
    if not net_ip or not 0 < net_port < 65536:
        raise HTTPException(status_code=400, detail="missing or invalid net_ip/net_port")

    key = f"{net_ip}:{net_port}"

    with _lock:
        _store[key] = {"snapshot": snapshot, "expires_at": _now() + TTL_SEC}

    return {"ok": True, "key": key}


@app.get("/rosters")
def get_rosters(x_tr1ckhouse_key: str = Header(None)):
    if not _authorized(x_tr1ckhouse_key):
        raise HTTPException(status_code=401, detail="unauthorized")

    _prune_expired()

    with _lock:
        rosters = {k: v["snapshot"] for k, v in _store.items()}

    return JSONResponse({
        "generated_at": int(_now()),
        "count": len(rosters),
        "rosters": rosters,
    })


@app.get("/health")
def health():
    """Liveness check — no auth, no state. For monitors and Apache upstream health."""
    return {"status": "ok"}


if __name__ == "__main__":
    # Behind Apache, request.client.host is 127.0.0.1. Trust X-Forwarded-For from
    # the local proxy only, so the NAT fallback above sees the real server IP.
    uvicorn.run(app, host=BIND_HOST, port=BIND_PORT, log_level="info",
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")