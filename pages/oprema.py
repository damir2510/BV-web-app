import streamlit as st
import pandas as pd
import io
import os
import re
import json
import calendar
import requests
from datetime import datetime
from db_utils import run_query, get_conn, execute_db
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

st.set_page_config(page_title="Evidencija Opreme", layout="wide")

st.markdown("""
    <style>
        html, body, .stMarkdown p, .stTable, .stDataFrame { font-family: 'Arial', sans-serif; }
        .stAlert { padding: 0.5rem; margin-bottom: 0.5rem; }
        [data-testid="stSidebarNav"] ul { display: none; }
    </style>
""", unsafe_allow_html=True)

try:
    pdfmetrics.registerFont(TTFont('Serbian', 'Arial.ttf'))
    FONT_NAME = 'Serbian'
except Exception:
    FONT_NAME = 'Helvetica'

GLAVNI_DRIVE_FOLDER_ID = os.getenv("GLAVNI_DRIVE_FOLDER_ID", "13NlAHUkiZDB3Lm-1W9TOiU6WqZ3pib9P")
SCOPES = ["https://www." + "googleapis." + "com/auth/drive"]
def get_drive_service():
    token_json_str = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
    if not token_json_str:
        return None
    info = json.loads(token_json_str)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("drive", "v3", credentials=creds)

def otpremi_dokument_na_drive(uploaded_file, inv_br, novo_ime_fajla):
    service = get_drive_service()
    if not service:
        return None, "GOOGLE_TOKEN_JSON nije podesen na Railway-u."
    naziv_foldera = f"Aparat_{inv_br}"
    upit = (
        f"name = '{naziv_foldera}' and '{GLAVNI_DRIVE_FOLDER_ID}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    rez = service.files().list(q=upit, fields="files(id, webViewLink)").execute().get("files", [])
    if rez:
        prvi = next(iter(rez))
        folder_id, folder_link = prvi.get("id"), prvi.get("webViewLink")
    else:
        meta = {"name": naziv_foldera, "mimeType": "application/vnd.google-apps.folder", "parents": [GLAVNI_DRIVE_FOLDER_ID]}
        novi = service.files().create(body=meta, fields="id, webViewLink").execute()
        folder_id, folder_link = novi.get("id"), novi.get("webViewLink")

    media = MediaIoBaseUpload(io.BytesIO(uploaded_file.getvalue()), mimetype=uploaded_file.type or "application/octet-stream", resumable=False)
    service.files().create(body={"name": novo_ime_fajla, "parents": [folder_id]}, media_body=media, fields="id").execute()
    return folder_link, None

def ocisti_naziv(tekst):
    if not tekst:
        return "Oprema"
    zamene = {"č": "c", "ć": "c", "ž": "z", "š": "s", "đ": "dj", "Č": "C", "Ć": "C", "Ž": "Z", "Š": "S", "Đ": "Dj"}
    for k, v in zamene.items():
        tekst = str(tekst).replace(k, v)
    return re.sub(r"[^A-Za-z0-9_-]+", "_", tekst.strip()).strip("_") or "Oprema"

def izracunaj_rok_vazenja(datum_pocetka, period_provere):
    tekst = str(period_provere or "").lower().strip()
    m = re.search(r"(\d+)", tekst)
    broj = int(m.group(1)) if m else 1
    meseci = broj if "mesec" in tekst else (broj * 12 if ("god" in tekst or broj <= 5) else broj)
    ukupno_meseci = datum_pocetka.month - 1 + meseci
    nova_god = datum_pocetka.year + ukupno_meseci // 12
    novi_mes = ukupno_meseci % 12 + 1
    novi_dan = min(datum_pocetka.day, max(calendar.monthrange(nova_god, novi_mes)))
    return datetime(nova_god, novi_mes, novi_dan).date()
def dobij_grad_iz_gps(gps_str):
    if not gps_str or "," not in str(gps_str):
        return None
    try:
        delovi = str(gps_str).replace(" ", "").split(",")
        lat, lon = delovi.pop(0), delovi.pop(0)
        url = f"https://openstreetmap.org{lat}&lon={lon}&zoom=10&addressdetails=1"
        r = requests.get(url, headers={"User-Agent": "BV-Web-App/1.0"}, timeout=5).json()
        adr = r.get("address", {})
        return adr.get("city") or adr.get("town") or adr.get("village") or adr.get("municipality")
    except Exception:
        return None

def apply_styling(df_st):
    if 'vazi_do' not in df_st.columns:
        return df_st
    return df_st.style.map(
        lambda v: "background-color: #ff4b4b; color: white" if pd.notnull(v) and pd.to_datetime(v).date() < datetime.now().date() else "",
        subset=['vazi_do']
    )

def generisi_pdf_karton(ins, df_s, df_e, df_b, df_k):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    s_naslov = styles['Title']; s_naslov.fontName = FONT_NAME
    s_h2 = styles['Heading2']; s_h2.fontName = FONT_NAME
    s_n = styles['Normal']; s_n.fontName = FONT_NAME

    elements = []
    inv_br = ins.get('inventarni_broj', 'N/A')
    elements.append(Paragraph(f"MATIČNI KARTON OPREME br: {inv_br}", s_naslov))
    elements.append(Paragraph(f"Datum izveštaja: {datetime.now().strftime('%d.%m.%Y.')}", s_n))
    elements.append(Spacer(1, 20))

    elements.append(Paragraph("1. TEHNIČKE KARAKTERISTIKE", s_h2))
    teh_podaci = [
        ["Proizvođač:", str(ins.get('proizvodjac', '-'))],
        ["Model:", str(ins.get('naziv_proizvodjac', '-'))],
        ["Serijski broj:", str(ins.get('seriski_broj', '-'))],
        ["Vrsta aparata:", str(ins.get('vrsta_opreme', '-'))],
        ["Godina proizvodnje:", str(ins.get('godina_proizvodnje', '-'))],
        ["U upotrebi od:", str(ins.get('upotreba_od', '-'))],
        ["Opseg merenja:", str(ins.get('opseg_merenja', '-'))],
        ["Klasa tačnosti:", str(ins.get('klasa_tacnosti', '-'))],
        ["Preciznost / Podeok:", f"{ins.get('preciznost', '-')} / {ins.get('podeok', '-')}"]
    ]
    t1 = Table(teh_podaci, colWidths=(150, 300))
    t1.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.grey), ('FONTNAME', (0, 0), (-1, -1), FONT_NAME)]))
    elements.append(t1)

    sekcije = [("2. BAŽDARENJA", df_b), ("3. ETALONIRANJA", df_e), ("4. SERVISI", df_s), ("5. KULTURE / OPSEZI", df_k)]
    for naslov, df_sec in sekcije:
        elements.append(Spacer(1, 15)); elements.append(Paragraph(naslov, s_h2))
        if not df_sec.empty:
            df_clean = df_sec.drop(columns=[c for c in ['id', 'inventarni_broj', 'link_dokumenta'] if c in df_sec.columns])
            data = [df_clean.columns.to_list()] + df_clean.astype(str).values.tolist()
            t_sec = Table(data, hAlign='LEFT', repeatRows=1)
            t_sec.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey), ('GRID', (0, 0), (-1, -1), 0.5, colors.grey), ('FONTNAME', (0, 0), (-1, -1), FONT_NAME), ('FONTSIZE', (0, 0), (-1, -1), 8)]))
            elements.append(t_sec)
        else:
            elements.append(Paragraph("Nema zabeleženih podataka.", s_n))

    doc.build(elements)
    return buffer.getvalue()
if 'ulogovan' not in st.session_state or not st.session_state['ulogovan']:
    st.switch_page("glavna.py")
    st.stop()

is_admin = int(st.session_state.get('is_premium', 0)) == 1
ime_korisnika = st.session_state.get('ime_korisnika', 'Korisnik')

st.markdown("<h1 style='text-align: center;'>Oprema</h1>", unsafe_allow_html=True)

st.sidebar.markdown(f"👤 Prijavljeni: **{ime_korisnika}**")

# 1. Odjavi se i Otvori Mapu na vrhu
if st.sidebar.button("🚪 Odjavi se", use_container_width=True):
    st.session_state['ulogovan'] = False
    if "sesija" in st.query_params:
        del st.query_params["sesija"]
    st.rerun()

if st.sidebar.button("🗺️ Otvori Mapu", use_container_width=True):
    st.switch_page("pages/mapa_opreme.py")

# 2. Mali razmak pa Inventarski broj
st.sidebar.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
izabrani_broj = st.sidebar.text_input("🔢 Inventarski br. (za KARTON):", "").strip()

# 3. Malo veći razmak pa Admin opcije (Izbor tabele i Uvoz Excela)
tabela_opcije = {
    "Glavna Oprema": "oprema",
    "Istorija Servisa": "istorija_servisa",
    "Etaloniranje": "istorija_etaloniranja",
    "Baždarenje": "istorija_bazdarenja",
    "Kulture": "kulture_opsezi"
}

izabrana_tabela = "oprema"
if is_admin:
    st.sidebar.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
    izbor_prikaza = st.sidebar.selectbox("Izaberi tabelu za rad:", list(tabela_opcije.keys()))
    izabrana_tabela = tabela_opcije[izbor_prikaza]
    uploaded_file = st.sidebar.file_uploader("Uvezi Excel (Update)", type=["xlsx"])
    if uploaded_file and st.sidebar.button("🚀 POKRENI UVOZ", use_container_width=True):
        try:
            new_data = pd.read_excel(uploaded_file)
            conn = get_conn(); cur = conn.cursor()
            cols = [c.strip().lower() for c in new_data.columns]
            update_part = ", ".join([f"{c} = VALUES({c})" for c in cols])
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO {izabrana_tabela} ({','.join(cols)}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {update_part}"
            for _, row in new_data.iterrows():
                cur.execute(sql, [None if pd.isna(x) else x for x in row])
            conn.commit(); conn.close(); st.sidebar.success("Podaci osveženi!"); st.rerun()
        except Exception as e:
            st.sidebar.error(f"Greška: {e}")
try:
    if izabrana_tabela == "oprema":
        upit_oprema = (
            "SELECT o.*, GREATEST(COALESCE(o.vazi_do, '1900-01-01'), "
            "COALESCE((SELECT MAX(b.vazi_do) FROM istorija_bazdarenja b WHERE b.inventarni_broj = o.inventarni_broj), '1900-01-01')) AS max_vazi_do "
            "FROM oprema o"
        )
        df_raw = run_query(upit_oprema)
        if not df_raw.empty:
            df = df_raw.copy()
            df.columns = [c.strip().lower() for c in df.columns]
            df['vazi_do'] = pd.to_datetime(df['max_vazi_do'], errors='coerce').dt.date
            df.loc[df['vazi_do'] == datetime(1900, 1, 1).date(), 'vazi_do'] = pd.NaT

            if 'vrsta_opreme' in df.columns:
                vrste = ["SVE"] + sorted(df['vrsta_opreme'].dropna().unique().tolist())
                izabrana_vrsta = st.selectbox("📁 Filtriraj po vrsti aparata:", vrste)
                if izabrana_vrsta != "SVE":
                    df = df[df['vrsta_opreme'] == izabrana_vrsta]

            red_kolona = ['inventarni_broj', 'sektor', 'vrsta_opreme', 'proizvodjac', 'naziv_proizvodjac', 'seriski_broj', 'trenutni_radnik', 'zadnja_lokacija', 'vazi_do', 'napomena']
            df_prikaz = df[[c for c in red_kolona if c in df.columns]]

            pretraga = st.text_input("🔍 Pretraga baze:", "").lower()
            if pretraga:
                df_prikaz = df_prikaz[df_prikaz.astype(str).apply(lambda x: x.str.lower().str.contains(pretraga)).any(axis=1)]

            st.dataframe(apply_styling(df_prikaz), use_container_width=True, hide_index=True)
    else:
        df_raw = run_query(f"SELECT * FROM {izabrana_tabela}")
        if not df_raw.empty:
            df_prikaz = df_raw.drop(columns=[c for c in ['id', 'link_dokumenta'] if c in df_raw.columns])
            pretraga = st.text_input("🔍 Pretraga tabele:", "").lower()
            if pretraga:
                df_prikaz = df_prikaz[df_prikaz.astype(str).apply(lambda x: x.str.lower().str.contains(pretraga)).any(axis=1)]
            st.dataframe(apply_styling(df_prikaz), use_container_width=True, hide_index=True)
    if izabrani_broj:
        st.markdown("---")
        res = run_query("SELECT * FROM oprema WHERE inventarni_broj = %s", (izabrani_broj,))
        if not res.empty:
            ins = next(iter(res.to_dict(orient='records')))
            st.subheader(f"📑 Matični karton: {ins.get('naziv_proizvodjac')} - {izabrani_broj}")

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.info(f"**Proizvođač:**\n\n{ins.get('proizvodjac', '-')}")
            c2.info(f"**Model:**\n\n{ins.get('naziv_proizvodjac', '-')}")
            c3.info(f"**Godina pr.:**\n\n{ins.get('godina_proizvodnje', '-')}")
            c4.info(f"**U upotrebi od:**\n\n{ins.get('upotreba_od', '-')}")
            c5.info(f"**Period provere:**\n\n{ins.get('period_provere', '1')} god.")

            tech_cols = [("Opseg merenja", "opseg_merenja"), ("Klasa tačnosti", "klasa_tacnosti"), ("Preciznost", "preciznost"), ("Podeok", "podeok"), ("Radna temp.", "radna_temperatura"), ("Rel. vlažnost", "rel_vlaznost")]
            cols_tech = st.columns(len(tech_cols))
            for i, (naslov, kljuc) in enumerate(tech_cols):
                vrednost = ins.get(kljuc)
                if vrednost and str(vrednost).strip() not in ['None', '', 'nan']:
                    cols_tech[i].success(f"**{naslov}:**\n\n{vrednost}")

            col_d1, col_d2 = st.columns(2)
            with col_d1:
                putanja = ins.get('putanja_folder')
                if putanja and str(putanja) != 'None':
                    st.link_button("📂 OTVORI DRIVE FOLDER", putanja, type="primary", use_container_width=True)
                else:
                    st.link_button("🔍 PRETRAŽI DRIVE", f"https://google.com_{izabrani_broj}", use_container_width=True)
            with col_d2:
                if st.button("🖨️ PRIPREMI PDF KARTON", use_container_width=True):
                    df_s = run_query("SELECT * FROM istorija_servisa WHERE inventarni_broj = %s", (izabrani_broj,))
                    df_e = run_query("SELECT * FROM istorija_etaloniranja WHERE inventarni_broj = %s", (izabrani_broj,))
                    df_b = run_query("SELECT * FROM istorija_bazdarenja WHERE inventarni_broj = %s", (izabrani_broj,))
                    df_k = run_query("SELECT * FROM kulture_opsezi WHERE naziv_proizvodjac = %s", (ins.get('naziv_proizvodjac'),))
                    pdf_bin = generisi_pdf_karton(ins, df_s, df_e, df_b, df_k)
                    st.download_button(label="📥 PREUZMI PDF", data=pdf_bin, file_name=f"Karton_{izabrani_broj}.pdf", mime="application/pdf", use_container_width=True)

            t1, t2, t3, t4 = st.tabs(["🔧 Servis", "🧪 Etaloniranje", "📐 Baždarenje", "🌿 Kulture"])
            konfig = [
                (t1, "istorija_servisa", "datum_servisa", "Servis"),
                (t2, "istorija_etaloniranja", "datum_etaloniranja", "Etaloniranje"),
                (t3, "istorija_bazdarenja", "datum_bazdarenja", "Baždarenje"),
            ]

            for tab, tab_ime, kol_dat, nasl in konfig:
                with tab:
                    df_h = run_query(f"SELECT * FROM {tab_ime} WHERE inventarni_broj = %s ORDER BY {kol_dat} DESC", (izabrani_broj,))
                    if not df_h.empty:
                        df_h_prikaz = df_h.drop(columns=[c for c in ['id', 'inventarni_broj', 'link_dokumenta'] if c in df_h.columns])
                        st.dataframe(apply_styling(df_h_prikaz), use_container_width=True, hide_index=True)
                    else:
                        st.info(f"Nema zabeleženih podataka za {nasl.lower()}.")

                    if is_admin:
                        kljuc_forma = f"prikazi_formu_{tab_ime}_{izabrani_broj}"
                        if kljuc_forma not in st.session_state:
                            st.session_state[kljuc_forma] = False

                        if st.button(f"➕ Ubaci novo {nasl}", key=f"btn_{tab_ime}_{izabrani_broj}"):
                            st.session_state[kljuc_forma] = not st.session_state[kljuc_forma]

                        if st.session_state[kljuc_forma]:
                            with st.form(f"form_{tab_ime}_{izabrani_broj}"):
                                st.markdown(f"#### Unos: {nasl} (Aparat {izabrani_broj})")
                                d_rada = st.date_input(f"Datum ({nasl}):", value=datetime.now().date())
                                predlozeni_rok = izracunaj_rok_vazenja(d_rada, ins.get('period_provere', 1))

                                if nasl == "Baždarenje":
                                    br_dok = st.text_input("Broj uverenja / zapisnika:")
                                    d_vazi = st.date_input("Važi do:", value=predlozeni_rok)
                                elif nasl == "Etaloniranje":
                                    br_dok = st.text_input("Broj sertifikata:")
                                    lab = st.text_input("Laboratorija:")
                                    d_vazi = st.date_input("Važi do:", value=predlozeni_rok)
                                else:
                                    br_dok = st.text_input("Broj zapisnika / radnog naloga:")
                                    opis = st.text_area("Opis intervencije:")
                                    serviser = st.text_input("Izvršio servis:")
                                    novi_status = st.selectbox("Status aparata nakon servisa:", ["Ne menjaj", "U radu", "Neispravno"])

                                prilozeni_fajl = st.file_uploader("Priloži dokument (PDF, JPG, PNG):", type=["pdf", "jpg", "jpeg", "png"])

                                if st.form_submit_button(f"💾 Sačuvaj {nasl}", type="primary"):
                                    naziv_fajla_db = None
                                    if prilozeni_fajl is not None:
                                        _, ekst = os.path.splitext(prilozeni_fajl.name)
                                        ekst = ekst.lower()

                                        vrsta_cisto = ocisti_naziv(ins.get('vrsta_opreme'))
                                        tip_cisto = ocisti_naziv(nasl)
                                        broj_cisto = re.sub(r"[^A-Za-z0-9-]+", "-", br_dok.strip()).strip("-") or "dok"
                                        naziv_fajla_db = f"{tip_cisto}_{vrsta_cisto}_{broj_cisto}_{d_rada}{ekst}"

                                        folder_link, greska_drive = otpremi_dokument_na_drive(prilozeni_fajl, izabrani_broj, naziv_fajla_db)
                                        if greska_drive:
                                            st.warning(f"Dokument nije poslat na Drive ({greska_drive}), ali zapis je upisan u bazu.")
                                        elif folder_link and not (ins.get('putanja_folder') or '').strip():
                                            execute_db("UPDATE oprema SET putanja_folder = %s WHERE inventarni_broj = %s", (folder_link, izabrani_broj))

                                    if nasl == "Baždarenje":
                                        execute_db(
                                            "INSERT INTO istorija_bazdarenja (datum_bazdarenja, broj_uverenja, vazi_do, inventarni_broj, naziv_dokumenta) VALUES (%s, %s, %s, %s, %s)",
                                            (d_rada, br_dok, d_vazi, izabrani_broj, naziv_fajla_db)
                                        )
                                        execute_db(
                                            "UPDATE oprema SET datum_bazdarenja = %s, vazi_do = GREATEST(COALESCE(vazi_do, '1900-01-01'), %s) WHERE inventarni_broj = %s",
                                            (d_rada, d_vazi, izabrani_broj)
                                        )
                                    elif nasl == "Etaloniranje":
                                        execute_db(
                                            "INSERT INTO istorija_etaloniranja (datum_etaloniranja, broj_sertifikata, vazi_do, laboratorija, inventarni_broj, naziv_dokumenta) VALUES (%s, %s, %s, %s, %s, %s)",
                                            (d_rada, br_dok, d_vazi, lab, izabrani_broj, naziv_fajla_db)
                                        )
                                    else:
                                        execute_db(
                                            "INSERT INTO istorija_servisa (datum_servisa, broj_zapisnika, opis_intervencije, izvršio_servis, inventarni_broj, naziv_dokumenta) VALUES (%s, %s, %s, %s, %s, %s)",
                                            (d_rada, br_dok, opis, serviser, izabrani_broj, naziv_fajla_db)
                                        )
                                        if novi_status != "Ne menjaj":
                                            execute_db("UPDATE oprema SET status = %s WHERE inventarni_broj = %s", (novi_status, izabrani_broj))

                                    st.session_state[kljuc_forma] = False
                                    st.success(f"{nasl} uspešno sačuvano!")
                                    st.rerun()

            with t4:
                model_ap = ins.get('naziv_proizvodjac')
                if model_ap:
                    df_k = run_query("SELECT * FROM kulture_opsezi WHERE naziv_proizvodjac = %s", (model_ap,))
                    if not df_k.empty:
                        df_k_prikaz = df_k.drop(columns=[c for c in ['id'] if c in df_k.columns])
                        st.dataframe(df_k_prikaz, use_container_width=True, hide_index=True)
                    else:
                        st.info(f"Nema kultura za model {model_ap}")
except Exception as e:
    st.error(f"Greška: {e}")
