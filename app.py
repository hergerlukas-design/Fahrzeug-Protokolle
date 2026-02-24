import streamlit as st
import datetime

# App Konfiguration für Mobile Optimierung
st.set_page_config(page_title="Fahrzeug-Übergabe", page_icon="🚗")

st.title("🚗 Fahrzeug-Annahme")

# --- ABSCHNITT 1: Projekt & Basisdaten ---
st.header("1. Basisdaten")

# Beispiel-Liste der Projekte (Später ziehen wir diese aus Supabase)
projekte_liste = ["CarHandling Campus", "Überführung BMW", "-- Neues Projekt erstellen --"]
auswahl_projekt = st.selectbox("Projekt wählen", projekte_liste)

projekt_name = ""
if auswahl_projekt == "-- Neues Projekt erstellen --":
    projekt_name = st.text_input("Name des neuen Projekts eingeben")
else:
    projekt_name = auswahl_projekt

col1, col2 = st.columns(2)
with col1:
    kennzeichen = st.text_input("Kennzeichen", placeholder="z.B. WIL-XY 123")
with col2:
    hersteller = st.text_input("Hersteller/Modell", placeholder="z.B. LYNK & CO")

vin = st.text_input("VIN (Fahrgestellnummer)")

# --- ABSCHNITT 2: Fahrzeug-Zustand ---
st.header("2. Zustand & Zubehör")

km_stand = st.number_input("Kilometerstand", min_value=0, step=1)
energie = st.slider("Tank / Batterie (%)", 0, 100, 50)

st.subheader("Checkliste")
clean_floor = st.checkbox("Boden sauber (Floor)")
clean_seats = st.checkbox("Sitze sauber (Seats)")
ladekabel = st.checkbox("Ladekabel vorhanden")
verbandskasten = st.checkbox("Verbandskasten vorhanden")

# --- ABSCHNITT 3: Foto-Dokumentation (Pflicht) ---
st.header("3. Fotos (Pflicht)")
st.info("Bitte mache Fotos von allen 4 Seiten und vom Fahrzeugschein.")

foto_vorne = st.camera_input("Foto VORNE")
foto_hinten = st.camera_input("Foto HINTEN")
foto_links = st.camera_input("Foto LINKS")
foto_rechts = st.camera_input("Foto RECHTS")
foto_schein = st.camera_input("Fahrzeugschein (Zulassung)")

# --- ABSCHNITT 4: Abschluss ---
st.header("4. Abschluss")
bemerkung = st.text_area("Bemerkungen / Bekannte Schäden")

st.write("---")
st.write("### Unterschrift")
st.info("Hier wird später ein Unterschriftenfeld integriert.")

# Überprüfung, ob alle Pflichtfotos da sind
pflicht_fotos_da = foto_vorne and foto_hinten and foto_links and foto_rechts and foto_schein

if st.button("Protokoll Speichern", use_container_width=True):
    if not pflicht_fotos_da:
        st.error("Bitte erst alle 5 Pflichtfotos aufnehmen!")
    elif not kennzeichen:
        st.error("Bitte Kennzeichen angeben!")
    else:
        st.success(f"Protokoll für {kennzeichen} wurde lokal erstellt! (Anbindung an Datenbank folgt)")
        # Hier kommt im nächsten Schritt der Code für Supabase rein
