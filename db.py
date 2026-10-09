"""Akses database SQLite (file tunggal, tanpa server)."""
import os
import sqlite3

import pandas as pd
from flask import current_app, g
from werkzeug.security import generate_password_hash

PERAN = ('admin', 'user')

SCHEMA = """
CREATE TABLE IF NOT EXISTS pengguna (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    nama          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    peran         TEXT NOT NULL DEFAULT 'user' CHECK (peran IN ('admin', 'user'))
);

CREATE TABLE IF NOT EXISTS data_produksi (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tanggal TEXT NOT NULL UNIQUE,   -- YYYY-MM-DD
    ton     REAL NOT NULL CHECK (ton >= 0)
);

CREATE TABLE IF NOT EXISTS peramalan (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    dibuat_pada    TEXT NOT NULL,
    mode_parameter TEXT NOT NULL,   -- 'otomatis' / 'manual'
    window_length  INTEGER NOT NULL,
    grup_r         INTEGER NOT NULL,
    rasio_latih    REAL NOT NULL,
    horizon        INTEGER NOT NULL,
    n_data         INTEGER NOT NULL,
    n_latih        INTEGER NOT NULL,
    n_uji          INTEGER NOT NULL,
    tanggal_awal   TEXT NOT NULL,
    tanggal_akhir  TEXT NOT NULL,
    mae            REAL NOT NULL,
    mse            REAL NOT NULL,
    rmse           REAL NOT NULL,
    mape           REAL NOT NULL,
    kriteria       TEXT NOT NULL,
    total_ramalan  REAL NOT NULL,
    detail_json    TEXT NOT NULL,   -- nilai singular, komponen, rekonstruksi, tabel pencarian L
    dijalankan_oleh TEXT            -- nama pengguna yang menjalankan proses
);

CREATE TABLE IF NOT EXISTS hasil_ramalan (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    peramalan_id INTEGER NOT NULL REFERENCES peramalan(id) ON DELETE CASCADE,
    tanggal      TEXT NOT NULL,
    jenis        TEXT NOT NULL,     -- 'uji' (dibandingkan dengan aktual) / 'ramalan' (periode mendatang)
    aktual       REAL,
    nilai        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hasil_peramalan ON hasil_ramalan(peramalan_id, jenis);
"""


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


def close_db(_exc=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _migrate(conn):
    """Sesuaikan database versi lama (tabel `admin`, peramalan tanpa kolom pelaksana)."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if 'admin' in tables:
        conn.execute("INSERT OR IGNORE INTO pengguna (id, username, nama, password_hash, peran) "
                     "SELECT id, username, nama, password_hash, 'admin' FROM admin")
        conn.execute('DROP TABLE admin')
    kolom = {r[1] for r in conn.execute('PRAGMA table_info(peramalan)')}
    if 'dijalankan_oleh' not in kolom:
        conn.execute('ALTER TABLE peramalan ADD COLUMN dijalankan_oleh TEXT')


def init_db(app, seed_csv=None):
    """Buat tabel, akun admin bawaan, dan isi data awal jika tabel produksi masih kosong."""
    os.makedirs(os.path.dirname(app.config['DATABASE']), exist_ok=True)
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        if not conn.execute("SELECT 1 FROM pengguna WHERE peran = 'admin' LIMIT 1").fetchone():
            conn.execute('INSERT INTO pengguna (username, nama, password_hash, peran) VALUES (?, ?, ?, ?)',
                         ('admin', 'Administrator', generate_password_hash('admin123'), 'admin'))
        if seed_csv and os.path.exists(seed_csv) \
                and not conn.execute('SELECT 1 FROM data_produksi LIMIT 1').fetchone():
            seed = pd.read_csv(seed_csv)
            conn.executemany('INSERT INTO data_produksi (tanggal, ton) VALUES (?, ?)',
                             seed[['tanggal', 'ton']].itertuples(index=False, name=None))


def load_series():
    """Seluruh data produksi terurut tanggal sebagai DataFrame (tanggal datetime, ton float)."""
    rows = get_db().execute('SELECT tanggal, ton FROM data_produksi ORDER BY tanggal').fetchall()
    df = pd.DataFrame([dict(r) for r in rows], columns=['tanggal', 'ton'])
    df['tanggal'] = pd.to_datetime(df['tanggal'])
    return df
