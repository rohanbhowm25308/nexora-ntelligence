"""
SQLite database layer for the BI & Sales Analytics System.
Handles schema creation, loading a cleaned DataFrame into the `orders`
table, and running the SQL analytics queries used by the dashboard.
"""

import sqlite3
import os
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "sales.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT,
    order_date TEXT,
    customer_id TEXT,
    customer_name TEXT,
    region TEXT,
    product_id TEXT,
    product_name TEXT,
    category TEXT,
    quantity INTEGER,
    unit_price REAL,
    discount_pct REAL,
    revenue REAL,
    cost REAL,
    profit REAL,
    payment_method TEXT,
    order_status TEXT
);

CREATE TABLE IF NOT EXISTS dataset_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    is_demo INTEGER NOT NULL,
    source_filename TEXT
);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def load_dataframe(df: pd.DataFrame, replace: bool = True):
    """Load a cleaned DataFrame into the orders table. Chunked insert keeps
    large uploads (tens of thousands of rows) fast and memory-friendly
    instead of one giant single-transaction insert."""
    init_db()
    conn = get_connection()
    try:
        df.to_sql(
            "orders", conn,
            if_exists="replace" if replace else "append",
            index=False,
            chunksize=2000,
            method="multi",
        )
        conn.commit()
    finally:
        conn.close()


def run_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_connection()
    try:
        result = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    return result


def has_data() -> bool:
    if not os.path.exists(DB_PATH):
        return False
    conn = get_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM orders")
        count = cur.fetchone()[0]
    except sqlite3.OperationalError:
        count = 0
    conn.close()
    return count > 0


def set_dataset_meta(is_demo: bool, source_filename: str):
    """Record which dataset is currently loaded, so a worker restart (a
    crash, a timeout, or Render's free-tier idle-sleep waking back up)
    can tell the difference between 'nothing uploaded yet' and 'the
    person's real data is sitting right here in the orders table' instead
    of always defaulting back to the bundled demo dataset."""
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO dataset_meta (id, is_demo, source_filename) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET is_demo=excluded.is_demo, source_filename=excluded.source_filename",
            (1 if is_demo else 0, source_filename),
        )
        conn.commit()
    finally:
        conn.close()


def get_dataset_meta():
    """Returns {"is_demo": bool, "source_filename": str} or None if no
    dataset has ever been loaded into this database file."""
    if not os.path.exists(DB_PATH):
        return None
    conn = get_connection()
    try:
        cur = conn.execute("SELECT is_demo, source_filename FROM dataset_meta WHERE id = 1")
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if row is None:
        return None
    return {"is_demo": bool(row[0]), "source_filename": row[1]}


def load_orders_table() -> pd.DataFrame:
    """Read the persisted orders table back into a DataFrame, with
    order_date parsed back to a real datetime (to_sql stores it as text)."""
    df = run_query("SELECT * FROM orders")
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    return df