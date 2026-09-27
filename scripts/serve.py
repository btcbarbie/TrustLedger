"""Production entry point (used by Railway via the Procfile).
Creates the database on first start, loads the SYNTHETIC demo groups only if it is empty, then serves on $PORT."""
import os

import uvicorn

from app import config, db


def main():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()
    with db.tx() as conn:
        empty = conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 0
    if empty:
        from scripts import seed
        seed.main()  # only ever runs on an empty database, so real data is never overwritten
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
