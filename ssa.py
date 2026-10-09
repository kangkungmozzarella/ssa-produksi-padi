"""
Singular Spectrum Analysis (SSA) untuk peramalan deret waktu produksi padi.

Tahapan mengikuti metodologi penelitian:
  1. Dekomposisi   : embedding (matriks lintasan L x K) dan Singular Value Decomposition
  2. Rekonstruksi  : grouping (r komponen pertama = sinyal, sisanya noise) dan diagonal averaging
  3. Peramalan     : Recurrent SSA (R-SSA)
  4. Evaluasi      : MAE, MSE, RMSE, MAPE
"""
import numpy as np


# ---------------------------------------------------------------------------
# Tahap 1: Dekomposisi
# ---------------------------------------------------------------------------
def embedding(series, L):
    """Ubah deret 1 dimensi (panjang N) menjadi matriks lintasan (Hankel) berukuran L x K, K = N - L + 1."""
    x = np.asarray(series, dtype=float)
    N = len(x)
    if not 2 <= L <= N // 2:
        raise ValueError(f"Window length L harus di antara 2 dan N/2 ({N // 2}), didapat L={L}")
    K = N - L + 1
    return np.column_stack([x[j:j + L] for j in range(K)])


def svd(X):
    """SVD matriks lintasan: X = sum(s_i * U_i * V_i^T). Mengembalikan U, nilai singular s, dan V^T."""
    U, s, Vt = np.linalg.svd(X, full_matrices=False)
    return U, s, Vt


# ---------------------------------------------------------------------------
# Tahap 2: Rekonstruksi
# ---------------------------------------------------------------------------
def diagonal_averaging(Xi):
    """Hankelisasi: rata-rata setiap anti-diagonal matriks L x K menjadi deret sepanjang N = L + K - 1."""
    L, K = Xi.shape
    N = L + K - 1
    total = np.zeros(N)
    count = np.zeros(N)
    for i in range(L):
        total[i:i + K] += Xi[i]
        count[i:i + K] += 1
    return total / count


def elementary_components(U, s, Vt, n):
    """Deret hasil diagonal averaging untuk masing-masing n eigentriple pertama."""
    return [diagonal_averaging(s[i] * np.outer(U[:, i], Vt[i])) for i in range(n)]


def grouping(components, r, trend_count=1):
    """
    Kelompokkan komponen elementer:
      - tren    : komponen 1..trend_count
      - musiman : komponen trend_count+1..r
      - sinyal  : tren + musiman (komponen 1..r), dipakai untuk peramalan
    Komponen setelah r dianggap noise dan dibuang.
    """
    N = len(components[0])
    trend = np.sum(components[:trend_count], axis=0) if trend_count else np.zeros(N)
    seasonal = np.sum(components[trend_count:r], axis=0) if r > trend_count else np.zeros(N)
    return trend, seasonal, trend + seasonal


# ---------------------------------------------------------------------------
# Tahap 3: Peramalan (Recurrent SSA)
# ---------------------------------------------------------------------------
def lrr_coefficients(U, r):
    """Koefisien Linear Recurrent Relation dari r vektor eigen pertama."""
    Ur = U[:, :r]
    pi = Ur[-1, :]              # komponen terakhir tiap vektor eigen
    nu2 = float(np.sum(pi ** 2))  # verticality coefficient
    if nu2 >= 1:
        raise ValueError("Verticality coefficient >= 1, R-SSA tidak dapat dihitung. Coba ubah L atau r.")
    R = (Ur[:-1, :] @ pi) / (1 - nu2)
    return R, nu2


def recurrent_forecast(signal, R, steps):
    """y_t = sum_{j=1}^{L-1} a_j * y_{t-j}, dimulai dari deret hasil rekonstruksi."""
    y = list(signal)
    L1 = len(R)
    for _ in range(steps):
        y.append(float(np.dot(R, y[-L1:])))
    return np.array(y[len(signal):])


# ---------------------------------------------------------------------------
# Tahap 4: Evaluasi
# ---------------------------------------------------------------------------
def metrics(actual, predicted):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    err = a - p
    mse = float(np.mean(err ** 2))
    return {
        'mae': float(np.mean(np.abs(err))),
        'mse': mse,
        'rmse': float(np.sqrt(mse)),
        'mape': float(np.mean(np.abs(err / a)) * 100),
    }


def mape_criteria(mape):
    """Kriteria MAPE (Tabel 2.1)."""
    if mape < 10:
        return 'Sangat Baik'
    if mape < 20:
        return 'Baik'
    if mape < 50:
        return 'Layak'
    return 'Buruk'


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def fit(series, L, r, n_components=None):
    """Jalankan dekomposisi + rekonstruksi, kembalikan semua hasil antara."""
    x = np.asarray(series, dtype=float)
    X = embedding(x, L)
    U, s, Vt = svd(X)
    if not 1 <= r < L:
        raise ValueError(f"Jumlah grup r harus di antara 1 dan L-1 ({L - 1}), didapat r={r}")
    n = max(r, min(n_components or r, len(s)))
    comps = elementary_components(U, s, Vt, n)
    trend, seasonal, signal = grouping(comps, r)
    eigen = s ** 2
    return {
        'L': L, 'K': X.shape[1], 'r': r,
        'U': U, 's': s,
        'contribution': eigen / eigen.sum() * 100,
        'components': comps,
        'trend': trend, 'seasonal': seasonal, 'signal': signal,
        'noise': x - signal,
    }


def evaluate(series, L, r, train_ratio):
    """Latih SSA pada data latih, ramal sepanjang data uji, hitung error."""
    x = np.asarray(series, dtype=float)
    n_train = int(round(len(x) * train_ratio))
    train, test = x[:n_train], x[n_train:]
    model = fit(train, L, r)
    R, _ = lrr_coefficients(model['U'], r)
    pred = recurrent_forecast(model['signal'], R, len(test))
    return {'n_train': n_train, 'n_test': len(test), 'test_pred': pred,
            'fit_metrics': metrics(train, model['signal']), **metrics(test, pred)}


def search_parameters(series, train_ratio, r_max=10):
    """
    Penentuan L secara coba-coba: setiap L di 2..N_latih/2 diuji dengan r = 1..min(L-1, r_max),
    lalu dipilih kombinasi dengan MAPE data uji terkecil.
    Mengembalikan (L terbaik, r terbaik, tabel ringkas MAPE terbaik per L).
    """
    x = np.asarray(series, dtype=float)
    n_train = int(round(len(x) * train_ratio))
    table = []
    for L in range(2, n_train // 2 + 1):
        best = None
        for r in range(1, min(L - 1, r_max) + 1):
            try:
                res = evaluate(x, L, r, train_ratio)
            except (ValueError, np.linalg.LinAlgError):
                continue
            if np.isfinite(res['mape']) and (best is None or res['mape'] < best['mape']):
                best = {'L': L, 'r': r, 'mape': res['mape'], 'mae': res['mae']}
        if best:
            table.append(best)
    if not table:
        raise ValueError("Tidak ada kombinasi L dan r yang valid untuk data ini.")
    winner = min(table, key=lambda row: row['mape'])
    return winner['L'], winner['r'], table


def forecast(series, L, r, steps):
    """Latih SSA pada seluruh data lalu ramal `steps` periode ke depan."""
    model = fit(series, L, r, n_components=min(L, 12))
    R, nu2 = lrr_coefficients(model['U'], r)
    model['forecast'] = recurrent_forecast(model['signal'], R, steps)
    model['nu2'] = nu2
    return model
