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

if not API_KEY:
    raise SystemExit("TR1CKHOUSE_API_KEY env var is required")

app = FastAPI(title="tr1ckhouse-registry")

# In-memory store: { "ip:port": {"snapshot": <dict>, "expires_at": <float>} }
_store: dict = {}
_lock = Lock()


def _now() -> float:
    return time.time()


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
    if x_tr1ckhouse_key != API_KEY:
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        snapshot = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    # Determine identity: the client tells us its public net_ip and net_port.
    # For servers behind NAT where the reported net_ip may be internal, we
    # fall back to the source IP from the connection.
    net_port = snapshot.get("net_port")
    net_ip = snapshot.get("net_ip") or (request.client.host if request.client else None)

    if not net_ip or not net_port:
        raise HTTPException(status_code=400, detail="missing net_ip or net_port")

    key = f"{net_ip}:{net_port}"

    with _lock:
        _store[key] = {"snapshot": snapshot, "expires_at": _now() + TTL_SEC}

    return {"ok": True, "key": key}


@app.get("/rosters")
def get_rosters(x_tr1ckhouse_key: str = Header(None)):
    if x_tr1ckhouse_key != API_KEY:
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
    uvicorn.run(app, host=BIND_HOST, port=BIND_PORT, log_level="info")