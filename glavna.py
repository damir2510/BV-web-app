import streamlit as st
import hashlib
from db_utils import run_query

st.set_page_config(page_title="BV Evidencija", layout="wide", page_icon="🏢")

if 'ulogovan' not in st.session_state:
    st.session_state['ulogovan'] = False

def napravi_token(korisnik, lozinka):
    return hashlib.sha256(f"bv_tajna_{korisnik}_{lozinka}".encode()).hexdigest()[:24]

# Automatska provera trajne prijave ako tab dugo stoji otvoren ili se osveži stranica
if not st.session_state['ulogovan'] and "sesija" in st.query_params:
    sacuvani_token = st.query_params["sesija"]
    svi_korisnici = run_query("SELECT korisnicko_ime, lozinka, ime_prezime, is_premium FROM zaposleni")
    if not svi_korisnici.empty:
        for _, row in svi_korisnici.iterrows():
            if napravi_token(row['korisnicko_ime'], row['lozinka']) == sacuvani_token:
                st.session_state['ulogovan'] = True
                st.session_state['is_premium'] = int(row['is_premium'])
                st.session_state['ime_korisnika'] = row['ime_prezime']
                break

p_oprema = st.Page("pages/oprema.py", title="Oprema", icon="🔍")
p_mapa = st.Page("pages/mapa_opreme.py", title="Mapa", icon="🗺️")

def izvrsi_prijava():
    u = st.session_state.korisnik_input
    p = st.session_state.lozinka_input
    res = run_query("SELECT ime_prezime, is_premium FROM zaposleni WHERE korisnicko_ime = %s AND lozinka = %s", (u, p))
    if not res.empty:
        st.session_state['ulogovan'] = True
        korisnik_red = next(iter(res.to_dict(orient='records')))
        st.session_state['is_premium'] = int(korisnik_red['is_premium'])
        st.session_state['ime_korisnika'] = korisnik_red['ime_prezime']
        st.query_params["sesija"] = napravi_token(u, p)
        st.switch_page(p_oprema)
    else:
        st.error("❌ Pogrešno korisničko ime ili lozinka!")

if not st.session_state['ulogovan']:
    st.markdown("<style>[data-testid='stSidebar'] {display:none;}</style>", unsafe_allow_html=True)
    st.title("👋 BV Web App")
    st.write("Unesite podatke za pristup sistemu evidencije.")
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("Korisničko ime:", key="korisnik_input")
        st.text_input("Lozinka:", type="password", key="lozinka_input", on_change=izvrsi_prijava)
        if st.button("🚀 PRIJAVI SE", use_container_width=True, type="primary"):
            izvrsi_prijava()
else:
    pg = st.navigation([p_oprema, p_mapa])
    pg.run()
