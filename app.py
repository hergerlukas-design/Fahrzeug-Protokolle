import streamlit as st
from supabase import create_client, Client
import datetime
import uuid

# --- VERBINDUNG ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Vehicle Protocol Pro", layout="wide")

# Tabs für die Navigation
tab1, tab2 = st.tabs(["📝 Neues Protokoll", "🔍 Archiv & Suche"])

# --- FUNKTIONEN ---
def upload_photo(file, folder, p_type):
    if file is None: return None
    path = f"{folder}/{datetime.date.today()}_{p_type}_{uuid.uuid4().hex[:5]}.jpg"
    supabase.storage.from_("vehicle-photos").upload(path, file.getvalue())
    return supabase.storage.from_("vehicle-photos").get_public_url(path)

def get_projects():
    res = supabase.table("projects").select("name").execute()
    return [p['name'] for p in res.data]

# --- TAB 1: PROTOKOLL ERSTELLEN ---
with tab1:
    st.title("Fahrzeug-Übergabeprotokoll")
    
    # ABSCHNITT 1: Basisdaten
    st.header("1. Basisdaten")
    projekte = get_projects()
    auswahl_p = st.selectbox("Projekt", ["-- Neu --"] + projekte)
    p_name = st.text_input("Neues Projekt Name") if auswahl_p == "-- Neu --" else auswahl_p
    
    col1, col2 = st.columns(2)
    with col1:
        kennzeichen = st.text_input("Kennzeichen").upper()
        vin = st.text_input("VIN (Fahrgestellnummer)")
        fahrer = st.text_input("Fahrer-Name (Übernahme durch)")
    with col2:
        hersteller = st.text_input("Hersteller/Modell")
        standort = st.text_input("Standort (Übergabeort)")
        datum_zeit = st.text_input("Datum & Uhrzeit", value=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))

    # ABSCHNITT 2: Sichtprüfung Außen
    st.header("2. Äußere Sichtprüfung")
    erschwert = st.multiselect("Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"])
    
    st.write("Pflicht-Fotos (Rundumblick)")
    f_v = st.file_uploader("Vorne", type=['jpg'])
    f_h = st.file_uploader("Hinten", type=['jpg'])
    f_l = st.file_uploader("Links", type=['jpg'])
    f_r = st.file_uploader("Rechts", type=['jpg'])
    f_s = st.file_uploader("Fahrzeugschein", type=['jpg'])

    # ABSCHNITT 3: Innenraum & Zubehör
    st.header("3. Innenraum & Zubehör")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Sauberkeit (OK?)")
        clean_floor = st.toggle("Boden", True)
        clean_seats = st.toggle("Sitze", True)
        clean_interieur = st.toggle("Innenverkleidung", True)
        clean_instr = st.toggle("Armaturen", True)
        clean_trunk = st.toggle("Kofferraum", True)
    with c2:
        st.subheader("Zubehör (Dabei?)")
        has_aid = st.toggle("Verbandskasten", True)
        has_tri = st.toggle("Warndreieck", True)
        has_vest = st.toggle("Warnweste", True)
        has_cable = st.toggle("Ladekabel", False)
        has_card = st.toggle("Ladekarte/Versicherung", True)

    # ABSCHNITT 4: Füllstände
    st.header("4. Betriebsstoffe")
    fuel = st.slider("Kraftstoff/Batterie %", 0, 100, 50)
    km = st.number_input("Kilometerstand", min_value=0)
    water = st.select_slider("Kühlwasser", options=["Warnung", "OK"], value="OK")

    # ABSCHNITT 5: Abschluss
    st.header("5. Abschluss")
    bemerkung = st.text_area("Bemerkungen (Schäden/Details)")
    st.warning("Bestätigung: Fahrzeug wie beschrieben übernommen.")
    # Hinweis: Echtes Sign-Pad braucht extra Komponente, hier nutzen wir Checkbox als Ersatz
    sign_confirm = st.checkbox("Ich bestätige die Angaben digital")

    if st.button("PROTOKOLL SPEICHERN", use_container_width=True):
        if not (f_v and f_h and f_l and f_r and f_s and kennzeichen):
            st.error("Bitte alle Pflichtfotos und Kennzeichen ausfüllen!")
        else:
            with st.spinner("Speichere..."):
                # 1. Projekt/Auto anlegen
                if auswahl_p == "-- Neu --":
                    supabase.table("projects").upsert({"name": p_name}).execute()
                
                p_id = supabase.table("projects").select("id").eq("name", p_name).execute().data[0]['id']
                v_res = supabase.table("vehicles").upsert({"project_id": p_id, "license_plate": kennzeichen, "brand_model": hersteller, "vin": vin}).execute()
                v_id = v_res.data[0]['id']

                # 2. Bilder hochladen
                f_path = f"{p_name}/{kennzeichen}"
                urls = {
                    "v": upload_photo(f_v, f_path, "vorne"),
                    "h": upload_photo(f_h, f_path, "hinten"),
                    "l": upload_photo(f_l, f_path, "links"),
                    "r": upload_photo(f_r, f_path, "rechts"),
                    "s": upload_photo(f_s, f_path, "schein")
                }

                # 3. Protokoll
                supabase.table("protocols").insert({
                    "vehicle_id": v_id,
                    "inspector_name": fahrer,
                    "location": standort,
                    "odometer": km,
                    "fuel_level": fuel,
                    "remarks": bemerkung,
                    "condition_data": {"checkliste": "OK", "photos": urls, "water": water, "conditions": erschwert}
                }).execute()
                st.success("Gespeichert!")

# --- TAB 2: ARCHIV & SUCHE ---
with tab2:
    st.title("Archiv")
    search_q = st.text_input("Nach Kennzeichen suchen").upper()
    
    # Daten laden
    query = supabase.table("protocols").select("*, vehicles(*)").order("created_at", desc=True)
    results = query.execute().data

    for r in results:
        plate = r['vehicles']['license_plate']
        if search_q in plate:
            with st.expander(f"{r['created_at'][:10]} - {plate} ({r['vehicles']['brand_model']})"):
                st.write(f"**Projekt:** {r['vehicles'].get('project_id', 'Unbekannt')}")
                st.write(f"**Fahrer:** {r['inspector_name']} | **KM:** {r['odometer']}")
                st.write(f"**Bemerkung:** {r['remarks']}")
                
                # Bilder anzeigen
                photos = r['condition_data'].get('photos', {})
                if photos:
                    cols = st.columns(5)
                    for i, (name, url) in enumerate(photos.items()):
                        cols[i].image(url, caption=name)
