"""
Membaca data produksi padi menjadi DataFrame rapi dengan kolom: tanggal (datetime), ton (float).

Format yang didukung:
  1. Excel mentah dari pabrik: beberapa blok tabel berdampingan dengan header
     "No | Bulan | Ton | Produksi Hari Sebelumnya | Rata-rata 7 Hari" dan judul "... Tahun 2024".
  2. CSV / Excel rapi dengan kolom "tanggal" dan "ton".

Jalankan langsung untuk mengonversi file mentah ke CSV:
  python data_import.py "data/raw/data_mentahan_2024.xlsx" data/produksi_padi_2024.csv
"""
import re
import sys

import pandas as pd

BULAN = ['januari', 'februari', 'maret', 'april', 'mei', 'juni', 'juli',
         'agustus', 'september', 'oktober', 'november', 'desember']


def _cell(value):
    return str(value).strip().lower() if pd.notna(value) else ''


def _find_year(raw):
    for value in raw.values.ravel():
        match = re.search(r'tahun\s+(\d{4})', _cell(value))
        if match:
            return int(match.group(1))
    return None


def parse_raw_excel(raw, year=None):
    """Ubah sheet Excel mentah (dibaca dengan header=None) menjadi deret harian."""
    year = year or _find_year(raw)
    if not year:
        raise ValueError('Tahun data tidak ditemukan. Pastikan judul memuat "Tahun YYYY".')

    # Setiap sel berisi "No" yang diikuti "Bulan" dan "Ton" adalah awal sebuah blok tabel
    blocks = []
    for (row, col), value in raw.stack().items():
        if _cell(value) == 'no' and col + 2 < raw.shape[1] \
                and _cell(raw.iat[row, col + 1]) == 'bulan' and _cell(raw.iat[row, col + 2]) == 'ton':
            blocks.append((row, col))
    if not blocks:
        raise ValueError('Header "No | Bulan | Ton" tidak ditemukan pada file.')

    # Header bisa berulang ke bawah pada kolom yang sama; sebuah blok berakhir di header berikutnya
    records = []
    for header_row, col in blocks:
        next_headers = [r for r, c in blocks if c == col and r > header_row]
        end_row = min(next_headers, default=raw.shape[0])
        for row in range(header_row + 1, end_row):
            day, month, ton = raw.iat[row, col], _cell(raw.iat[row, col + 1]), raw.iat[row, col + 2]
            if month not in BULAN:
                continue  # baris kosong atau header yang berulang
            records.append({
                'tanggal': pd.Timestamp(year=year, month=BULAN.index(month) + 1, day=int(day)),
                'ton': float(ton),
            })
    return _finalize(pd.DataFrame(records))


def parse_tidy(df):
    """Baca tabel rapi dengan kolom tanggal & ton (nama kolom tidak peka huruf besar/kecil)."""
    cols = {c.strip().lower(): c for c in df.columns.astype(str)}
    if 'tanggal' not in cols or 'ton' not in cols:
        raise ValueError('Kolom "tanggal" dan "ton" wajib ada.')
    out = pd.DataFrame({
        'tanggal': pd.to_datetime(df[cols['tanggal']], dayfirst=False),
        'ton': pd.to_numeric(df[cols['ton']], errors='coerce'),
    })
    return _finalize(out.dropna())


def _finalize(df):
    if df.empty:
        raise ValueError('Tidak ada data produksi yang terbaca.')
    dup = df['tanggal'].duplicated()
    if dup.any():
        dates = df.loc[dup, 'tanggal'].dt.strftime('%Y-%m-%d').tolist()
        raise ValueError(f"Terdapat {len(dates)} tanggal ganda, mis. {', '.join(dates[:5])}")
    return df.sort_values('tanggal').reset_index(drop=True)


def read_file(path_or_buffer, filename):
    """Deteksi format berdasarkan ekstensi dan isi file."""
    name = filename.lower()
    if name.endswith('.csv'):
        return parse_tidy(pd.read_csv(path_or_buffer))
    if name.endswith(('.xlsx', '.xls')):
        raw = pd.read_excel(path_or_buffer, header=None)
        header = [_cell(v) for v in raw.iloc[0]]
        if 'tanggal' in header and 'ton' in header:
            raw.columns = raw.iloc[0]
            return parse_tidy(raw.iloc[1:])
        return parse_raw_excel(raw)
    raise ValueError('Format file harus .xlsx, .xls, atau .csv')


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    data = read_file(src, src)
    data.to_csv(dst, index=False, date_format='%Y-%m-%d')
    print(f'{len(data)} baris ({data.tanggal.min():%Y-%m-%d} s.d. {data.tanggal.max():%Y-%m-%d}) -> {dst}')
