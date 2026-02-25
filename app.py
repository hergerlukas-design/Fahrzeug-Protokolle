import streamlit as st
from supabase import create_client, Client
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io
import datetime
import uuid
import requests
from fpdf import FPDF

# --- 1. SETUP ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Vehicle Protocol Pro", layout="wide", page_icon="🚗")

# OPTIMIERTES CSS: Fixierte Tabs, die im Hell- und Dunkelmodus funktionieren
st.markdown("""
    <style>
        div[data-testid="stTabs"] > div:first-child {
            position: sticky;
            top: 0;
            /* Nutzt die Hintergrundfarbe des Themes oder Glas-Effekt */
            background-color: rgba(255, 255, 255, 0.05); 
            backdrop-filter: blur(10px);
            z-index: 999;
            padding-top: 10px;
            border-bottom: 1px solid rgba(128, 128, 128, 0.2);
        }
    </style>
""", unsafe_allow_html=True)

# Navigation Tabs
tab1, tab2 = st.tabs(["📝 Protokoll erstellen / Bearbeiten", "🔍 Archiv & Verwaltung"])

# --- 2. HILFSFUNKTIONEN ---
def upload_photo(file, folder, p_type, is_pil=False):
    if file is None: return None
    try:
        ext = "png" if is_pil else "jpg"
        path = f"{folder}/{datetime.date.today()}_{p_type}_{uuid.uuid4().hex[:5]}.{ext}"
        if is_pil:
            img_byte_arr = io.BytesIO()
            file.save(img_byte_arr, format='PNG')
            content = img_byte_arr.getvalue()
        else:
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

def create_pdf(data):
    """Erstellt ein professionelles PDF inkl. Bemerkungen, Fotos und Unterschrift"""
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, "Fahrzeug-Übergabeprotokoll", ln=True, align="C")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 10, f"Erstellt am: {data['created_at'][:10]}", ln=True, align="R")
    
    # 1. Basisdaten
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "1. Basisdaten", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(95, 8, f"Kennzeichen: {data['vehicles']['license_plate']}", border=1)
    pdf.cell(95, 8, f"Modell: {data['vehicles']['brand_model']}", border=1, ln=True)
    pdf.cell(95, 8, f"VIN: {data['vehicles']['vin']}", border=1)
    pdf.cell(95, 8, f"Ersteller: {data['inspector_name']}", border=1, ln=True)
    pdf.cell(95, 8, f"KM-Stand: {data['odometer']} KM", border=1)
    pdf.cell(95, 8, f"Standort: {data['location']}", border=1, ln=True)
    
    # 2. Technik & Füllstände
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "2. Technik & Betriebsstoffe", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(63, 8, f"Kraftstoff: {data['fuel_level']}%", border=1)
    pdf.cell(63, 8, f"Batterie: {data['condition_data'].get('battery', 0)}%", border=1)
    pdf.cell(64, 8, f"Bedingungen: {', '.join(data['condition_data'].get('conditions', []))}", border=1, ln=True)
    
    # 3. Checkliste
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "3. Checkliste (Zustand & Zubehör)", ln=True)
    pdf.set_font("helvetica", "", 9)
    cl = data['condition_data'].get('checkliste', {})
    uebersetzung = {
        "floor": "Boden sauber", "seats": "Sitze sauber", "entry": "Einstiege",
        "instruments": "Armaturen OK", "trunk": "Kofferraum sauber", "engine": "Motorraum OK",
        "aid_kit": "Verbandskasten", "triangle": "Warndreieck", "vest": "Warnweste",
        "cable": "Ladekabel", "registration": "Fahrzeugschein", "card": "Ladekarte/Versicherung"
    }
    items = list(cl.items())
    for i in range(0, len(items), 2):
        k1, v1 = items[i]
        pdf.cell(95, 7, f"{uebersetzung.get(k1, k1)}: {'OK' if v1 else 'Nicht OK'}", border=1)
        if i+1 < len(items):
            k2, v2 = items[i+1]
            pdf.cell(95, 7, f"{uebersetzung.get(k2, k2)}: {'OK' if v2 else 'Nicht OK'}", border=1, ln=True)
        else: pdf.ln(7)

    # 4. Bemerkungen (ÜBERNAHME INS PDF)
    if data.get('remarks'):
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "4. Bemerkungen", ln=True)
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(190, 8, data['remarks'], border=1)

    # 5. Schäden Tabelle
    damage_list = data['condition_data'].get('damage_records', [])
    if damage_list:
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "5. Erfasste Schäden", ln=True)
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(60, 7, "Position", border=1)
        pdf.cell(60, 7, "Art", border=1)
        pdf.cell(70, 7, "Intensität", border=1, ln=True)
        pdf.set_font("helvetica", "", 9)
        for d in damage_list:
            pdf.cell(60, 7, d['pos'], border=1)
            pdf.cell(60, 7, d['type'], border=1)
            pdf.cell(70, 7, d['int'], border=1, ln=True)

    # 6. Fotos mit Randabstand
    photos = data['condition_data'].get('photos', {})
    if photos:
        pdf.add_page()
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "6. Fotodokumentation", ln=True)
        y_pos, col = 30, 0
        x_positions = [10, 105]
        for p_label, p_url in photos.items():
            if p_url and p_label != "signature":
                try:
                    img_data = requests.get(p_url).content
                    pdf.image(io.BytesIO(img_data), x=x_positions[col] + 3.5, y=y_pos + 3.5, w=83) 
                    pdf.set_xy(x_positions[col], y_pos + 62)
                    pdf.cell(90, 5, p_label.capitalize(), align="C")
                    col += 1
                    if col > 1: col = 0; y_pos += 75
                    if y_pos > 230: pdf.add_page(); y_pos = 20
                except: pass

    # 7. Unterschrift
    if "signature" in photos and photos["signature"]:
        if pdf.get_y() > 220: pdf.add_page()
        pdf.ln(10)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "7. Bestätigung & Unterschrift", ln=True)
        try:
            sig_data = requests.get(photos["signature"]).content
            pdf.image(io.BytesIO(sig_data), w=60)
        except: pass

    return bytes(pdf.output())

# --- TAB 1: PROTOKOLL ERSTELLEN ---
with tab1:
    is_edit = "edit_id" in st.session_state
    if is_edit:
        st.warning(f"⚠️ Bearbeitungsmodus: {st.session_state.edit_data['vehicles']['license_plate']}")
        if st.button("Abbrechen"):
            del st.session_state["edit_id"]; st.rerun()
    
    st.title("Fahrzeug-Übergabe")
    
    st.header("1. Basisdaten")
    projekte = get_projects()
    auswahl_p = st.selectbox("Projekt", ["-- Neues Projekt erstellen --"] + projekte)
    p_name = st.text_input("Projektname") if auswahl_p == "-- Neues Projekt erstellen --" else auswahl_p
    
    col1, col2 = st.columns(2)
    with col1:
        k_val = st.session_state.edit_data['vehicles']['license_plate'] if is_edit else ""
        kennzeichen = st.text_input("Kennzeichen", value=k_val).upper()
        vin_val = st.session_state.edit_data['vehicles']['vin'] if is_edit else ""
        vin = st.text_input("VIN", value=vin_val)
        f_val = st.session_state.edit_data['inspector_name'] if is_edit else ""
        fahrer = st.text_input("Ersteller", value=f_val)
    with col2:
        h_val = st.session_state.edit_data['vehicles']['brand_model'] if is_edit else ""
        hersteller = st.text_input("Modell", value=h_val)
        s_val = st.session_state.edit_data['location'] if is_edit else ""
        standort = st.text_input("Standort", value=s_val)
        datum_zeit = st.text_input("Datum", value=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))

    st.header("2. Sichtprüfung & Schadenserfassung")
    erschwert = st.multiselect("Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"])
    
    st.subheader("Pflicht-Fotos (Rundumblick)")
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        f_v = st.file_uploader("Vorne", type=['jpg','png'])
        f_l = st.file_uploader("Links", type=['jpg','png'])
        f_s = st.file_uploader("Hinten", type=['jpg','png'])
    with c_f2:
        f_h = st.file_uploader("Rechts", type=['jpg','png'])
        f_r = st.file_uploader("Schein", type=['jpg','png'])

    st.subheader("🛠️ Schäden erfassen")
    if "damage_count" not in st.session_state: st.session_state.damage_count = 0
    if st.button("+ Neuen Schaden hinzufügen"):
        st.session_state.damage_count += 1

    damage_records, damage_photos = [], {}
    for i in range(st.session_state.damage_count):
        with st.expander(f"Schaden #{i+1}", expanded=True):
            d1, d2 = st.columns(2)
            with d1:
                pos = st.selectbox(f"Position", ["Stoßfänger vorne", "Stoßfänger hinten", "Motorhaube", "Dach", "Tür VL", "Tür VR", "Felge VL", "Felge VR", "Felge HL", "Felge HR"], key=f"pos_{i}")
                dtype = st.radio(f"Art", ["Kratzer", "Delle", "Steinschlag", "Riss", "Fehlteil"], key=f"type_{i}", horizontal=True)
            with d2:
                intens = st.select_slider(f"Intensität", options=["Oberflächlich", "Bis Grundierung", "Deformiert"], key=f"int_{i}")
                d_photo = st.file_uploader(f"Foto Schaden #{i+1}", type=['jpg','png'], key=f"photo_{i}")
                if d_photo: damage_photos[f"schaden_{i+1}"] = d_photo
            damage_records.append({"pos": pos, "type": dtype, "int": intens})

    st.header("3. Checkliste")
    old_cl = st.session_state.edit_data['condition_data'].get('checkliste', {}) if is_edit else {}
    c1, c2 = st.columns(2)
    with c1:
        c_floor = st.toggle("Boden sauber", old_cl.get('floor', True))
        c_seats = st.toggle("Sitze sauber", old_cl.get('seats', True))
        c_covers = st.toggle("Einstiege", old_cl.get('entry', True))
        c_instr = st.toggle("Armaturen", old_cl.get('instruments', True))
        c_trunk = st.toggle("Kofferraum sauber", old_cl.get('trunk', True))
        c_engine = st.toggle("Motorraum", old_cl.get('engine', True))
    with c2:
        z_aid = st.toggle("Verbandskasten", old_cl.get('aid_kit', True))
        z_tri = st.toggle("Warndreieck", old_cl.get('triangle', True))
        z_vest = st.toggle("Warnweste", old_cl.get('vest', True))
        z_cable = st.toggle("Ladekabel", old_cl.get('cable', False))
        z_reg = st.toggle("Fahrzeugschein", old_cl.get('registration', True))
        z_card = st.toggle("Ladekarte", old_cl.get('card', True))

    st.header("4. Betriebsstoffe")
    fuel = st.slider("Kraftstoff %", 0, 100, 50)
    battery = st.slider("Batterie %", 0, 100, 100)
    km = st.number_input("Kilometer", min_value=0)

    st.header("5. Abschluss")
    bemerkung = st.text_area("Bemerkungen")
    canvas_result = st_canvas(fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3, stroke_color="#000000", background_color="#eeeeee", height=150, key="canvas")
    confirm = st.checkbox("Ich bestätige die Richtigkeit der Angaben")

    if st.button("SPEICHERN", use_container_width=True):
        if not (kennzeichen and p_name and confirm): st.error("Pflichtfelder ausfüllen!")
        else:
            with st.spinner("Speichere..."):
                try:
                    supabase.table("projects").upsert({"name": p_name}, on_conflict="name").execute()
                    p_id = supabase.table("projects").select("id").eq("name", p_name).execute().data[0]['id']
                    v_res = supabase.table("vehicles").upsert({"project_id": p_id, "license_plate": kennzeichen, "brand_model": hersteller, "vin": vin}, on_conflict="license_plate").execute()
                    v_id = v_res.data[0]['id']
                    path = f"{p_name}/{kennzeichen}"
                    urls = st.session_state.edit_data['condition_data'].get('photos', {}) if is_edit else {}
                    for k, f in [("vorne",f_v),("hinten",f_h),("links",f_l),("rechts",f_r),("schein",f_s)]:
                        if f: urls[k] = upload_photo(f, path, k)
                    for k, f in damage_photos.items(): urls[k] = upload_photo(f, path, k)
                    if canvas_result.image_data is not None:
                        im = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
                        urls["signature"] = upload_photo(im, path, "sign", is_pil=True)

                    payload = {"vehicle_id": v_id, "inspector_name": fahrer, "location": standort, "odometer": km, "fuel_level": fuel, "remarks": bemerkung, "condition_data": {"battery": battery, "photos": urls, "conditions": erschwert, "damage_records": damage_records, "checkliste": {"floor": c_floor, "seats": c_seats, "entry": c_covers, "instruments": c_instr, "trunk": c_trunk, "engine": c_engine, "aid_kit": z_aid, "triangle": z_tri, "vest": z_vest, "cable": z_cable, "registration": z_reg, "card": z_card}}}
                    if is_edit: supabase.table("protocols").update(payload).eq("id", st.session_state.edit_id).execute()
                    else: supabase.table("protocols").insert(payload).execute()
                    st.success("Erfolgreich!"); st.session_state.damage_count = 0; st.rerun()
                except Exception as e: st.
                    
