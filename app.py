import json
import os
import sqlite3
from datetime import datetime
from functools import wraps

import numpy as np
import pandas as pd
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import ssa
from data_import import read_file
from db import PERAN, close_db, get_db, init_db, load_series

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'ssa-produksi-padi-dev-key'),
    DATABASE=os.path.join(BASE_DIR, 'instance', 'ssa_padi.db'),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
app.teardown_appcontext(close_db)
init_db(app, seed_csv=os.path.join(BASE_DIR, 'data', 'produksi_padi_2024.csv'))

RESEARCH = {
    'judul': 'Peramalan Tingkat Produksi Padi di Pabrik KP. Putra Yusima Desa Masjid '
             'Kecamatan Meurah Mulia Kabupaten Aceh Utara Menggunakan Metode '
             'Singular Spectrum Analysis (SSA)',
    'lokasi': 'Pabrik KP. Putra Yusima, Desa Masjid, Kec. Meurah Mulia, Kab. Aceh Utara',
    'metode': 'Singular Spectrum Analysis (SSA)',
}

NAMA_BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
              'Agustus', 'September', 'Oktober', 'November', 'Desember']

DEFAULT_PARAMS = {'mode': 'otomatis', 'L': 30, 'r': 2, 'rasio': 80, 'horizon': 365}
MIN_DATA = 30


@app.before_request
def load_current_user():
    """Ambil ulang akun dari database setiap request, supaya akun yang dihapus/diubah perannya langsung berlaku."""
    g.user = None
    if 'user_id' in session:
        g.user = get_db().execute('SELECT id, username, nama, peran FROM pengguna WHERE id = ?',
                                  (session['user_id'],)).fetchone()
        if g.user is None:
            session.clear()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.user is None:
            flash('Silakan login terlebih dahulu', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if g.user['peran'] != 'admin':
            flash('Fitur tersebut hanya dapat digunakan oleh admin', 'warning')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    return {'research': RESEARCH, 'current_year': datetime.now().year,
            'current_user': g.get('user'), 'is_admin': bool(g.get('user')) and g.user['peran'] == 'admin'}


@app.template_filter('angka')
def format_angka(value, digits=2):
    """Format angka gaya Indonesia: 1.234,56"""
    if value is None:
        return '-'
    text = f'{value:,.{digits}f}'
    return text.replace(',', '#').replace('.', ',').replace('#', '.')


@app.template_filter('tgl')
def format_tanggal(value):
    d = pd.Timestamp(value)
    return f'{d.day} {NAMA_BULAN[d.month - 1]} {d.year}'


def series_problems(df):
    """Masalah pada data yang membuat SSA tidak bisa dijalankan (SSA butuh deret harian tanpa celah)."""
    if len(df) < MIN_DATA:
        return f'Data produksi minimal {MIN_DATA} hari, saat ini {len(df)} hari.'
    gaps = df['tanggal'].diff().dt.days.iloc[1:]
    missing = int((gaps - 1).clip(lower=0).sum())
    if missing:
        first = df['tanggal'].iloc[gaps[gaps > 1].index[0] - 1] + pd.Timedelta(days=1)
        return (f'Terdapat {missing} hari yang tidak memiliki data (mulai {format_tanggal(first)}). '
                'Lengkapi data harian terlebih dahulu.')
    return None


def recap(dates, values, freq):
    """Rekap total & rata-rata per bulan ('M') atau per kuartal ('Q')."""
    # np.asarray: Series pandas dengan indeks lain akan di-reindex menjadi NaN jika dipakai langsung
    s = pd.Series(np.asarray(values, dtype=float), index=pd.DatetimeIndex(dates))
    period = s.index.to_period(freq)
    rows = []
    for p, chunk in s.groupby(period):
        label = f'{NAMA_BULAN[p.month - 1]} {p.year}' if freq == 'M' else f'Kuartal {p.quarter} {p.year}'
        full_days = p.days_in_month if freq == 'M' else (p.end_time.normalize() - p.start_time).days + 1
        rows.append({'periode': label, 'hari': len(chunk), 'penuh': len(chunk) == full_days,
                     'total': float(chunk.sum()), 'rata': float(chunk.mean())})
    return rows


def _round(arr, digits=4):
    return [round(float(v), digits) for v in arr]


# ---------------------------------------------------------------------------
# Autentikasi
# ---------------------------------------------------------------------------
def series_summary(df):
    """Statistik ringkas dan data grafik deret produksi (dipakai beranda & dashboard)."""
    stats = {
        'n': len(df), 'awal': df['tanggal'].min(), 'akhir': df['tanggal'].max(),
        'total': df['ton'].sum(), 'rata': df['ton'].mean(),
        'min': df['ton'].min(), 'max': df['ton'].max(),
    }
    bulanan = recap(df['tanggal'], df['ton'], 'M')
    chart = {
        'tanggal': df['tanggal'].dt.strftime('%Y-%m-%d').tolist(),
        'ton': df['ton'].tolist(),
        'bulan_label': [b['periode'] for b in bulanan],
        'bulan_total': [round(b['total'], 2) for b in bulanan],
    }
    return stats, chart


# ---------------------------------------------------------------------------
# Beranda (publik)
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    df = load_series()
    stats = chart = matriks = None
    if not df.empty:
        stats, chart = series_summary(df)
        # Contoh embedding dari data asli: 8 hari pertama, L = 4, K = 5
        contoh = df.head(8)
        if len(contoh) == 8:
            x = contoh['ton'].tolist()
            matriks = {
                'L': 4, 'K': 5,
                'tanggal': [format_tanggal(t) for t in contoh['tanggal']],
                'deret': x,
                'baris': [[x[i + j] for j in range(5)] for i in range(4)],
            }

    latest = get_db().execute('SELECT * FROM peramalan ORDER BY id DESC LIMIT 1').fetchone()
    ramalan = None
    if latest:
        rows = get_db().execute(
            "SELECT tanggal, nilai FROM hasil_ramalan WHERE peramalan_id = ? AND jenis = 'ramalan' ORDER BY tanggal",
            (latest['id'],)).fetchall()
        ramalan = {'tanggal': [r['tanggal'] for r in rows], 'nilai': _round([r['nilai'] for r in rows], 2),
                   'awal': rows[0]['tanggal'] if rows else None, 'akhir': rows[-1]['tanggal'] if rows else None}

    return render_template('home/index.html', stats=stats, chart=chart, matriks=matriks,
                           latest=latest, ramalan=ramalan, logged_in=g.user is not None)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        akun = get_db().execute('SELECT * FROM pengguna WHERE username = ?', (username,)).fetchone()
        if akun and check_password_hash(akun['password_hash'], request.form.get('password', '')):
            session.clear()
            session['user_id'] = akun['id']
            return redirect(url_for('dashboard'))
        flash('Username atau password salah', 'danger')
    return render_template('auth/login.html')


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Anda telah logout', 'info')
    return redirect(url_for('login'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route('/dashboard')
@login_required
def dashboard():
    df = load_series()
    stats, chart = series_summary(df) if not df.empty else (None, None)
    latest = get_db().execute('SELECT * FROM peramalan ORDER BY id DESC LIMIT 1').fetchone()
    return render_template('dashboard/index.html', stats=stats, chart=chart, latest=latest,
                           problem=series_problems(df) if not df.empty else None)


# ---------------------------------------------------------------------------
# Kelola data produksi
# ---------------------------------------------------------------------------
def _parse_form_row(form):
    try:
        tanggal = pd.Timestamp(form['tanggal']).strftime('%Y-%m-%d')
        ton = float(form['ton'].replace(',', '.'))
    except (KeyError, ValueError):
        raise ValueError('Tanggal dan produksi (ton) wajib diisi dengan format yang benar')
    if ton < 0:
        raise ValueError('Produksi tidak boleh bernilai negatif')
    return tanggal, ton


@app.route('/data')
@login_required
def data_produksi():
    rows = get_db().execute('SELECT * FROM data_produksi ORDER BY tanggal').fetchall()
    df = load_series()
    return render_template('data/index.html', rows=rows,
                           problem=series_problems(df) if not df.empty else None)


@app.route('/data/tambah', methods=['POST'])
@admin_required
def data_tambah():
    try:
        tanggal, ton = _parse_form_row(request.form)
        get_db().execute('INSERT INTO data_produksi (tanggal, ton) VALUES (?, ?)', (tanggal, ton))
        get_db().commit()
        flash(f'Data {format_tanggal(tanggal)} berhasil ditambahkan', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except sqlite3.IntegrityError:
        flash('Data untuk tanggal tersebut sudah ada, gunakan tombol ubah', 'danger')
    return redirect(url_for('data_produksi'))


@app.route('/data/<int:row_id>/ubah', methods=['POST'])
@admin_required
def data_ubah(row_id):
    try:
        tanggal, ton = _parse_form_row(request.form)
        get_db().execute('UPDATE data_produksi SET tanggal = ?, ton = ? WHERE id = ?', (tanggal, ton, row_id))
        get_db().commit()
        flash(f'Data {format_tanggal(tanggal)} berhasil diubah', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except sqlite3.IntegrityError:
        flash('Tanggal tersebut sudah dipakai data lain', 'danger')
    return redirect(url_for('data_produksi'))


@app.route('/data/<int:row_id>/hapus', methods=['POST'])
@admin_required
def data_hapus(row_id):
    get_db().execute('DELETE FROM data_produksi WHERE id = ?', (row_id,))
    get_db().commit()
    flash('Data berhasil dihapus', 'success')
    return redirect(url_for('data_produksi'))


@app.route('/data/import', methods=['POST'])
@admin_required
def data_import():
    upload = request.files.get('file')
    if not upload or not upload.filename:
        flash('Pilih file terlebih dahulu', 'warning')
        return redirect(url_for('data_produksi'))
    try:
        df = read_file(upload.stream, upload.filename)
    except Exception as e:
        flash(f'File gagal dibaca: {e}', 'danger')
        return redirect(url_for('data_produksi'))

    db = get_db()
    if request.form.get('mode') == 'ganti':
        db.execute('DELETE FROM data_produksi')
    db.executemany(
        'INSERT INTO data_produksi (tanggal, ton) VALUES (?, ?) '
        'ON CONFLICT(tanggal) DO UPDATE SET ton = excluded.ton',
        [(t.strftime('%Y-%m-%d'), float(v)) for t, v in zip(df['tanggal'], df['ton'])])
    db.commit()
    flash(f'{len(df)} data berhasil diimport '
          f'({format_tanggal(df.tanggal.min())} s.d. {format_tanggal(df.tanggal.max())})', 'success')
    return redirect(url_for('data_produksi'))


# ---------------------------------------------------------------------------
# Proses peramalan SSA
# ---------------------------------------------------------------------------
def _read_params(form):
    p = {
        'mode': form.get('mode', 'otomatis'),
        'L': form.get('L', type=int), 'r': form.get('r', type=int),
        'rasio': form.get('rasio', type=int), 'horizon': form.get('horizon', type=int),
    }
    if p['mode'] not in ('otomatis', 'manual'):
        raise ValueError('Mode parameter tidak dikenal')
    if not p['rasio'] or not 50 <= p['rasio'] <= 95:
        raise ValueError('Rasio data latih harus di antara 50% dan 95%')
    if not p['horizon'] or not 1 <= p['horizon'] <= 730:
        raise ValueError('Periode peramalan harus di antara 1 dan 730 hari')
    if p['mode'] == 'manual' and (not p['L'] or not p['r']):
        raise ValueError('Isi nilai L dan r untuk mode manual')
    return p


@app.route('/peramalan', methods=['GET', 'POST'])
@login_required
def peramalan():
    df = load_series()
    problem = series_problems(df) if not df.empty else 'Belum ada data produksi.'
    params = dict(DEFAULT_PARAMS)

    if request.method == 'POST' and not problem:
        try:
            params = _read_params(request.form)
            run_id = run_forecast(df, params)
            flash('Proses peramalan selesai dan hasil telah disimpan', 'success')
            return redirect(url_for('peramalan_detail', run_id=run_id))
        except ValueError as e:
            flash(str(e), 'danger')
            params = {**DEFAULT_PARAMS, **{k: v for k, v in request.form.items() if v}}

    n_latih = int(round(len(df) * int(params['rasio']) / 100)) if len(df) else 0
    return render_template('peramalan/form.html', params=params, problem=problem,
                           n_data=len(df), n_latih=n_latih)


def run_forecast(df, p):
    x = df['ton'].to_numpy()
    ratio = p['rasio'] / 100
    n_train = int(round(len(x) * ratio))
    if n_train < 2 * 3 or len(x) - n_train < 1:
        raise ValueError('Data latih atau data uji terlalu sedikit untuk rasio tersebut')

    grid = None
    if p['mode'] == 'otomatis':
        L, r, grid = ssa.search_parameters(x, ratio)
    else:
        L, r = p['L'], p['r']
        if not 2 <= L <= n_train // 2:
            raise ValueError(f'L harus di antara 2 dan {n_train // 2} (setengah jumlah data latih)')
        if not 1 <= r < L:
            raise ValueError(f'r harus di antara 1 dan {L - 1} (L - 1)')

    ev = ssa.evaluate(x, L, r, ratio)
    model = ssa.forecast(x, L, r, p['horizon'])
    if not np.all(np.isfinite(model['forecast'])) or not np.isfinite(ev['mape']):
        raise ValueError('Hasil peramalan tidak stabil untuk L dan r ini, coba nilai lain')

    dates = df['tanggal']
    test_dates = dates.iloc[ev['n_train']:]
    future_dates = pd.date_range(dates.iloc[-1] + pd.Timedelta(days=1), periods=p['horizon'], freq='D')
    n_show = len(model['components'])
    detail = {
        'K': model['K'], 'nu2': model['nu2'],
        'fit_metrics': ev['fit_metrics'],
        'nilai_singular': _round(model['s'][:n_show]),
        'kontribusi': _round(model['contribution'][:n_show]),
        'tanggal': dates.dt.strftime('%Y-%m-%d').tolist(),
        'aktual': _round(x),
        'rekonstruksi': _round(model['signal']),
        'tren': _round(model['trend']),
        'musiman': _round(model['seasonal']),
        'noise': _round(model['noise']),
        'komponen': [_round(c) for c in model['components'][:6]],
        'pencarian': grid,
    }

    db = get_db()
    cur = db.execute(
        '''INSERT INTO peramalan (dibuat_pada, mode_parameter, window_length, grup_r, rasio_latih, horizon,
               n_data, n_latih, n_uji, tanggal_awal, tanggal_akhir, mae, mse, rmse, mape, kriteria,
               total_ramalan, detail_json, dijalankan_oleh)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), p['mode'], L, r, ratio, p['horizon'],
         len(x), ev['n_train'], ev['n_test'],
         dates.iloc[0].strftime('%Y-%m-%d'), dates.iloc[-1].strftime('%Y-%m-%d'),
         ev['mae'], ev['mse'], ev['rmse'], ev['mape'], ssa.mape_criteria(ev['mape']),
         float(model['forecast'].sum()), json.dumps(detail), g.user['nama']))
    run_id = cur.lastrowid
    rows = [(run_id, d.strftime('%Y-%m-%d'), 'uji', float(a), float(v))
            for d, a, v in zip(test_dates, x[ev['n_train']:], ev['test_pred'])]
    rows += [(run_id, d.strftime('%Y-%m-%d'), 'ramalan', None, float(v))
             for d, v in zip(future_dates, model['forecast'])]
    db.executemany('INSERT INTO hasil_ramalan (peramalan_id, tanggal, jenis, aktual, nilai) VALUES (?, ?, ?, ?, ?)',
                   rows)
    db.commit()
    return run_id


@app.route('/peramalan/riwayat')
@login_required
def peramalan_riwayat():
    runs = get_db().execute('SELECT * FROM peramalan ORDER BY id DESC').fetchall()
    return render_template('peramalan/riwayat.html', runs=runs)


@app.route('/peramalan/<int:run_id>')
@login_required
def peramalan_detail(run_id):
    db = get_db()
    run = db.execute('SELECT * FROM peramalan WHERE id = ?', (run_id,)).fetchone()
    if not run:
        flash('Hasil peramalan tidak ditemukan', 'warning')
        return redirect(url_for('peramalan_riwayat'))
    detail = json.loads(run['detail_json'])
    hasil = db.execute('SELECT * FROM hasil_ramalan WHERE peramalan_id = ? ORDER BY tanggal',
                       (run_id,)).fetchall()
    uji = [dict(h) for h in hasil if h['jenis'] == 'uji']
    for h in uji:
        h['ape'] = abs(h['aktual'] - h['nilai']) / h['aktual'] * 100
    ramalan = [dict(h) for h in hasil if h['jenis'] == 'ramalan']
    f_dates = [h['tanggal'] for h in ramalan]
    f_values = [h['nilai'] for h in ramalan]
    return render_template(
        'peramalan/detail.html', run=run, detail=detail, uji=uji, ramalan=ramalan,
        rekap_bulan=recap(f_dates, f_values, 'M'), rekap_kuartal=recap(f_dates, f_values, 'Q'),
        chart={
            'uji_tanggal': [h['tanggal'] for h in uji],
            'uji_aktual': [h['aktual'] for h in uji],
            'uji_prediksi': _round([h['nilai'] for h in uji], 2),
            'ramalan_tanggal': f_dates,
            'ramalan_nilai': _round(f_values, 2),
        })


@app.route('/peramalan/<int:run_id>/hapus', methods=['POST'])
@admin_required
def peramalan_hapus(run_id):
    get_db().execute('DELETE FROM peramalan WHERE id = ?', (run_id,))
    get_db().commit()
    flash('Riwayat peramalan berhasil dihapus', 'success')
    return redirect(url_for('peramalan_riwayat'))


# ---------------------------------------------------------------------------
# Pengguna
# ---------------------------------------------------------------------------
MIN_PASSWORD = 6


def _validate_password(pw, konfirmasi):
    if len(pw) < MIN_PASSWORD:
        raise ValueError(f'Password minimal {MIN_PASSWORD} karakter')
    if pw != konfirmasi:
        raise ValueError('Konfirmasi password tidak sama')


def _jumlah_admin():
    return get_db().execute("SELECT COUNT(*) FROM pengguna WHERE peran = 'admin'").fetchone()[0]


@app.route('/pengguna')
@admin_required
def pengguna():
    akun = get_db().execute('SELECT id, username, nama, peran FROM pengguna ORDER BY peran, nama').fetchall()
    return render_template('pengguna/index.html', akun=akun, peran_list=PERAN, min_password=MIN_PASSWORD)


@app.route('/pengguna/tambah', methods=['POST'])
@admin_required
def pengguna_tambah():
    f = request.form
    username, nama, peran = f.get('username', '').strip().lower(), f.get('nama', '').strip(), f.get('peran', 'user')
    try:
        if not username or not nama:
            raise ValueError('Username dan nama wajib diisi')
        if not username.replace('_', '').replace('.', '').isalnum():
            raise ValueError('Username hanya boleh berisi huruf, angka, titik, dan garis bawah')
        if peran not in PERAN:
            raise ValueError('Peran tidak dikenal')
        _validate_password(f.get('password', ''), f.get('konfirmasi', ''))
        get_db().execute('INSERT INTO pengguna (username, nama, password_hash, peran) VALUES (?, ?, ?, ?)',
                         (username, nama, generate_password_hash(f['password']), peran))
        get_db().commit()
        flash(f'Akun {username} ({peran}) berhasil dibuat', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    except sqlite3.IntegrityError:
        flash(f'Username {username} sudah dipakai', 'danger')
    return redirect(url_for('pengguna'))


@app.route('/pengguna/<int:akun_id>/ubah', methods=['POST'])
@admin_required
def pengguna_ubah(akun_id):
    f = request.form
    akun = get_db().execute('SELECT * FROM pengguna WHERE id = ?', (akun_id,)).fetchone()
    if not akun:
        flash('Akun tidak ditemukan', 'warning')
        return redirect(url_for('pengguna'))
    nama, peran, pw = f.get('nama', '').strip(), f.get('peran', akun['peran']), f.get('password', '')
    try:
        if not nama:
            raise ValueError('Nama wajib diisi')
        if peran not in PERAN:
            raise ValueError('Peran tidak dikenal')
        if akun['peran'] == 'admin' and peran != 'admin':
            if akun_id == g.user['id']:
                raise ValueError('Anda tidak dapat menurunkan peran akun sendiri')
            if _jumlah_admin() <= 1:
                raise ValueError('Harus ada minimal satu admin')
        get_db().execute('UPDATE pengguna SET nama = ?, peran = ? WHERE id = ?', (nama, peran, akun_id))
        if pw:
            _validate_password(pw, f.get('konfirmasi', ''))
            get_db().execute('UPDATE pengguna SET password_hash = ? WHERE id = ?',
                             (generate_password_hash(pw), akun_id))
        get_db().commit()
        flash(f'Akun {akun["username"]} berhasil diperbarui' + (' (password direset)' if pw else ''), 'success')
    except ValueError as e:
        get_db().rollback()
        flash(str(e), 'danger')
    return redirect(url_for('pengguna'))


@app.route('/pengguna/<int:akun_id>/hapus', methods=['POST'])
@admin_required
def pengguna_hapus(akun_id):
    akun = get_db().execute('SELECT * FROM pengguna WHERE id = ?', (akun_id,)).fetchone()
    if not akun:
        flash('Akun tidak ditemukan', 'warning')
    elif akun_id == g.user['id']:
        flash('Anda tidak dapat menghapus akun sendiri', 'danger')
    elif akun['peran'] == 'admin' and _jumlah_admin() <= 1:
        flash('Harus ada minimal satu admin', 'danger')
    else:
        get_db().execute('DELETE FROM pengguna WHERE id = ?', (akun_id,))
        get_db().commit()
        flash(f'Akun {akun["username"]} berhasil dihapus', 'success')
    return redirect(url_for('pengguna'))


@app.route('/akun', methods=['GET', 'POST'])
@login_required
def akun_saya():
    if request.method == 'POST':
        f = request.form
        row = get_db().execute('SELECT password_hash FROM pengguna WHERE id = ?', (g.user['id'],)).fetchone()
        try:
            if not check_password_hash(row['password_hash'], f.get('password_lama', '')):
                raise ValueError('Password lama salah')
            _validate_password(f.get('password', ''), f.get('konfirmasi', ''))
            get_db().execute('UPDATE pengguna SET password_hash = ? WHERE id = ?',
                             (generate_password_hash(f['password']), g.user['id']))
            get_db().commit()
            flash('Password berhasil diganti', 'success')
            return redirect(url_for('akun_saya'))
        except ValueError as e:
            flash(str(e), 'danger')
    return render_template('pengguna/akun.html', min_password=MIN_PASSWORD)


# ---------------------------------------------------------------------------
# Lain-lain
# ---------------------------------------------------------------------------
@app.route('/tentang')
@login_required
def tentang():
    return render_template('tentang/index.html')


@app.errorhandler(404)
def not_found(_error):
    return render_template('errors/404.html'), 404


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', host='127.0.0.1', port=5000)
