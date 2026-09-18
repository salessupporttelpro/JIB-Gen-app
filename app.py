"""
JIB Composer -- mini-app internal GSD untuk menyusun draft Justifikasi Inisiatif Bisnis (JIB)
otomatis dari dokumen referensi (RKS/TOR, Undangan/Notulen, RAB).

Cara pakai:
    1. pip install -r requirements.txt
    2. Pastikan file .env berisi GEMINI_API_KEY, APP_USERNAME, dan APP_PASSWORD
    3. streamlit run app.py
"""

import json
import os
import re
import tempfile
import time

import streamlit as st
from google import genai
from google.genai import types
from dotenv import load_dotenv

from extract import extract_reference_files, read_all_local_references
from prompt import SYSTEM_PROMPT, FEW_SHOT_EXAMPLE, build_user_prompt
from build_docx import build_jib_docx

# Muat variabel environment dari .env
load_dotenv()

st.set_page_config(page_title="JIB Composer - GSD", layout="wide")

# ==============================================================================
# SISTEM LOGIN SEDERHANA (MEMBACA DARI .ENV)
# ==============================================================================
ENV_USERNAME = os.getenv("APP_USERNAME", "admin")
ENV_PASSWORD = os.getenv("APP_PASSWORD", "gsd123")


def check_password():
    """Memeriksa login pengguna berdasarkan kredensial di file .env."""
    if st.session_state.get("authenticated", False):
        return True

    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔒 Login Internal JIB Generator")
        st.caption("Masukkan kredensial unit untuk mengakses aplikasi.")

        input_user = st.text_input("Username", key="input_username")
        input_pass = st.text_input("Password", type="password", key="input_password")
        login_btn = st.button("Login", type="primary", use_container_width=True)

        if login_btn:
            if input_user == ENV_USERNAME and input_pass == ENV_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Username atau Password salah!")
    return False


# Hentikan eksekusi jika pengguna belum terautentikasi
if not check_password():
    st.stop()

# ==============================================================================
# AUTO-RESET SAAT BROWSER DI-REFRESH (F5 / CTRL+R)
# ==============================================================================
if "is_generating" not in st.session_state:
    if "generated_data" in st.session_state:
        del st.session_state["generated_data"]
    if "generated_out_path" in st.session_state:
        del st.session_state["generated_out_path"]
    if "generated_out_name" in st.session_state:
        del st.session_state["generated_out_name"]

if "is_generating" in st.session_state:
    del st.session_state["is_generating"]

# Inisialisasi session state untuk status kuota limit API
if "api_limit_exceeded" not in st.session_state:
    st.session_state.api_limit_exceeded = False

# Header Utama
col_header1, col_header2 = st.columns([1, 6])

with col_header1:
    telpro_img = "https://telkomproperty.co.id/_next/image?url=%2F_next%2Fstatic%2Fmedia%2FlogoTelkomHeader.ff908c55.png&w=3840&q=75"
    st.markdown("<br>", unsafe_allow_html=True)
    st.image(telpro_img)
with col_header2:
    st.title("JIB Generator")

st.caption(
    "Susun draft Justifikasi Inisiatif Bisnis (JIB) dari dokumen referensi secara otomatis. "
    "Hasil tetap WAJIB direview sebelum dipakai resmi."
)

# Ambil API Keys
raw_keys = os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_API_KEY", ""))
api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

# Status Sidebar Dinamis + Tombol Logout
with st.sidebar:
    st.header("Status Sistem")

    if st.session_state.api_limit_exceeded:
        st.warning("🟡 API Key Limit / Quota Habis (429)")
        st.caption(
            "Silakan tunggu 1–2 menit atau perbarui `GEMINI_API_KEY` di file `.env`."
        )
    elif api_keys:
        st.success("🟢 API Key Terhubung")
    else:
        st.error("🔴 API Key Belum Ditemukan di .env")

    st.divider()

    # Tombol Logout
    if st.button("Logout", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.divider()
    st.markdown(
        "**Catatan:**\n"
        "- Field kosong akan diisi model sebisa mungkin dari dokumen referensi.\n"
        "- Angka finansial (Revenue/Beban/Net Income) dapat diupload dalam format final dengan bentuk PDF atau di bagian informasi tambahan.\n"
        "- Tool ini tidak menyimpan dokumen di server manapun; semua diproses saat runtime.\n"
    )

st.subheader("Masukkan Informasi")
col3, col4 = st.columns(2)
with col3:
    st.markdown("**Upload Dokumen Pendukung**")
    ref_pdfs = st.file_uploader(
        "RKS/TOR/Undangan/Notulen (PDF, dapat lebih dari satu)",
        type=["pdf"],
        accept_multiple_files=True,
    )
    nama_program = st.text_input("Nama Program (kosongkan jika ikut dokumen)")
    unit_kerja = st.text_input(
        "Unit Kerja Inisiator", value="Direktorat Bisnis - Unit Sales TELKOM"
    )
    additional_information_ref = st.text_area("Informasi tambahan")
with col4:
    st.markdown("**Data Penandatangan**")
    inisiator_nama = st.text_input("Inisiator - Nama")
    inisiator_jabatan = st.text_input("Inisiator - Jabatan")
    reviewer_nama = st.text_input("Reviewer - Nama")
    reviewer_jabatan = st.text_input("Reviewer - Jabatan")
    approver_nama = st.text_input("Approver - Nama")
    approver_jabatan = st.text_input("Approver - Jabatan")

generate = st.button("Generate Draft JIB", type="primary", use_container_width=True)

if generate:
    st.session_state.is_generating = True

    all_files = list(ref_pdfs or [])
    if not all_files:
        st.error("Upload minimal satu dokumen referensi (RKS/TOR/Undangan) dulu.")
        st.stop()
    if not api_keys:
        st.error("Isi GEMINI_API_KEY di file .env terlebih dahulu.")
        st.stop()

    st.session_state.api_limit_exceeded = False

    with st.spinner("Membaca dokumen acuan lokal & unggahan..."):
        uploaded_bytes = {f.name: f.read() for f in all_files}
        user_ref_text = extract_reference_files(uploaded_bytes)
        local_ref_text = read_all_local_references("references")

    signer_data = (
        f"Inisiator: {inisiator_nama or '-'} / {inisiator_jabatan or '-'}\n"
        f"Reviewer: {reviewer_nama or '-'} / {reviewer_jabatan or '-'}\n"
        f"Approver: {approver_nama or '-'} / {approver_jabatan or '-'}"
    )

    user_prompt = build_user_prompt(
        local_reference_text=local_ref_text,
        user_reference_text=user_ref_text,
        additional_information=additional_information_ref,
        nama_program_hint=nama_program,
        unit_kerja_hint=unit_kerja,
        signer_data=signer_data,
    )

    models_to_try = ["gemini-3.5-flash", "gemini-3.1-pro", "gemini-3.1-flash-lite"]
    response = None
    raw_text = ""

    with st.spinner("Menyusun draft JIB dengan Gemini..."):
        for current_key in api_keys:
            client = genai.Client(api_key=current_key)
            for model_name in models_to_try:
                try:
                    res = client.models.generate_content(
                        model=model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT
                            + "\n\n"
                            + FEW_SHOT_EXAMPLE,
                            response_mime_type="application/json",
                            temperature=0.2,
                        ),
                    )
                    if res and res.text:
                        response = res
                        raw_text = res.text
                        st.session_state.api_limit_exceeded = False
                        break
                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        st.session_state.api_limit_exceeded = True
                        st.warning(
                            "Quota/Rate Limit tercapai (429). Mencoba opsi/key lain..."
                        )
                        time.sleep(1.5)
                    elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                        st.warning(
                            f"Model {model_name} sibuk. Mencoba model cadangan..."
                        )
                        time.sleep(1.5)
                    else:
                        st.warning(f"Error pada {model_name}: {e}")
            if response:
                break

    if st.session_state.api_limit_exceeded and not raw_text:
        st.rerun()

    if not raw_text:
        st.error(
            "Gagal mendapatkan respon dari Gemini API. Silakan coba lagi beberapa saat lagi."
        )
        st.stop()

    data = None
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        cleaned = re.sub(
            r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE
        ).strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            st.error(
                "Respons model bukan JSON valid. Coba klik Generate lagi, atau lihat raw output di bawah."
            )
            st.text_area("Raw output", raw_text, height=300)
            st.stop()

    if data:
        with st.spinner("Menyusun file Word..."):
            filename_clean = re.sub(
                r"[^A-Za-z0-9]+", "_", str(data.get("judul_project", "draft"))
            )[:60]
            out_name = f"JIBGen_{filename_clean}.docx"

            temp_dir = tempfile.gettempdir()
            out_path = os.path.join(temp_dir, out_name)
            build_jib_docx(data, out_path)

            st.session_state.generated_data = data
            st.session_state.generated_out_path = out_path
            st.session_state.generated_out_name = out_name

# ==============================================================================
# TAMPILKAN PRATINJAU JIKA DATA SUDAH TERSEDIA DI SESSION STATE
# ==============================================================================
if "generated_data" in st.session_state and st.session_state.generated_data:
    data = st.session_state.generated_data
    out_path = st.session_state.generated_out_path
    out_name = st.session_state.generated_out_name

    st.success("Draft JIB selesai dibuat. Review sebelum digunakan resmi.")

    tab_preview, tab_raw = st.tabs(
        ["📊 Pratinjau Tabel & Format", "🔍 Raw JSON (Debug)"]
    )

    with tab_preview:
        st.markdown(f"### PROJECT: {str(data.get('judul_project', '-')).upper()}")

        col_a, col_b = st.columns(2)
        with col_a:
            st.write(f"**Nama Program:** {data.get('nama_program', '-')}")
        with col_b:
            st.write(
                f"**Unit Kerja Inisiator:** {data.get('unit_kerja_inisiator', '-')}"
            )

        st.divider()

        def _clean_ui_item(val):
            s = str(val).strip()
            cleaned = re.sub(r"^(?:(?:\d+|[a-zA-Z])[\.\)]\s*|[-•]\s*)+", "", s).strip()
            if not cleaned:
                cleaned = s
            # Tambahkan titik di akhir jika tidak ada tanda baca
            if cleaned and cleaned[-1] not in [".", "!", "?", ":", ";"]:
                cleaned += "."
            return cleaned

        # 1. Latar Belakang Kebutuhan Bisnis
        st.markdown("### 1. Latar Belakang Kebutuhan Bisnis")
        latar_belakang = data.get("latar_belakang", [])
        if isinstance(latar_belakang, list) and latar_belakang:
            for i, item in enumerate(latar_belakang, 1):
                st.markdown(f"{i}. {_clean_ui_item(item)}")
        else:
            st.write("-")

        # 2. Ruang Lingkup
        st.markdown("### 2. Ruang Lingkup Pekerjaan")
        ruang_lingkup = data.get("ruang_lingkup", [])
        if isinstance(ruang_lingkup, list) and ruang_lingkup:
            for item in ruang_lingkup:
                if isinstance(item, dict):
                    indent = (
                        "&nbsp;&nbsp;&nbsp;&nbsp;" if item.get("level", 0) > 0 else ""
                    )
                    clean_txt = _clean_ui_item(item.get("text", ""))
                    st.markdown(f"{indent}• {clean_txt}", unsafe_allow_html=True)
                else:
                    st.markdown(f"• {_clean_ui_item(item)}")
        else:
            st.write("-")

        # 3. Asumsi
        st.markdown("### 3. Asumsi yang Digunakan")
        asumsi = data.get("asumsi", {}) if isinstance(data.get("asumsi"), dict) else {}
        fin_data = asumsi.get("financial_table", [])
        if fin_data:
            st.caption("**Perhitungan nilai pekerjaan:**")
            st.dataframe(
                fin_data,
                hide_index=True,
                use_container_width=True,
            )

        catatan_asumsi = asumsi.get("catatan", [])
        if catatan_asumsi:
            st.caption("**Catatan Asumsi:**")
            for i, c in enumerate(catatan_asumsi):
                prefix_char = chr(97 + (i % 26))
                st.markdown(f"{prefix_char}. {_clean_ui_item(c)}")

        # 4. Analisis-Analisis & Mitigasi Risiko
        st.markdown("### 4. Analisis-Analisis DAN MITIGASI RISIKO")
        analisis = (
            data.get("analisis", {}) if isinstance(data.get("analisis"), dict) else {}
        )

        # 4.1 Sub-Bagian Aspek
        data_kelayakan_narasi = (
            analisis.get("kelayakan_proyek")
            or analisis.get("kelayakan")
            or analisis.get("aspek_kelayakan")
            or []
        )

        sections = [
            ("1. ASPEK STRATEGIS", analisis.get("strategis", [])),
            ("2. ASPEK KOMPETISI", analisis.get("kompetisi", [])),
            ("3. ASPEK MANFAAT", analisis.get("manfaat", [])),
            ("4. ASPEK BISNIS", analisis.get("bisnis", [])),
            ("5. ASPEK KELAYAKAN PROYEK", data_kelayakan_narasi),
            ("6. ASPEK TEKNIS", analisis.get("teknis", [])),
        ]

        for label_sub, items_sub in sections:
            st.markdown(f"**{label_sub}:**")

            # Cetak Narasi
            if isinstance(items_sub, list) and items_sub:
                for idx, sub_item in enumerate(items_sub):
                    prefix_char = chr(97 + (idx % 26))
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;{prefix_char}. {_clean_ui_item(sub_item)}",
                        unsafe_allow_html=True,
                    )
            elif items_sub:
                st.markdown(
                    f"&nbsp;&nbsp;&nbsp;&nbsp;a. {_clean_ui_item(items_sub)}",
                    unsafe_allow_html=True,
                )
            else:
                if label_sub != "5. ASPEK KELAYAKAN PROYEK":
                    st.write("-")

            # Cetak Tabel Kelayakan Proyek
            if label_sub == "5. ASPEK KELAYAKAN PROYEK":
                kelayakan_table = analisis.get("kelayakan_table", [])
                if kelayakan_table:
                    st.caption("**Tabel Perhitungan Kelayakan Proyek:**")
                    st.table(kelayakan_table)

        # 4.2 Analisis dan Mitigasi Risiko
        st.markdown("**7. ANALISIS DAN MITIGASI RISIKO:**")
        risiko_mitigasi_list = analisis.get("risiko_dan_mitigasi", [])
        if isinstance(risiko_mitigasi_list, list) and risiko_mitigasi_list:
            for rm in risiko_mitigasi_list:
                if isinstance(rm, dict):
                    kat = rm.get("kategori", "Risiko")
                    st.markdown(f"**• {kat}:**")

                    r_list = rm.get("risiko", [])
                    if r_list:
                        st.caption("Risiko:")
                        for i_r, r_item in enumerate(r_list):
                            prefix = chr(97 + (i_r % 26))
                            st.markdown(
                                f"&nbsp;&nbsp;&nbsp;&nbsp;{prefix}. {_clean_ui_item(r_item)}",
                                unsafe_allow_html=True,
                            )

                    m_list = rm.get("mitigasi", [])
                    if m_list:
                        st.caption("Mitigasi:")
                        for i_m, m_item in enumerate(m_list):
                            prefix = chr(97 + (i_m % 26))
                            st.markdown(
                                f"&nbsp;&nbsp;&nbsp;&nbsp;{prefix}. {_clean_ui_item(m_item)}",
                                unsafe_allow_html=True,
                            )
        else:
            st.write("-")

        st.divider()

        # 5. Kesimpulan
        st.markdown("### 5. Kesimpulan")
        kesimpulan_obj = data.get("kesimpulan", {})
        judul_p = str(data.get("judul_project", "-")).strip()

        if isinstance(kesimpulan_obj, dict):
            status_ai = _clean_ui_item(
                kesimpulan_obj.get("status_kelayakan", "[Layak/Tidak Layak]")
            )
            if "layak" not in status_ai.lower():
                status_ai = f"[Layak/Tidak Layak] {status_ai}".strip()

            st.markdown(
                f"**Kesimpulan:** Project **{judul_p}** dinyatakan **{status_ai}** dengan catatan untuk memperhatikan risiko-risiko sebagai berikut :"
            )
            poin_list = kesimpulan_obj.get("poin_kesimpulan", [])
            if isinstance(poin_list, list):
                for i, p in enumerate(poin_list, 1):
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;{i}. {_clean_ui_item(p)}",
                        unsafe_allow_html=True,
                    )
        else:
            st.write(str(kesimpulan_obj))

        st.divider()

        # 6. Rekomendasi Keputusan
        st.markdown("### 6. Rekomendasi Keputusan")
        st.write(data.get("rekomendasi_keputusan", "-"))

        # 7. Keputusan
        st.markdown("### 7. Keputusan")
        st.write(data.get("keputusan", "-"))

        st.divider()

        # Ringkasan Penandatangan
        st.markdown("### Data Penandatangan")
        col_inisiator, col_reviewer, col_approver = st.columns(3)

        inisiator = (
            data.get("inisiator", {}) if isinstance(data.get("inisiator"), dict) else {}
        )
        reviewer = (
            data.get("reviewer", {}) if isinstance(data.get("reviewer"), dict) else {}
        )
        approver = (
            data.get("approver", {}) if isinstance(data.get("approver"), dict) else {}
        )

        with col_inisiator:
            st.markdown("**Inisiator**")
            st.caption(
                f"Nama: {inisiator.get('nama', '-')}\n\nJabatan: {inisiator.get('jabatan', '-')}"
            )
        with col_reviewer:
            st.markdown("**Reviewer**")
            st.caption(
                f"Nama: {reviewer.get('nama', '-')}\n\nJabatan: {reviewer.get('jabatan', '-')}"
            )
        with col_approver:
            st.markdown("**Approver**")
            st.caption(
                f"Nama: {approver.get('nama', '-')}\n\nJabatan: {approver.get('jabatan', '-')}"
            )

    with tab_raw:
        st.caption("Gunakan scrollbar di bawah untuk menjelajahi data JSON lengkap:")
        with st.container(height=400):
            st.json(data)

    st.markdown("---")

    # Tombol Download
    if os.path.exists(out_path):
        with open(out_path, "rb") as f:
            st.download_button(
                "⬇️ Download Draft JIB (.docx)",
                data=f.read(),
                file_name=out_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )
