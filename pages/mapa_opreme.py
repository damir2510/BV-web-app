import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from db_utils import run_query

st.set_page_config(page_title="Mapa Opreme", layout="wide")

st.markdown("""
    <style>
        [data-testid="stSidebarNav"] ul { display: none; }
        .stMain { padding: 0rem; }
    </style>
""", unsafe_allow_html=True)

if 'ulogovan' not in st.session_state or not st.session_state['ulogovan']:
    st.switch_page("glavna.py")
    st.stop()

if st.sidebar.button("⬅️ Nazad na Pregled", use_container_width=True):
    st.switch_page("pages/oprema.py")

st.title("📍 Interaktivna Mapa Opreme")

query = "SELECT id, inventarni_broj, vrsta_opreme, naziv_proizvodjac, gps_koordinate, trenutni_radnik, status, zadnja_lokacija, sektor FROM oprema"
df_all = run_query(query)

if not df_all.empty:
    search = st.text_input("🔍 Pretraži mapu (Sektor, Radnik ili Model):", "").lower()

    df = df_all.copy()
    if search:
        mask = df.astype(str).apply(lambda x: x.str.lower().str.contains(search)).any(axis=1)
        df = df[mask]

    locations = []
    for _, row in df.iterrows():
        gps = row.get('gps_koordinate')
        if gps and "," in str(gps):
            try:
                parts = str(gps).replace(' ', '').split(',')
                lat = float(parts.pop(0))
                lon = float(parts.pop(0))
                locations.append({
                    'lat': lat,
                    'lon': lon,
                    'info': f"<b>Inv:</b> {row['inventarni_broj']}<br><b>Model:</b> {row['naziv_proizvodjac']}",
                    'radnik': row.get('trenutni_radnik', '-'),
                    'status': str(row.get('status', '')).lower(),
                    'grad': row.get('zadnja_lokacija', '-')
                })
            except Exception:
                continue

    if locations:
        prva = next(iter(locations))
        m = folium.Map(location=(prva['lat'], prva['lon']), zoom_start=8, control_scale=True)

        for loc in locations:
            color = 'green' if any(x in loc['status'] for x in ['rad', 'ispravno', 'u radu']) else 'red'
            popup_html = f"<div style='width:200px;'>{loc['info']}<br><b>Lokacija:</b> {loc['grad']}<br><b>Zadužio:</b> {loc['radnik']}</div>"
            folium.Marker(
                (loc['lat'], loc['lon']),
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color=color, icon='info-sign')
            ).add_to(m)

        st_folium(m, width=1500, height=620, returned_objects=[])
    else:
        st.warning("Nema rezultata za vašu pretragu ili fale GPS koordinate.")

    # --- ISTORIJA PROVERA ZA IZABRANI APARAT ---
    st.markdown("---")
    st.subheader("📋 Istorija terenskih provera")

    opcije_aparata = ["-- Izaberi aparat za prikaz istorije provera --"] + [
        f"{r['inventarni_broj']} | {r.get('vrsta_opreme', '')} {r.get('naziv_proizvodjac', '')}"
        for _, r in df_all.iterrows()
    ]
    izbor_ap = st.selectbox("Aparat:", opcije_aparata)

    if izbor_ap != "-- Izaberi aparat za prikaz istorije provera --":
        inv_odabrani = izbor_ap.split("|").pop(0).strip()
        red_ap = df_all[df_all['inventarni_broj'].astype(str) == inv_odabrani]
        if not red_ap.empty:
            oprema_id_val = int(next(iter(red_ap.to_dict(orient='records')))['id'])
            df_prov = run_query(
                "SELECT datum_provere, radnik_ime, lokacija_naziv, gps_koordinate FROM istorija_provera WHERE oprema_id = %s ORDER BY datum_provere DESC",
                (oprema_id_val,)
            )
            if not df_prov.empty:
                st.dataframe(df_prov, use_container_width=True, hide_index=True)
            else:
                st.info(f"Nema zabeleženih terenskih provera za aparat {inv_odabrani}.")
else:
    st.info("Baza je prazna.")
