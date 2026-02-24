import streamlit as st
from supabase import create_client, Client
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io
import datetime
import uuid

# --- 1. SETUP ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Vehicle Protocol Pro", layout="wide", page_icon="🚗")

# Navigation
tab1, tab2 = st.tabs(["📝 Protokoll erstellen / Bearbeiten", "🔍 Archiv & Verwaltung"])

# --- 2. HILFSFUNKTIONEN ---
def upload_photo(file, folder, p_type, is_pil=False):
    """Lädt normale Dateien oder PIL-Bilder (Unterschrift) hoch"""
    if file is None: return None
    try:
        ext = "png" if is_pil else "jpg"
        path = f"{folder}/{datetime.date.today()}_{p_type}_{uuid.uuid4().hex[:5]}.{ext}"
        
        if is_pil:
            # Für die Unterschrift (PIL Image zu Bytes)
            img_byte_arr = io.BytesIO()
            file.save(img_byte_arr, format='PNG')
            content = img_byte_arr.getvalue()
        else:
            # Für normale Kamera-Uploads
            content = file.getvalue()
            
        supabase.storage.from_("vehicle-photos").upload(path, content)
        return supabase.storage.from_("vehicle-photos").get_public_url(path)
    except Exception as e:
        st.error(f"Upload-Fehler ({p_type}): {e}")
        return None

def get_projects():
    try:
        res = supabase.table("projects").select("name").order("name").execute()
        return [p['name'] for p in res.data]
    except: return []

# --- TAB 1: PROTOKOLL ERSTELLEN & BEARBEITEN ---
with tab1:
    is_edit = "edit_id" in st.session_state
    if is_edit:
        st.warning(f"⚠️ BEARBEITUNGSMODUS: {st.session_state.edit_data['vehicles']['license_plate']}")
        if st.button("Bearbeitung abbrechen"):
            del st.session_state["edit_id"]
            del st.session_state["edit_data"]
            st.rerun()
    
    st.title("Fahrzeug-Übergabe")
    
    # 1. Basisdaten
    st.header("1. Basisdaten")
    projekte = get_projects()
    default_p_index = 0
    # Logik für Projekt-Vorauswahl im Edit-Modus
    if is_edit:
        try:
            # Wir suchen das Projekt basierend auf der ID aus den geladenen Daten
            current_p_id = st.session_state.edit_data['vehicles']['project_id']
            p_res = supabase.table("projects").select("name").eq("id", current_p_id).execute()
            if p_res.data:
                p_name_old = p_res.data[0]['name']
                if p_name_old in projekte:
                    default_p_index = projekte.index(p_name_old) + 1
        except: pass

    auswahl_p = st.selectbox("Projekt", ["-- Neues Projekt erstellen --"] + projekte, index=default_p_index)
    p_name = st.text_input("Name des neuen Projekts") if auswahl_p == "-- Neues Projekt erstellen --" else auswahl_p
    
    col1, col2 = st.columns(2)
    with col1:
        k_val = st.session_state.edit_data['vehicles']['license_plate'] if is_edit else ""
        kennzeichen = st.text_input("Kennzeichen", value=k_val).upper().replace(" ", "_")
        vin_val = st.session_state.edit_data['vehicles']['vin'] if is_edit else ""
        vin = st.text_input("VIN (Fahrgestellnummer)", value=vin_val)
        f_val = st.session_state.edit_data['inspector_name'] if is_edit else ""
        fahrer = st.text_input("Fahrer-Name", value=f_val)
    with col2:
        h_val = st.session_state.edit_data['vehicles']['brand_model'] if is_edit else ""
        hersteller = st.text_input("Hersteller/Modell", value=h_val)
        s_val = st.session_state.edit_data['location'] if is_edit else ""
        standort = st.text_input("Standort", value=s_val)
        datum_zeit = st.text_input("Datum & Uhrzeit", value=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))

    # 2. Sichtprüfung & Fotos
    st.header("2. Äußere Sichtprüfung")
    f_v = st.file_uploader("Foto VORNE (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_h = st.file_uploader("Foto HINTEN (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_l = st.file_uploader("Foto LINKS (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_r = st.file_uploader("Foto RECHTS (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_s = st.file_uploader("Fahrzeugschein (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_schaden1 = st.file_uploader("Schaden Foto 1 (Optional)", type=['jpg', 'jpeg', 'png'])
    f_schaden2 = st.file_uploader("Schaden Foto 2 (Optional)", type=['jpg', 'jpeg', 'png'])

    # 3. Innenraum & Zubehör
    st.header("3. Innenraum & Zubehör")
    old_cl = st.session_state.edit_data['condition_data'].get('checkliste', {}) if is_edit else {}
    c_in1, c_in2 = st.columns(2)
    with c_in1:
        c_floor = st.toggle("Boden sauber", old_cl.get('floor', True))
        c_seats = st.toggle("Sitze sauber", old_cl.get('seats', True))
        c_covers = st.toggle("Innenverkleidung", old_cl.get('covers', True))
    with c_in2:
        z_aid = st.toggle("Verbandskasten", old_cl.get('aid_kit', True))
        z_cable = st.toggle("Ladekabel", old_cl.get('cable', False))
        z_card = st.toggle("Versicherung/Ladekarte", old_cl.get('card', True))

    # 4. Betriebsstoffe
    st.header("4. Betriebsstoffe")
    f_lvl = st.session_state.edit_data['fuel_level'] if is_edit else 50
    fuel = st.slider("Kraftstoff (%)", 0, 100, f_lvl)
    batt_lvl = st.session_state.edit_data['condition_data'].get('battery', 100) if is_edit else 100
    battery = st.slider("Batterie (%)", 0, 100, batt_lvl)
    km_val = st.session_state.edit_data['odometer'] if is_edit else 0
    km = st.number_input("Kilometerstand", min_value=0, value=km_val)

    # 5. Abschluss & Unterschrift
    st.header("5. Abschluss & Unterschrift")
    bem_val = st.session_state.edit_data['remarks'] if is_edit else ""
    bemerkung = st.text_area("Bemerkungen", value=bem_val)
    
    st.write("Bitte hier unterschreiben:")
    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=3,
        stroke_color="#000000",
        background_color="#eeeeee",
        height=150,
        key="canvas",
    )
    
    sign_confirm = st.checkbox("Ich bestätige die Richtigkeit der Angaben")

    if st.button("PROTOKOLL SPEICHERN", use_container_width=True):
        if not kennzeichen or not p_name:
            st.error("Kennzeichen und Projekt sind Pflicht!")
        elif not sign_confirm:
            st.error("Bitte Bestätigungs-Häkchen setzen!")
        else:
            with st.spinner("Verarbeite Daten und Bilder..."):
                try:
                    # Projekt & Fahrzeug IDs (on_conflict verhindert Fehler bei Duplikaten)
                    supabase.table("projects").upsert({"name": p_name}, on_conflict="name").execute()
                    p_id = supabase.table("projects").select("id").eq("name", p_name).execute().data[0]['id']
                    
                    v_res = supabase.table("vehicles").upsert({
                        "project_id": p_id, "license_plate": kennzeichen, "brand_model": hersteller, "vin": vin
                    }, on_conflict="license_plate").execute()
                    v_id = v_res.data[0]['id']

                    path = f"{p_name}/{kennzeichen}"
                    urls = st.session_state.edit_data['condition_data'].get('photos', {}) if is_edit else {}
                    
                    # Fotos hochladen (nur wenn neue Dateien gewählt wurden)
                    for key, file in [("v", f_v), ("h", f_h), ("l", f_l), ("r", f_r), ("s", f_s), ("sch1", f_schaden1), ("sch2", f_schaden2)]:
                        if file: urls[key] = upload_photo(file, path, key)

                    # Unterschrift verarbeiten
                    if canvas_result.image_data is not None:
                        im = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
                        urls["signature"] = upload_photo(im, path, "sign", is_pil=True)

                    proto_payload = {
                        "vehicle_id": v_id,
                        "inspector_name": fahrer,
                        "location": standort,
                        "odometer": km,
                        "fuel_level": fuel,
                        "remarks": bemerkung,
                        "condition_data": {
                            "battery": battery, "photos": urls,
                            "checkliste": {"floor": c_floor, "seats": c_seats, "covers": c_covers, "aid_kit": z_aid, "cable": z_cable, "card": z_card}
                        }
                    }

                    if is_edit:
                        supabase.table("protocols").update(proto_payload).eq("id", st.session_state.edit_id).execute()
                        st.success("Protokoll aktualisiert!")
                        del st.session_state["edit_id"]
                    else:
                        supabase.table("protocols").insert(proto_payload).execute()
                        st.success("Protokoll neu angelegt!")
                    
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")

# --- TAB 2: ARCHIV & VERWALTUNG ---
with tab2:
    st.title("Archiv & Verwaltung")
    search_q = st.text_input("Kennzeichen suchen").upper()
    
    results = supabase.table("protocols").select("*, vehicles(*)").order("created_at", desc=True).execute().data
    
    for r in results:
        plate = r['vehicles']['license_plate']
        if search_q in plate:
            with st.expander(f"📄 {r['created_at'][:10]} | {plate}"):
                st.write(f"**KM:** {r['odometer']} | **Sprit/Akku:** {r['fuel_level']}% / {r['condition_data'].get('battery')}%")
                
                c1, c2 = st.columns(2)
                with c1:
                    if st.button(f"Bearbeiten", key=f"ed_{r['id']}"):
                        st.session_state.edit_id = r['id']
                        st.session_state.edit_data = r
                        st.rerun()
                with c2:
                    if st.button(f"Löschen", key=f"del_{r['id']}"):
                        supabase.table("protocols").delete().eq("id", r['id']).execute()
                        st.rerun()
                
                # Zeige Bilder inkl. Unterschrift
                photos = r['condition_data'].get('photos', {})
                if photos:
                    st.write("**Bilder & Unterschrift:**")
                    st.image([url for url in photos.values() if url], width=120)
