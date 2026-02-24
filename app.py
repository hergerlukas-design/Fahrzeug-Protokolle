import streamlit as st
from supabase import create_client, Client
import datetime
import uuid

# --- DATENBANK VERBINDUNG ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Fahrzeug-Übergabe", page_icon="🚗")
st.title("🚗 Fahrzeug-Annahme")

# --- HILFSFUNKTION FÜR FOTO-UPLOAD ---
def upload_photo(file, folder_name, photo_type):
    if file is None:
        return None
    # Dateiname erstellen: kennzeichen/datum_typ.jpg
    file_extension = file.name.split('.')[-1] if hasattr(file, 'name') else "jpg"
    file_path = f"{folder_name}/{datetime.date.today()}_{photo_type}_{uuid.uuid4().hex[:5]}.{file_extension}"
    
    # Upload zu Supabase Storage
    content = file.getvalue()
    supabase.storage.from_("vehicle-photos").upload(file_path, content)
    
    # URL der Datei zurückgeben
    return supabase.storage.from_("vehicle-photos").get_public_url(file_path)

# --- PROJEKTE LADEN ---
def get_projects():
    try:
        response = supabase.table("projects").select("name").execute()
        return [p['name'] for p in response.data]
    except:
        return []

vorhandene_projekte = get_projects()

# --- 1. BASISDATEN ---
st.header("1. Basisdaten")
auswahl_projekt = st.selectbox("Projekt wählen", ["-- Neues Projekt erstellen --"] + vorhandene_projekte)

if auswahl_projekt == "-- Neues Projekt erstellen --":
    projekt_name = st.text_input("Name des neuen Projekts")
else:
    projekt_name = auswahl_projekt

col1, col2 = st.columns(2)
with col1:
    kennzeichen = st.text_input("Kennzeichen", placeholder="z.B. WIL-XY 123").replace(" ", "_")
with col2:
    hersteller = st.text_input("Hersteller/Modell")

# --- 2. ZUSTAND ---
st.header("2. Zustand")
km_stand = st.number_input("Kilometerstand", min_value=0)
energie = st.slider("Tank / Batterie (%)", 0, 100, 50)
checkliste = {
    "floor": st.checkbox("Boden sauber"),
    "seats": st.checkbox("Sitze sauber"),
    "cable": st.checkbox("Ladekabel vorhanden")
}

# --- 3. FOTOS ---
st.header("3. Fotos (Pflicht)")
f_vorne = st.camera_input("Vorne")
f_hinten = st.camera_input("Hinten")
f_links = st.camera_input("Links")
f_rechts = st.camera_input("Rechts")
f_schein = st.camera_input("Fahrzeugschein")

# --- 4. SPEICHERN ---
if st.button("Protokoll Speichern", use_container_width=True):
    if not (f_vorne and f_hinten and f_links and f_rechts and f_schein and kennzeichen and projekt_name):
        st.error("Bitte alle Pflichtfelder ausfüllen und alle 5 Fotos machen!")
    else:
        with st.spinner("Protokoll wird erstellt und Fotos hochgeladen..."):
            try:
                # 1. Projekt & Fahrzeug IDs
                if auswahl_projekt == "-- Neues Projekt erstellen --":
                    supabase.table("projects").insert({"name": projekt_name}).execute()
                
                proj_id = supabase.table("projects").select("id").eq("name", projekt_name).execute().data[0]['id']
                veh_resp = supabase.table("vehicles").upsert({"project_id": proj_id, "license_plate": kennzeichen, "brand_model": hersteller}).execute()
                veh_id = veh_resp.data[0]['id']

                # 2. Fotos hochladen
                folder = f"{projekt_name}/{kennzeichen}"
                urls = {
                    "vorne": upload_photo(f_vorne, folder, "vorne"),
                    "hinten": upload_photo(f_hinten, folder, "hinten"),
                    "links": upload_photo(f_links, folder, "links"),
                    "rechts": upload_photo(f_rechts, folder, "rechts"),
                    "schein": upload_photo(f_schein, folder, "schein")
                }

                # 3. Protokoll in DB speichern
                supabase.table("protocols").insert({
                    "vehicle_id": veh_id,
                    "odometer": km_stand,
                    "fuel_level": energie,
                    "condition_data": {**checkliste, "photo_urls": urls}
                }).execute()

                st.success("✅ Fertig! Protokoll und Fotos wurden sicher gespeichert.")
                st.balloons()
            except Exception as e:
                st.error(f"Fehler: {e}")
