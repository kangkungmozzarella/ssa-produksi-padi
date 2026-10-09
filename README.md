# Peramalan Tingkat Produksi Padi dengan Singular Spectrum Analysis (SSA)

Sistem peramalan produksi padi harian di **Pabrik KP. Putra Yusima, Desa Masjid, Kecamatan Meurah Mulia, Kabupaten Aceh Utara** menggunakan metode **Singular Spectrum Analysis (SSA)**.

## Fitur
- Beranda publik (tanpa login): ringkasan penelitian, tahapan SSA, grafik data produksi, dan hasil peramalan terakhir.
- Login dengan dua peran. Password disimpan dalam bentuk hash.
  - **Admin**: semua fitur, termasuk tambah/ubah/hapus/import data produksi, hapus riwayat, dan Kelola Pengguna.
  - **User**: melihat dashboard, data, dan riwayat, serta menjalankan peramalan. Akun user dibuat oleh admin.
  - Setiap akun bisa mengganti password sendiri di menu Akun Saya (klik nama di pojok kanan atas).
- Kelola data produksi harian: tambah, ubah, hapus, dan import dari Excel/CSV.
- Proses peramalan SSA dengan parameter L dan r yang ditentukan otomatis (coba-coba, pilih MAPE terkecil) atau diisi manual.
- Hasil tersimpan di database dan bisa dibuka kembali dari halaman riwayat:
  - Nilai singular, komponen tren/musiman/noise, serta grafik data aktual vs rekonstruksi.
  - Evaluasi pada data uji: MAE, MSE, RMSE, MAPE, dan kriterianya.
  - Ramalan harian beserta rekap per bulan dan per kuartal.
  - Grafik MAPE untuk setiap nilai L (khusus mode otomatis).

## Metode
1. **Embedding**: deret sepanjang N dibentuk menjadi matriks lintasan L × K, dengan K = N − L + 1.
2. **SVD**: matriks lintasan dipecah menjadi nilai singular dan vektor singular.
3. **Grouping**: komponen 1 menjadi tren, komponen 2..r menjadi musiman, dan sisanya noise yang dibuang.
4. **Diagonal averaging**: matriks hasil grouping dikembalikan menjadi deret waktu.
5. **Recurrent SSA**: hasil rekonstruksi diproyeksikan ke periode berikutnya.

Data dibagi berurutan waktu menjadi data latih dan data uji (bawaan 80:20). Akurasi dihitung dari ramalan pada data uji. Setelah itu model dengan L dan r yang sama dilatih ulang pada seluruh data untuk meramal periode mendatang.

Kriteria MAPE: < 10% Sangat Baik, 10–20% Baik, 20–50% Layak, ≥ 50% Buruk.

## Struktur
```
app.py              Route Flask (login, dashboard, data, peramalan, tentang)
ssa.py              Algoritma SSA + metrik evaluasi (numpy)
db.py               Skema & koneksi SQLite
data_import.py      Pembaca Excel mentah pabrik / CSV rapi
analisis_ssa.ipynb  Notebook langkah-langkah SSA (untuk Bab 4)
data/
  raw/data_mentahan_2024.xlsx   Data mentah dari pabrik
  produksi_padi_2024.csv        Data hasil konversi (tanggal, ton), dipakai sebagai data awal
templates/          Halaman HTML (Jinja2); partials/ berisi potongan yang dipakai ulang
static/css/app.css  Tampilan aplikasi (di atas Bootstrap); public.css untuk beranda & login
static/js/app.js    Format angka, pengaturan grafik & DataTables, menu di layar kecil
instance/           Database SQLite (dibuat otomatis, tidak ikut repo)
```

## Menjalankan
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
Buka http://127.0.0.1:5000 untuk melihat beranda, lalu klik **Masuk admin** dan login dengan **admin** / **admin123**. Akun user dibuat dari menu **Kelola Pengguna**.

Saat pertama kali dijalankan, database `instance/ssa_padi.db` dibuat otomatis lalu diisi dari `data/produksi_padi_2024.csv`. Untuk mengulang dari awal, hapus folder `instance/`.

## Notebook analisis
`analisis_ssa.ipynb` menjalankan setiap tahap SSA secara berurutan (data, pembersihan, uji stasioneritas, penentuan L dan r, embedding, SVD, grouping, diagonal averaging, R-SSA, evaluasi, ramalan) dan menampilkan hasil antaranya beserta grafik interaktif (Plotly). Notebook ini memakai modul `ssa.py` yang sama dengan aplikasi, jadi angkanya sama dengan hasil mode otomatis.

Output sudah tersimpan di dalam file. Untuk menjalankan ulang:
```bash
pip install -r requirements-notebook.txt
```
Setelah itu buka notebook di VS Code atau Jupyter, pilih kernel dari `venv`, lalu jalankan **Run All**.

## Konversi data mentah
File Excel dari pabrik berisi beberapa blok tabel (`No | Bulan | Ton | …`) yang disusun berdampingan. Untuk mengubahnya menjadi CSV:
```bash
python data_import.py data/raw/data_mentahan_2024.xlsx data/produksi_padi_2024.csv
```
File Excel mentah juga bisa langsung diimport lewat menu **Data Produksi → Import File**.
