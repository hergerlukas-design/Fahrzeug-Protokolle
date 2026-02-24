import streamlit as st
from supabase import create_client, Client
import datetime
import uuid

# --- 1. VERBINDUNG & SETUP ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Vehicle Protocol Pro", layout="wide", page_icon="🚗")

# Navigation
tab1, tab2 = st.tabs(["📝 Protokoll erstellen", "🔍 Archiv & Bearbeitung"])

# --- 2. HILFSFUNKTIONEN ---
def upload_photo(file, folder, p_type):
    if file is None: return None
    try:
        path = f"{folder}/{datetime.date.today()}_{p_type}_{uuid.uuid4().hex[:5]}.jpg"
        supabase.storage.from_("vehicle-photos").upload(path, file.getvalue())
        return supabase.storage.from_("vehicle-photos").get_public_url(path)
    except:
        return None

def get_projects():
    try:
        res = supabase.table("projects").select("name").execute()
        return [p['name'] for p in res.data]
    except: return []

# --- TAB 1: PROTOKOLL ERSTELLEN ---
with tab1:
    st.title("Neues Übergabeprotokoll")
    
    # 1. Basisdaten
    st.header("1. Basisdaten")
    projekte = get_projects()
    auswahl_p = st.selectbox("Projekt", ["-- Neues Projekt erstellen --"] + projekte)
    
    if auswahl_p == "-- Neues Projekt erstellen --":
        p_name = st.text_input("Name des neuen Projekts")
    else:
        p_name = auswahl_p
    
    col1, col2 = st.columns(2)
    with col1:
        kennzeichen = st.text_input("Kennzeichen").upper().replace(" ", "_")
        vin = st.text_input("VIN (Fahrgestellnummer)")
        fahrer = st.text_input("Fahrer-Name")
    with col2:
        hersteller = st.text_input("Hersteller/Modell")
        standort = st.text_input("Standort (Übergabeort)")
        datum_zeit = st.text_input("Datum & Uhrzeit", value=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))

    # 2. Sichtprüfung & Fotos
    st.header("2. Äußere Sichtprüfung")
    erschwert = st.multiselect("Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"])
    
    st.subheader("Pflicht-Fotos")
    c_f1, c_f2, c_f3 = st.columns(3)
    with c_f1:
        f_v = st.file_uploader("Foto VORNE", type=['jpg', 'jpeg', 'png'])
        f_h = st.file_uploader("Foto HINTEN", type=['jpg', 'jpeg', 'png'])
    with c_f2:
        f_l = st.file_uploader("Foto LINKS", type=['jpg', 'jpeg', 'png'])
        f_r = st.file_uploader("Foto RECHTS", type=['jpg', 'jpeg', 'png'])
    with c_f3:
        f_s = st.file_uploader("Fahrzeugschein", type=['jpg', 'jpeg', 'png'])

    st.subheader("Zusätzliche Schadensfotos (Optional)")
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        f_schaden1 = st.file_uploader("Schaden Foto 1", type=['jpg', 'jpeg', 'png'])
    with col_s2:
        f_schaden2 = st.file_uploader("Schaden Foto 2", type=['jpg', 'jpeg', 'png'])

    # 3. Innenraum & Zubehör
    st.header("3. Innenraum & Zubehör")
    c_in1, c_in2 = st.columns(2)
    with c_in1:
        st.subheader("Sauberkeit / Zustand")
        c_floor = st.toggle("Boden (Floor) sauber", True)
        c_seats = st.toggle("Sitze (Seats) sauber", True)
        c_covers = st.toggle("Innenverkleidung sauber", True)
        c_instr = st.toggle("Armaturen/Instrumente OK", True)
        c_trunk = st.toggle("Kofferraum sauber", True)
        c_engine = st.toggle("Motorraum OK", True)
    with c_in2:
        st.subheader("Zubehör")
        z_aid = st.toggle("Verbandskasten", True)
        z_tri = st.toggle("Warndreieck", True)
        z_vest = st.toggle("Warnweste", True)
        z_cable = st.toggle("Ladekabel", False)
        z_reg = st.toggle("Zulassungsbescheinigung", True)
        z_card = st.toggle("Versicherung/Ladekarte", True)

    # 4. Betriebsstoffe (Hybrid & Elektro Fokus)
    st.header("4. Betriebsstoffe")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        fuel = st.slider("Kraftstoff-Stand (%)", 0, 100, 50)
        km = st.number_input("Kilometerstand (KM)", min_value=0)
    with col_b2:
        battery = st.slider("Batterie-Stand (%)", 0, 100, 100)

    # 5. Abschluss
    st.header("5. Abschluss")
    bemerkung = st.text_area("Bemerkungen (Remarks)")
    st.info("Bestätigung: Fahrzeug wie beschrieben übernommen.")
    sign_confirm = st.checkbox("Ich bestätige die Angaben")

    if st.button("PROTOKOLL SPEICHERN", use_container_width=True):
        if not (f_v and f_h and f_l and f_r and f_s and kennzeichen and p_name):
            st.error("Bitte alle Pflichtfotos, Kennzeichen und Projekt angeben!")
        elif not sign_confirm:
            st.error("Bitte die Bestätigung anklicken!")
        else:
            with st.spinner("Protokoll wird gespeichert..."):
                try:
                    if auswahl_p == "-- Neues Projekt erstellen --":
                        supabase.table("projects").upsert({"name": p_name}).execute()
                    
                    p_id = supabase.table("projects").select("id").eq("name", p_name).execute().data[0]['id']
                    v_res = supabase.table("vehicles").upsert({
                        "project_id": p_id, "license_plate": kennzeichen, 
                        "brand_model": hersteller, "vin": vin
                    }).execute()
                    v_id = v_res.data[0]['id']

                    # Foto Upload
                    path = f"{p_name}/{kennzeichen}"
                    urls = {
                        "vorne": upload_photo(f_v, path, "v"),
                        "hinten": upload_photo(f_h, path, "h"),
                        "links": upload_photo(f_l, path, "l"),
                        "rechts": upload_photo(f_r, path, "r"),
                        "schein": upload_photo(f_s, path, "s"),
                        "schaden1": upload_photo(f_schaden1, path, "sch1"),
                        "schaden2": upload_photo(f_schaden2, path, "sch2")
                    }

                    # Protokoll Speichern
                    supabase.table("protocols").insert({
                        "vehicle_id": v_id,
                        "inspector_name": fahrer,
                        "location": standort,
                        "odometer": km,
                        "fuel_level": fuel,
                        "remarks": bemerkung,
                        "condition_data": {
                            "battery": battery,
                            "photos": urls,
                            "conditions": erschwert,
                            "checkliste": {
                                "floor": c_floor, "seats": c_seats, "covers": c_covers,
                                "instruments": c_instr, "trunk": c_trunk, "engine": c_engine,
                                "aid_kit": z_aid, "triangle": z_tri, "vest": z_vest,
                                "cable": z_cable, "registration": z_reg, "card": z_card
                            }
                        }
                    }).execute()
                    st.success("✅ Erfolgreich im Archiv gespeichert!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Fehler beim Speichern: {e}")

# --- TAB 2: ARCHIV & SUCHE ---
with tab2:
    st.title("Archiv & Suche")
    search_q = st.text_input("Kennzeichen suchen").upper()
    
    # Refresh Button
    if st.button("Daten aktualisieren"):
        st.rerun()

    # Daten laden
    try:
        results = supabase.table("protocols").select("*, vehicles(*)").order("created_at", desc=True).execute().data
        
        for r in results:
            plate = r['vehicles']['license_plate']
            if search_q in plate:
                with st.expander(f"📄 {r['created_at'][:10]} | {plate} | {r['vehicles']['brand_model']}"):
                    # Layout im Archiv
                    col_det1, col_det2 = st.columns(2)
                    with col_det1:
                        st.write("**BASISDATEN**")
                        st.write(f"Fahrer: {r['inspector_name']}")
                        st.write(f"Standort: {r['location']}")
                        st.write(f"VIN: {r['vehicles']['vin']}")
                        st.write(f"Bedingungen: {', '.join(r['condition_data'].get('conditions', []))}")
                    with col_det2:
                        st.write("**TECHNIK & FÜLLSTÄNDE**")
                        st.write(f"KM-Stand: {r['odometer']} KM")
                        st.write(f"Kraftstoff: {r['fuel_level']}%")
                        st.write(f"Batterie: {r['condition_data'].get('battery')}%")

                    st.write("---")
                    st.write("**CHECKLISTE (Zustand & Zubehör)**")
                    cl = r['condition_data'].get('checkliste', {})
                    c_cols = st.columns(3)
                    # Alle Checkbox-Werte ausgeben
                    for i, (item, val) in enumerate(cl.items()):
                        c_cols[i % 3].write(f"{'✅' if val else '❌'} {item.capitalize()}")

                    st.write("---")
                    st.write(f"**Bemerkungen:** {r['remarks']}")

                    # Fotos anzeigen
                    st.write("**FOTO-DOKUMENTATION**")
                    photos = r['condition_data'].get('photos', {})
                    if photos:
                        active_p = {k: v for k, v in photos.items() if v}
                        p_cols = st.columns(4)
                        for i, (p_name, p_url) in enumerate(active_p.items()):
                            p_cols[i % 4].image(p_url, caption=p_name, use_container_width=True)
                    
                    st.write("---")
                    st.info("Bearbeitungs-Funktion wird in Kürze freigeschaltet (Daten sind schreibgeschützt).")
    except Exception as e:
        st.error(f"Fehler beim Laden der Daten: {e}")
    
