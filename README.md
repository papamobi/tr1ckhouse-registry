# tr1ckhouse-registry

Central HTTPS registry for the [tr1ckhouse_roster](https://github.com/papamobi/tr1ckhouse-minqlx-plugins/tree/main/tr1ckhouse_roster)
minqlx plugin. Receives per-server roster snapshots and serves them to a
[discord-gamestatus](https://github.com/papamobi/discord-gamestatus/tree/tr1ckhouse) bot instance.

Runs as a small FastAPI process behind a reverse proxy, with in-memory
storage and TTL-based cleanup.

## Endpoints

- `POST /roster` — plugin publishes a snapshot (auth via `X-Tr1ckhouse-Key` header)
- `GET /rosters` — bot fetches all live rosters (same header)
- `GET /health` — unauthenticated liveness check

## Install

```bash
git clone https://github.com/papamobi/tr1ckhouse-registry
cd tr1ckhouse-registry
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
export TR1CKHOUSE_API_KEY="pick-a-long-random-string"
python tr1ckhouse_registry.py
```

Environment variables:

| Var | Default | Description |
|---|---|---|
| `TR1CKHOUSE_API_KEY` | *(required)* | Shared secret for both POST and GET |
| `TR1CKHOUSE_TTL_SEC` | `180` | Seconds a snapshot lives without refresh |
| `TR1CKHOUSE_BIND_HOST` | `127.0.0.1` | Bind host |
| `TR1CKHOUSE_BIND_PORT` | `8766` | Bind port |

## Production setup

Bind to localhost, expose via reverse proxy (Apache/nginx/Caddy) with TLS.
See `example/` for a working Apache vhost config and supervisord entry.

## License

GPL-3.0
