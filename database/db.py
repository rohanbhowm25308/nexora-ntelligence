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
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    return conn


def init_db():
    conn = get_connection()
    conn.execute(SCHEMA)
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
