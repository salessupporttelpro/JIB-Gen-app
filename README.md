# JIB Composer — Mini-app Penyusun Draft JIB Otomatis

Mini-app internal (bukan produk Anthropic/Claude.ai) untuk mempercepat penyusunan draft
Justifikasi Inisiatif Bisnis (JIB) di GSD, dari **30–60 menit** menjadi:
- **Execute:** upload dokumen referensi + klik Generate → 1–2 menit
- **Review:** cek angka & narasi hasil draft → ~5 menit

Tool ini men-generate **draft** — tetap wajib direview manusia sebelum dipakai resmi
(terutama angka finansial dan nama/jabatan penandatangan).

## Cara Setup (sekali saja)

1. Install Python 3.10+ jika belum ada.
2. Di folder ini, jalankan:
   ```bash
   pip install -r requirements.txt
   ```
3. Dapatkan Anthropic API key di https://console.anthropic.com (perlu akun Anthropic Console
   terpisah dari akun Claude.ai — ini API key berbayar per-pemakaian, bukan bagian dari
   langganan Claude Pro).
4. Simpan API key sebagai environment variable supaya tidak perlu input ulang tiap kali:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-xxxxxxxx"
   ```
   (Windows PowerShell: `$env:ANTHROPIC_API_KEY="sk-ant-xxxxxxxx"`)

## Cara Menjalankan

```bash
streamlit run app.py
```

Browser akan otomatis terbuka ke `http://localhost:8501`. Untuk dipakai bareng tim tanpa
masing-masing install Python, app ini bisa di-deploy ke server internal kantor atau
Streamlit Community Cloud (tanya IT/DevOps untuk opsi hosting).

## Cara Pakai

1. Upload dokumen referensi: RKS/TOR/Undangan/Notulen (PDF) dan RAB/perhitungan
   profitabilitas (XLSX).
2. (Opsional) Isi Nama Program / Unit Kerja Inisiator kalau mau override apa yang ada di
   dokumen.
3. Isi nama & jabatan Inisiator / Reviewer / Approver.
4. Klik **Generate Draft JIB**.
5. Download file `.docx`, **review isi dan angkanya**, baru dikirim/diajukan.

## Struktur File

| File | Fungsi |
|---|---|
| `app.py` | UI Streamlit + orkestrasi alur |
| `extract.py` | Ekstrak teks dari PDF & XLSX referensi |
| `prompt.py` | System prompt, skema JSON, dan contoh gaya (few-shot) untuk Claude |
| `build_docx.py` | Menyusun file `.docx` JIB dari data JSON hasil Claude, mengikuti format tabel baku |

## Known Limitations (v1)

- Format tabel isi mengikuti struktur baku JIB (No | Aspek | Isi) — kalau template resmi
  berubah, `build_docx.py` perlu disesuaikan.
- Model bisa saja salah baca nominal dari RAB kalau format Excel-nya tidak standar —
  **selalu cocokkan angka finansial di draft dengan RAB asli**.
- Tidak ada penyimpanan riwayat/draft sebelumnya (setiap generate berdiri sendiri).
- Biaya pemakaian dibebankan ke API key yang dipakai (per token) — cek dashboard
  console.anthropic.com untuk memantau biaya.
