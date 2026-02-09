#!/usr/bin/env python3
import json
import os
import random
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
DEFAULT_DB_PATH = ROOT_DIR / "data" / "ubereats_agent.db"


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_db_path() -> Path:
    env_value = os.getenv("SQLITE_PATH", str(DEFAULT_DB_PATH))
    path = Path(env_value)
    if not path.is_absolute():
        path = (ROOT_DIR / path).resolve()
    return path


def db_connect() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS stores (
            store_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            store_url TEXT NOT NULL,
            group_order_url TEXT,
            deliverable INTEGER NOT NULL DEFAULT 1,
            last_checked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            name TEXT NOT NULL,
            price_twd INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'TWD',
            FOREIGN KEY (store_id) REFERENCES stores(store_id)
        );

        CREATE TABLE IF NOT EXISTS classifications (
            item_id TEXT PRIMARY KEY,
            is_afternoon_tea INTEGER NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('drink', 'food')),
            score REAL NOT NULL,
            reason TEXT,
            model TEXT,
            classified_at TEXT,
            FOREIGN KEY (item_id) REFERENCES items(item_id)
        );
        """
    )
    conn.commit()


def seed_demo_data(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS count FROM stores").fetchone()["count"]
    if existing > 0:
        return

    stores = [
        ("s1", "晨光咖啡", "https://www.ubereats.com/tw/store/s1", "https://www.ubereats.com/group-orders/s1", 1),
        ("s2", "甜點角落", "https://www.ubereats.com/tw/store/s2", "https://www.ubereats.com/group-orders/s2", 1),
        ("s3", "茶香小舖", "https://www.ubereats.com/tw/store/s3", "https://www.ubereats.com/group-orders/s3", 1),
        ("s4", "午茶工房", "https://www.ubereats.com/tw/store/s4", "https://www.ubereats.com/group-orders/s4", 1),
        ("s5", "果食餐盒", "https://www.ubereats.com/tw/store/s5", "https://www.ubereats.com/group-orders/s5", 1),
        ("s6", "慢烤點心", "https://www.ubereats.com/tw/store/s6", "https://www.ubereats.com/group-orders/s6", 1),
    ]

    items = [
        ("i1", "s1", "拿鐵", 120, "drink", 0.96),
        ("i2", "s2", "巴斯克乳酪蛋糕", 180, "food", 0.94),
        ("i3", "s3", "四季春茶", 75, "drink", 0.92),
        ("i4", "s4", "檸檬塔", 165, "food", 0.91),
        ("i5", "s5", "水果優格杯", 140, "food", 0.88),
        ("i6", "s6", "可可歐蕾", 130, "drink", 0.89),
        ("i7", "s1", "美式咖啡", 90, "drink", 0.90),
        ("i8", "s2", "伯爵紅茶", 110, "drink", 0.87),
        ("i9", "s3", "司康", 95, "food", 0.86),
        ("i10", "s4", "抹茶拿鐵", 150, "drink", 0.93),
        ("i11", "s5", "核桃布朗尼", 160, "food", 0.90),
        ("i12", "s6", "肉桂捲", 170, "food", 0.92),
    ]

    conn.executemany(
        """
        INSERT INTO stores (store_id, name, store_url, group_order_url, deliverable)
        VALUES (?, ?, ?, ?, ?)
        """,
        stores,
    )

    conn.executemany(
        """
        INSERT INTO items (item_id, store_id, name, price_twd)
        VALUES (?, ?, ?, ?)
        """,
        [(item_id, store_id, item_name, price) for item_id, store_id, item_name, price, _, _ in items],
    )

    conn.executemany(
        """
        INSERT INTO classifications (item_id, is_afternoon_tea, category, score, reason, model, classified_at)
        VALUES (?, 1, ?, ?, 'demo seed', 'demo-model', datetime('now'))
        """,
        [(item_id, category, score) for item_id, _, _, _, category, score in items],
    )
    conn.commit()


def fetch_candidates(conn: sqlite3.Connection, category: str, price_limit: int) -> dict:
    rows = conn.execute(
        """
        WITH eligible_stores AS (
            SELECT
                s.store_id,
                s.name AS store_name,
                s.store_url,
                COALESCE(s.group_order_url, s.store_url) AS group_order_url,
                AVG(i.price_twd) AS avg_item_price
            FROM stores s
            JOIN items i ON i.store_id = s.store_id
            WHERE s.deliverable = 1
            GROUP BY s.store_id
            HAVING AVG(i.price_twd) < ?
        )
        SELECT
            es.store_id,
            es.store_name,
            es.store_url,
            es.group_order_url,
            ROUND(es.avg_item_price, 2) AS avg_item_price,
            i.item_id,
            i.name AS item_name,
            i.price_twd,
            c.score,
            c.reason
        FROM eligible_stores es
        JOIN items i ON i.store_id = es.store_id
        JOIN classifications c ON c.item_id = i.item_id
        WHERE c.is_afternoon_tea = 1
          AND c.category = ?
        ORDER BY RANDOM()
        """,
        (price_limit, category),
    ).fetchall()

    grouped = {}
    for row in rows:
        store_id = row["store_id"]
        grouped.setdefault(store_id, []).append(dict(row))
    return grouped


def pick_items(drink_candidates: dict, food_candidates: dict) -> tuple:
    drink_store_ids = list(drink_candidates.keys())
    if len(drink_store_ids) < 2:
        return None, "INSUFFICIENT_DRINKS"

    selected_drink_stores = random.sample(drink_store_ids, 2)
    drinks = [random.choice(drink_candidates[store_id]) for store_id in selected_drink_stores]

    available_food_stores = [store_id for store_id in food_candidates if store_id not in selected_drink_stores]
    if len(available_food_stores) < 2:
        return None, "INSUFFICIENT_FOODS"

    selected_food_stores = random.sample(available_food_stores, 2)
    foods = [random.choice(food_candidates[store_id]) for store_id in selected_food_stores]

    return {"drinks": drinks, "foods": foods}, None


def build_copy_text(selection: dict) -> str:
    lines = []
    ordered_items = selection["drinks"] + selection["foods"]
    for entry in ordered_items:
        lines.append(f"{entry['store_name']}+{entry['group_order_url']}")
    return "\n".join(lines)


def random_selection_response() -> tuple:
    with db_connect() as conn:
        ensure_schema(conn)
        drink_candidates = fetch_candidates(conn, "drink", price_limit=200)
        food_candidates = fetch_candidates(conn, "food", price_limit=200)

    selection, error_code = pick_items(drink_candidates, food_candidates)
    if error_code:
        return (
            400,
            {
                "ok": False,
                "error": error_code,
                "message": "資料不足，無法組成 2 種飲料 + 2 種食物（且不同店家）。",
            },
        )

    copy_text = build_copy_text(selection)
    return (
        200,
        {
            "ok": True,
            "result": selection,
            "copy_text": copy_text,
        },
    )


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, filename: str, content_type: str) -> None:
        path = STATIC_DIR / filename
        if not path.exists():
            self.send_error(404, "Not Found")
            return
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_file("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_file("app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_file("styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/api/random-selection":
            status, payload = random_selection_response()
            self._json(status, payload)
            return
        self.send_error(404, "Not Found")


def main() -> None:
    load_dotenv(ROOT_DIR / ".env")

    with db_connect() as conn:
        ensure_schema(conn)
        if "--seed-demo" in sys.argv:
            seed_demo_data(conn)
            print("Demo data seeded into", get_db_path())
            return

    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8080"))

    server = HTTPServer((host, port), Handler)
    print(f"Server running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
