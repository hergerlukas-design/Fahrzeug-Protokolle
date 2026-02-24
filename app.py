import streamlit as st
from supabase import create_client, Client
import datetime

# --- DATENBANK VERBINDUNG ---
# Holt sich die Daten sicher aus den Streamlit Secrets
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Fahrzeug-Übergabe", page_icon="🚗")
st.title("🚗 Fahrzeug-Annahme")

# --- PROJEKTE LADEN ---
def get_projects():
    response = supabase.table("projects").select("name").execute()
    return [p['name'] for p in response.data]

try:
    vorhandene_projekte = get_projects()
except:
    vorhandene_projekte = ["Allgemein"]

# --- 1. BASISDATEN ---
st.header("1. Basisdaten")
auswahl_projekt = st.selectbox("Projekt wählen", ["-- Neues Projekt erstellen --"] + vorhandene_projekte)

projekt_name = ""
if auswahl_projekt == "-- Neues Projekt erstellen --":
    projekt_name = st.text_input("Name des neuen Projekts")
else:
    projekt_name = auswahl_projekt

col1, col2 = st.columns(2)
with col1:
    kennzeichen = st.text_input("Kennzeichen", placeholder="z.B. WIL-XY 123")
with col2:
    hersteller = st.text_input("Hersteller/Modell", placeholder="z.B. LYNK & CO")

vin = st.text_input("VIN (Fahrgestellnummer)")

# --- 2. ZUSTAND ---
st.header("2. Zustand")
km_stand = st.number_input("Kilometerstand", min_value=0, step=1)
energie = st.slider("Tank / Batterie (%)", 0, 100, 50)

# Checkliste als Dictionary (für JSON Speicherung)
checkliste = {
    "floor_clean": st.checkbox("Boden sauber"),
    "seats_clean": st.checkbox("Sitze sauber"),
    "cable": st.checkbox("Ladekabel vorhanden"),
    "first_aid": st.checkbox("Verbandskasten")
}

# --- 3. FOTOS ---
st.header("3. Fotos (Pflicht)")
f1 = st.camera_input("Vorne")
f2 = st.camera_input("Hinten")
f3 = st.camera_input("Links")
f4 = st.camera_input("Rechts")
f5 = st.camera_input("Fahrzeugschein")

# --- 4. SPEICHERN LOGIK ---
if st.button("Protokoll Speichern", use_container_width=True):
    if not (f1 and f2 and f3 and f4 and f5 and kennzeichen and projekt_name):
        st.error("Bitte alle Pflichtfelder ausfüllen und Fotos machen!")
    else:
        with st.spinner("Speichere Daten..."):
            try:
                # 1. Falls neues Projekt, in DB anlegen
                if auswahl_projekt == "-- Neues Projekt erstellen --":
                    supabase.table("projects").insert({"name": projekt_name}).execute()
                
                # 2. Projekt ID holen
                proj_resp = supabase.table("projects").select("id").eq("name", projekt_name).execute()
                proj_id = proj_resp.data[0]['id']

                # 3. Fahrzeug anlegen/holen
                veh_resp = supabase.table("vehicles").upsert({
                    "project_id": proj_id,
                    "license_plate": kennzeichen,
                    "vin": vin,
                    "brand_model": hersteller
                }).execute()
                veh_id = veh_resp.data[0]['id']

                # 4. Protokoll speichern
                supabase.table("protocols").insert({
                    "vehicle_id": veh_id,
                    "odometer": km_stand,
                    "fuel_level": energie,
                    "condition_data": checkliste,
                    "remarks": st.session_state.get("remarks", "")
                }).execute()

                st.success(f"Erfolgreich gespeichert! Fahrzeug {kennzeichen} ist im System.")
                st.balloons()
            except Exception as e:
                st.error(f"Fehler beim Speichern: {e}")
                
