// Format angka gaya Indonesia: 1.234,56
const formatTon = (v, d = 2) =>
    Number(v).toLocaleString('id-ID', { minimumFractionDigits: d, maximumFractionDigits: d });

// Warna grafik: hijau = data aktual/model, emas = ramalan (satu-satunya aksen), abu = pembanding
const WARNA = { aktual: '#2E5E3E', ramalan: '#B7861F', pudar: '#A9B7A2', noise: '#7C8577' };

const chartBase = {
    chart: {
        fontFamily: "'Source Sans 3', 'Segoe UI', system-ui, sans-serif",
        foreColor: '#535C4E',
        toolbar: { show: true, tools: { download: false } },
        zoom: { enabled: true },
        animations: { enabled: false },
    },
    dataLabels: { enabled: false },
    grid: { borderColor: '#E3DBC6', strokeDashArray: 3 },
    legend: { position: 'top', horizontalAlign: 'left' },
    tooltip: { y: { formatter: v => v == null ? '-' : formatTon(v) + ' ton' } },
    yaxis: { labels: { formatter: v => formatTon(v, 0) } },
};

if (window.DataTable) {
    $.extend(true, DataTable.defaults, {
        pagingType: 'simple_numbers',
        language: {
            search: 'Cari:',
            lengthMenu: 'Tampilkan _MENU_ data',
            info: 'Menampilkan _START_–_END_ dari _TOTAL_ data',
            infoEmpty: 'Tidak ada data',
            infoFiltered: '(disaring dari _MAX_ data)',
            zeroRecords: 'Tidak ada data yang cocok dengan pencarian',
            emptyTable: 'Belum ada data',
            paginate: { first: '«', previous: '‹', next: '›', last: '»' },
        },
    });
}

// Sidebar di layar kecil: buka dengan tombol menu, tutup dengan overlay atau Escape
(() => {
    const app = document.getElementById('app');
    const toggle = document.getElementById('menuToggle');
    if (!app || !toggle) return;
    const setOpen = open => {
        app.classList.toggle('nav-open', open);
        toggle.setAttribute('aria-expanded', String(open));
        if (open) document.querySelector('#sidebar a')?.focus();
    };
    toggle.addEventListener('click', () => setOpen(!app.classList.contains('nav-open')));
    document.getElementById('sideOverlay').addEventListener('click', () => setOpen(false));
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && app.classList.contains('nav-open')) {
            setOpen(false);
            toggle.focus();
        }
    });
})();
