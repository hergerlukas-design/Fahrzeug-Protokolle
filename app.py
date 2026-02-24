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
    """Erstellt ein PDF-Dokument mit allen Details und Bildern"""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, "Fahrzeug-Übergabeprotokoll", ln=True, align="C")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 10, f"Erstellt am: {data['created_at'][:10]}", ln=True, align="R")
    
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "1. Basisdaten", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(95, 8, f"Kennzeichen: {data['vehicles']['license_plate']}", border=1)
    pdf.cell(95, 8, f"Hersteller/Modell: {data['vehicles']['brand_model']}", border=1, ln=True)
    pdf.cell(95, 8, f"VIN: {data['vehicles']['vin']}", border=1)
    pdf.cell(95, 8, f"Fahrer: {data['inspector_name']}", border=1, ln=True)
    pdf.cell(95, 8, f"KM-Stand: {data['odometer']} KM", border=1)
    pdf.cell(95, 8, f"Standort: {data['location']}", border=1, ln=True)
    
    pdf.ln(5)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "2. Technik & Füllstände", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(63, 8, f"Kraftstoff: {data['fuel_level']}%", border=1)
    pdf.cell(63, 8, f"Batterie: {data['condition_data'].get('battery', 0)}%", border=1)
    pdf.cell(64, 8, f"Bedingungen: {', '.join(data['condition_data'].get('conditions', []))}", border=1, ln=True)

    # Bilder hinzufügen (kleine Auswahl)
    photos = data['condition_data'].get('photos', {})
    if photos:
        pdf.ln(10)
        pdf.cell(0, 10, "3. Fotos & Unterschrift", ln=True)
        # Wir laden nur das erste Bild als Beispiel (v), um das PDF klein zu halten
        if "vorne" in photos and photos["vorne"]:
            try:
                img_data = requests.get(photos["vorne"]).content
                pdf.image(io.BytesIO(img_data), x=10, y=pdf.get_y(), w=80)
            except: pass
        if "signature" in photos and photos["signature"]:
            try:
                sig_data = requests.get(photos["signature"]).content
                pdf.image(io.BytesIO(sig_data), x=110, y=pdf.get_y(), w=50)
            except: pass
            
    return pdf.output()

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
    
    st.header("1. Basisdaten")
    projekte = get_projects()
    default_p_index = 0
    if is_edit:
        try:
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

    st.header("2. Äußere Sichtprüfung")
    erschwert_val = st.session_state.edit_data['condition_data'].get('conditions', []) if is_edit else []
    erschwert = st.multiselect("Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"], default=erschwert_val)
    
    st.subheader("Pflicht-Fotos")
    f_v = st.file_uploader("Foto VORNE (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_h = st.file_uploader("Foto HINTEN (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_l = st.file_uploader("Foto LINKS (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_r = st.file_uploader("Foto RECHTS (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_s = st.file_uploader("Fahrzeugschein (Pflicht)", type=['jpg', 'jpeg', 'png'])
    f_schaden1 = st.file_uploader("Schaden Foto 1 (Optional)", type=['jpg', 'jpeg', 'png'])
    f_schaden2 = st.file_uploader("Schaden Foto 2 (Optional)", type=['jpg', 'jpeg', 'png'])

    st.header("3. Innenraum & Zubehör")
    old_cl = st.session_state.edit_data['condition_data'].get('checkliste', {}) if is_edit else {}
    c_in1, c_in2 = st.columns(2)
    with c_in1:
        st.subheader("Sauberkeit / Zustand")
        c_floor = st.toggle("Boden (Floor) sauber", old_cl.get('floor', True))
        c_seats = st.toggle("Sitze (Seats) sauber", old_cl.get('seats', True))
        c_covers = st.toggle("Innenverkleidung sauber", old_cl.get('covers', True))
        c_instr = st.toggle("Armaturen/Instrumente OK", old_cl.get('instruments', True))
        c_trunk = st.toggle("Kofferraum sauber", old_cl.get('trunk', True))
        c_engine = st.toggle("Motorraum OK", old_cl.get('engine', True))
    with c_in2:
        st.subheader("Zubehör")
        z_aid = st.toggle("Verbandskasten", old_cl.get('aid_kit', True))
        z_tri = st.toggle("Warndreieck", old_cl.get('triangle', True))
        z_vest = st.toggle("Warnweste", old_cl.get('vest', True))
        z_cable = st.toggle("Ladekabel", old_cl.get('cable', False))
        z_reg = st.toggle("Zulassungsbescheinigung", old_cl.get('registration', True))
        z_card = st.toggle("Versicherung/Ladekarte", old_cl.get('card', True))

    st.header("4. Betriebsstoffe")
    f_lvl = st.session_state.edit_data['fuel_level'] if is_edit else 50
    fuel = st.slider("Kraftstoff (%)", 0, 100, f_lvl)
    batt_lvl = st.session_state.edit_data['condition_data'].get('battery', 100) if is_edit else 100
    battery = st.slider("Batterie (%)", 0, 100, batt_lvl)
    km_val = st.session_state.edit_data['odometer'] if is_edit else 0
    km = st.number_input("Kilometerstand", min_value=0, value=km_val)

    st.header("5. Abschluss & Unterschrift")
    bem_val = st.session_state.edit_data['remarks'] if is_edit else ""
    bemerkung = st.text_area("Bemerkungen", value=bem_val)
    canvas_result = st_canvas(fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3, stroke_color="#000000", background_color="#eeeeee", height=150, key="canvas")
    sign_confirm = st.checkbox("Ich bestätige die Richtigkeit der Angaben")

    if st.button("PROTOKOLL SPEICHERN", use_container_width=True):
        if not kennzeichen or not p_name:
            st.error("Kennzeichen und Projekt sind Pflicht!")
        elif not sign_confirm:
            st.error("Bitte Bestätigungs-Häkchen setzen!")
        else:
            with st.spinner("Speichere..."):
                try:
                    supabase.table("projects").upsert({"name": p_name}, on_conflict="name").execute()
                    p_id = supabase.table("projects").select("id").eq("name", p_name).execute().data[0]['id']
                    v_res = supabase.table("vehicles").upsert({"project_id": p_id, "license_plate": kennzeichen, "brand_model": hersteller, "vin": vin}, on_conflict="license_plate").execute()
                    v_id = v_res.data[0]['id']
                    path = f"{p_name}/{kennzeichen}"
                    urls = st.session_state.edit_data['condition_data'].get('photos', {}) if is_edit else {}
                    for key, file in [("vorne", f_v), ("hinten", f_h), ("links", f_l), ("rechts", f_r), ("schein", f_s), ("schaden1", f_schaden1), ("schaden2", f_schaden2)]:
                        if file: urls[key] = upload_photo(file, path, key)
                    if canvas_result.image_data is not None:
                        im = Image.fromarray(canvas_result.image_data.astype('uint8'), 'RGBA')
                        urls["signature"] = upload_photo(im, path, "sign", is_pil=True)
                    
                    payload = {
                        "vehicle_id": v_id, "inspector_name": fahrer, "location": standort, "odometer": km, "fuel_level": fuel, "remarks": bemerkung,
                        "condition_data": {
                            "battery": battery, "photos": urls, "conditions": erschwert,
                            "checkliste": {
                                "floor": c_floor, "seats": c_seats, "covers": c_covers, "instruments": c_instr, "trunk": c_trunk, "engine": c_engine,
                                "aid_kit": z_aid, "triangle": z_tri, "vest": z_vest, "cable": z_cable, "registration": z_reg, "card": z_card
                            }
                        }
                    }
                    if is_edit: supabase.table("protocols").update(payload).eq("id", st.session_state.edit_id).execute()
                    else: supabase.table("protocols").insert(payload).execute()
                    st.success("Erfolgreich gespeichert!")
                    if is_edit: del st.session_state["edit_id"]
                    st.rerun()
                except Exception as e: st.error(f"Fehler: {e}")

# --- TAB 2: ARCHIV & VERWALTUNG ---
with tab2:
    st.title("Archiv & Verwaltung")
    search_q = st.text_input("Kennzeichen suchen").upper()
    results = supabase.table("protocols").select("*, vehicles(*)").order("created_at", desc=True).execute().data
    for r in results:
        plate = r['vehicles']['license_plate']
        if search_q in plate:
            confirm_key = f"del_confirm_{r['id']}"
            with st.expander(f"📄 {r['created_at'][:10]} | {plate} | {r['vehicles']['brand_model']}"):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.write("**BASISDATEN**")
                    st.write(f"Fahrer: {r['inspector_name']} | Standort: {r['location']}")
                    st.write(f"VIN: {r['vehicles']['vin']}")
                    st.write(f"Bedingungen: {', '.join(r['condition_data'].get('conditions', []))}")
                with col_b:
                    st.write("**TECHNIK**")
                    st.write(f"KM: {r['odometer']} | Sprit: {r['fuel_level']}% | Akku: {r['condition_data'].get('battery')}%")
                
                st.write("---")
                st.write("**CHECKLISTE**")
                cl = r['condition_data'].get('checkliste', {})
                cols = st.columns(3)
                for i, (item, val) in enumerate(cl.items()):
                    cols[i % 3].write(f"{'✅' if val else '❌'} {item.capitalize()}")
                
                st.write(f"**Bemerkungen:** {r['remarks']}")
                photos = r['condition_data'].get('photos', {})
                if photos:
                    st.write("**FOTOS & UNTERSCHRIFT**")
                    st.image([url for url in photos.values() if url], width=120)
                
                st.write("---")
                c_b1, c_b2, c_b3 = st.columns(3)
                with c_b1:
                    if st.button("Bearbeiten", key=f"e_{r['id']}"):
                        st.session_state.edit_id, st.session_state.edit_data = r['id'], r
                        st.rerun()
                with c_b2:
                    # PDF DOWNLOAD BUTTON
                    pdf_file = create_pdf(r)
                    st.download_button("⬇️ PDF Download", data=pdf_file, file_name=f"Protokoll_{plate}.pdf", mime="application/pdf", key=f"pdf_{r['id']}")
                with c_b3:
                    if st.session_state.get(confirm_key, False):
                        st.warning("Wirklich löschen?")
                        if st.button("JA", key=f"y_{r['id']}", type="primary"):
                            supabase.table("protocols").delete().eq("id", r['id']).execute()
                            del st.session_state[confirm_key]; st.rerun()
                        if st.button("NEIN", key=f"n_{r['id']}"):
                            del st.session_state[confirm_key]; st.rerun()
                    else:
                        if st.button("Löschen", key=f"d_{r['id']}"):
                            st.session_state[confirm_key] = True; st.rerun()
