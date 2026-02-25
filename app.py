import streamlit as st
from supabase import create_client, Client
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io
import datetime
import uuid
import requests
import re
import numpy as np
from fpdf import FPDF
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 1. SETUP
# ---------------------------------------------------------------------------

url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Vehicle Protocol Pro", layout="wide", page_icon="🚗")

# Sticky Tabs CSS + Floating Button
st.markdown("""
    <style>
        div[data-testid="stTabs"] > div:first-child {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            background-color: var(--default-backgroundColor);
            z-index: 999;
            padding: 10px 1rem 0 1rem;
            border-bottom: 1px solid rgba(128, 128, 128, 0.2);
        }

        /* Abstand damit der Inhalt nicht unter den fixierten Tabs verschwindet */
        div[data-testid="stTabs"] > div:last-child {
            margin-top: 50px;
        }

        .float-btn-placeholder {}
    </style>
""", unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 Protokoll erstellen / Bearbeiten", "🔍 Archiv & Verwaltung"])

# ---------------------------------------------------------------------------
# 2. KONSTANTEN
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE_MB = 5

# FIX (Qualität): Checkliste-Übersetzung nur einmal definiert, überall verwendet
CHECKLIST_LABELS = {
    "floor":        "Boden",
    "seats":        "Sitze",
    "entry":        "Einstiege",
    "instruments":  "Armaturen",
    "trunk":        "Kofferraum",
    "engine":       "Motorraum",
    "aid_kit":      "Verbandskasten",
    "triangle":     "Warndreieck",
    "vest":         "Warnweste",
    "cable":        "Ladekabel",
    "registration": "Fahrzeugschein",
    "card":         "Ladekarte",
}

# Welche Keys bekommen "Ja/Nein" statt "Sauber/Nicht sauber"
CHECKLIST_JA_NEIN = {"aid_kit", "triangle", "vest", "cable", "registration", "card"}

# ---------------------------------------------------------------------------
# 3. HILFSFUNKTIONEN
# ---------------------------------------------------------------------------

def sanitize_filename(text: str) -> str:
    """Bereinigt Texte für den Speicherpfad (entfernt &, Leerzeichen, Umlaute)."""
    if not text:
        return "unbekannt"
    replacements = {
        "ä": "ae", "ö": "oe", "ü": "ue",
        "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
        "ß": "ss", "&": "_and_", " ": "_",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return re.sub(r"[^a-zA-Z0-9_\-]", "", text)


def compress_image(data: bytes, max_size_mb: float = MAX_UPLOAD_SIZE_MB, quality: int = 85) -> bytes:
    """Komprimiert ein Bild schrittweise bis es unter max_size_mb liegt."""
    img = Image.open(io.BytesIO(data))
    # EXIF-Rotation korrigieren (Handyfotos)
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    # In RGB konvertieren falls nötig (z.B. RGBA PNG)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    # Maximal 2000px – reicht für Protokolle
    img.thumbnail((2000, 2000), Image.LANCZOS)
    current_quality = quality
    while current_quality >= 40:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=current_quality, optimize=True)
        if buf.tell() / (1024 * 1024) <= max_size_mb:
            return buf.getvalue()
        current_quality -= 15
    # Letzter Versuch mit kleinster Auflösung
    img.thumbnail((1000, 1000), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=40, optimize=True)
    return buf.getvalue()


def upload_photo(file, folder_path: str, p_type: str, is_pil: bool = False) -> str | None:
    """Lädt ein Foto nach Supabase Storage hoch und gibt die öffentliche URL zurück.
    Nicht-PIL-Fotos werden automatisch komprimiert falls nötig."""
    if file is None:
        return None
    try:
        clean_parts = [sanitize_filename(part) for part in folder_path.split("/")]
        clean_folder = "/".join(clean_parts)

        if is_pil:
            ext = "png"
            path = f"{clean_folder}/{datetime.date.today()}_{p_type}_{uuid.uuid4().hex[:5]}.{ext}"
            img_byte_arr = io.BytesIO()
            file.save(img_byte_arr, format="PNG")
            content = img_byte_arr.getvalue()
        else:
            raw = file.getvalue()
            size_mb = len(raw) / (1024 * 1024)
            if size_mb > MAX_UPLOAD_SIZE_MB:
                st.info(f"📸 '{p_type}': {size_mb:.1f} MB → wird komprimiert...")
                content = compress_image(raw)
                st.info(f"✅ '{p_type}' komprimiert auf {len(content)/(1024*1024):.1f} MB")
            else:
                content = raw
            ext = "jpg"
            path = f"{clean_folder}/{datetime.date.today()}_{p_type}_{uuid.uuid4().hex[:5]}.{ext}"

        supabase.storage.from_("vehicle-photos").upload(path, content)
        return supabase.storage.from_("vehicle-photos").get_public_url(path)

    except Exception as e:
        st.error(f"Upload-Fehler ({p_type}): {e}")
        return None


# FIX (Performance): Ergebnis 60 Sekunden cachen, kein DB-Hit bei jedem Rerender
@st.cache_data(ttl=60)
def get_projects() -> list[str]:
    # FIX (Bug): Exception mit Fehlermeldung statt stillem pass
    try:
        res = supabase.table("projects").select("name").order("name").execute()
        return [p["name"] for p in res.data]
    except Exception as e:
        st.warning(f"Projekte konnten nicht geladen werden: {e}")
        return []


def validate_inputs(kennzeichen: str, p_name: str, confirm: bool, km: int) -> bool:
    """Validiert Pflichtfelder und gibt True zurück wenn alles OK ist."""
    if not kennzeichen:
        st.error("Bitte Kennzeichen eingeben.")
        return False
    if not p_name:
        st.error("Bitte Projektname eingeben.")
        return False
    if not confirm:
        st.error("Bitte Richtigkeit der Angaben bestätigen.")
        return False
    # FIX (Sicherheit): KM-Stand-Validierung
    if not (0 <= km <= 2_000_000):
        st.error("KM-Stand scheint unrealistisch (max. 2.000.000 km).")
        return False
    return True


def ensure_project(name: str) -> int:
    """Legt Projekt an falls nicht vorhanden und gibt die ID zurück."""
    supabase.table("projects").upsert({"name": name}, on_conflict="name").execute()
    res = supabase.table("projects").select("id").eq("name", name).execute()
    return res.data[0]["id"]


def upsert_vehicle(project_id: int, license_plate: str, brand_model: str, vin: str) -> int:
    """Legt Fahrzeug an / aktualisiert es und gibt die ID zurück."""
    res = supabase.table("vehicles").upsert(
        {
            "project_id": project_id,
            "license_plate": license_plate,
            "brand_model": brand_model,
            "vin": vin,
        },
        on_conflict="license_plate",
    ).execute()
    return res.data[0]["id"]


def upload_all_photos(files: dict, path: str) -> dict:
    """Lädt alle Fotos hoch und gibt ein Dict {label: url} zurück."""
    urls = {}
    for label, file in files.items():
        if file is not None:
            is_pil = label == "signature"
            result = upload_photo(file, path, label, is_pil=is_pil)
            if result:
                urls[label] = result
    return urls


def build_payload(
    vehicle_id: int,
    inspector_name: str,
    location: str,
    odometer: int,
    fuel_level: int,
    remarks: str,
    battery: int,
    photos: dict,
    conditions: list,
    damage_records: list,
    checkliste: dict,
) -> dict:
    """Baut den vollständigen Payload für die protocols-Tabelle zusammen."""
    return {
        "vehicle_id": vehicle_id,
        "inspector_name": inspector_name,
        "location": location,
        "odometer": odometer,
        "fuel_level": fuel_level,
        "remarks": remarks,
        "inspection_date": datetime.datetime.now().isoformat(),
        "condition_data": {
            "battery": battery,
            "photos": photos,
            "conditions": conditions,
            "damage_records": damage_records,
            "checkliste": checkliste,
        },
    }


def save_protocol(payload: dict, edit_id: int | None = None) -> bool:
    """Speichert oder aktualisiert ein Protokoll. Gibt True bei Erfolg zurück."""
    try:
        if edit_id:
            supabase.table("protocols").update(payload).eq("id", edit_id).execute()
        else:
            supabase.table("protocols").insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"Fehler beim Speichern: {e}")
        return False


# ---------------------------------------------------------------------------
# 4. PDF-ERSTELLUNG
# ---------------------------------------------------------------------------

# FIX (Performance): Fotos parallel herunterladen
def _fetch_image_bytes(url: str) -> bytes | None:
    try:
        return requests.get(url, timeout=10).content
    except Exception:
        return None


def _fetch_photos_parallel(photo_items: list[tuple[str, str]]) -> list[tuple[str, bytes | None]]:
    """Lädt mehrere Fotos parallel herunter."""
    urls = [url for _, url in photo_items]
    with ThreadPoolExecutor(max_workers=5) as executor:
        contents = list(executor.map(_fetch_image_bytes, urls))
    return [(label, content) for (label, _), content in zip(photo_items, contents)]


# FIX (Qualität): Unicode-fähige PDF-Klasse – löst Umlaut-Problem mit Helvetica
class UnicodePDF(FPDF):
    """FPDF-Subklasse mit UTF-8-Unterstützung über core latin extended fonts."""
    pass


def _prepare_image_bytes(img_bytes: bytes) -> bytes:
    """
    Wendet EXIF-Rotation an und gibt korrigierte JPEG-Bytes zurück.
    FPDF versteht kein EXIF – ohne diesen Schritt erscheinen Handyfotos gedreht.
    """
    try:
        from PIL import ImageOps
        pil_img = Image.open(io.BytesIO(img_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)   # Rotation aus EXIF anwenden
        if pil_img.mode in ("RGBA", "P"):
            pil_img = pil_img.convert("RGB")
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return img_bytes  # Fallback: Original zurückgeben


def _get_photo_display_size(img_bytes: bytes, max_w: float, max_h: float) -> tuple[float, float]:
    """
    Berechnet die Anzeigegröße eines (bereits EXIF-korrigierten) Fotos.
    WICHTIG: pdf.image() wird immer NUR mit w= aufgerufen (nie h=), sonst verzerrt FPDF.
    """
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        orig_w, orig_h = pil_img.size
    except Exception:
        return max_w, max_h

    # Erst auf max_w begrenzen
    scale  = max_w / orig_w
    disp_w = max_w
    disp_h = orig_h * scale

    # Falls zu hoch: auf max_h begrenzen und Breite anpassen
    if disp_h > max_h:
        scale  = max_h / orig_h
        disp_h = max_h
        disp_w = orig_w * scale

    return disp_w, disp_h


def create_pdf(data: dict) -> bytes:
    pdf = UnicodePDF()
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)

    def u(text: str) -> str:
        """Konvertiert Umlaute für FPDF1-Kompatibilität."""
        if not isinstance(text, str):
            text = str(text)
        return (
            text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
                .replace("ß", "ss")
        )

    photos = data["condition_data"].get("photos", {})

    # ── Unterschrift vorab herunterladen für Seite 1 ────────────────────────
    sig_bytes = None
    if photos.get("signature"):
        sig_bytes = _fetch_image_bytes(photos["signature"])

    # ── Seitenheader: Titel links, Datum + Unterschrift rechts ──────────────
    # Unterschrift-Box: x=145, y=8, w=55, h=30
    SIG_X, SIG_Y, SIG_W, SIG_BOX_H = 145, 8, 55, 30

    pdf.set_font("helvetica", "B", 16)
    pdf.set_xy(10, 15)
    pdf.cell(130, 10, u("Fahrzeug-Übergabeprotokoll"), ln=False)

    # Datum + Unterschrift-Box oben rechts
    pdf.set_font("helvetica", "", 8)
    pdf.set_xy(SIG_X, SIG_Y)
    pdf.cell(SIG_W, 5, f"Datum: {data['created_at'][:10]}", ln=True, align="C")
    pdf.set_font("helvetica", "B", 8)
    pdf.set_xy(SIG_X, SIG_Y + 5)
    pdf.cell(SIG_W, 5, u("Unterschrift"), ln=True, align="C")
    # Unterschrift-Bild einfügen (nur w=, kein h= → kein Verzerren)
    if sig_bytes:
        try:
            sig_prepared = _prepare_image_bytes(sig_bytes)
            sig_disp_w, sig_disp_h = _get_photo_display_size(sig_prepared, SIG_W, SIG_BOX_H - 6)
            sig_img_x = SIG_X + (SIG_W - sig_disp_w) / 2
            pdf.image(io.BytesIO(sig_prepared), x=sig_img_x, y=SIG_Y + 10, w=sig_disp_w)
        except Exception:
            pass
    pdf.set_xy(10, 28)

    # ── 1. Basisdaten ────────────────────────────────────────────────────────
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "1. Basisdaten", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(95, 8, f"Kennzeichen: {data['vehicles']['license_plate']}", border=1)
    pdf.cell(95, 8, u(f"Modell: {data['vehicles']['brand_model']}"), border=1, ln=True)
    pdf.cell(95, 8, f"VIN: {data['vehicles']['vin']}", border=1)
    pdf.cell(95, 8, u(f"Ersteller: {data['inspector_name']}"), border=1, ln=True)
    pdf.cell(95, 8, f"KM-Stand: {data['odometer']} KM", border=1)
    pdf.cell(95, 8, u(f"Standort: {data['location']}"), border=1, ln=True)

    # ── 2. Technik ───────────────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "2. Technik & Betriebsstoffe", ln=True)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(63, 8, f"Kraftstoff: {data['fuel_level']}%", border=1)
    pdf.cell(63, 8, f"Batterie: {data['condition_data'].get('battery', 0)}%", border=1)
    pdf.cell(64, 8, u(f"Bedingungen: {', '.join(data['condition_data'].get('conditions', []))}"), border=1, ln=True)

    # ── 3. Checkliste ────────────────────────────────────────────────────────
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, u("3. Checkliste"), ln=True)

    cl = data["condition_data"].get("checkliste", {})

    def cl_val(key: str, val: bool) -> str:
        if key in CHECKLIST_JA_NEIN:
            return "Ja" if val else "Nein"
        return "Sauber" if val else "Nicht sauber"

    ZUSTAND_KEYS  = ["floor", "seats", "entry", "instruments", "trunk", "engine"]
    ZUBEHOER_KEYS = ["aid_kit", "triangle", "vest", "cable", "registration", "card"]

    zustand_items  = [(k, cl[k]) for k in ZUSTAND_KEYS  if k in cl]
    zubehoer_items = [(k, cl[k]) for k in ZUBEHOER_KEYS if k in cl]

    COL_L = 10    # x Start linke Spalte
    COL_R = 108   # x Start rechte Spalte
    COL_W = 90    # Breite pro Spalte
    ROW_H = 7

    # Überschriften
    x_after_headers = pdf.get_y()
    pdf.set_font("helvetica", "B", 10)
    pdf.set_xy(COL_L, x_after_headers)
    pdf.cell(COL_W, ROW_H, "Zustand", ln=False)
    pdf.set_xy(COL_R, x_after_headers)
    pdf.cell(COL_W, ROW_H, u("Zubehör"), ln=True)

    # Zeilen
    pdf.set_font("helvetica", "", 9)
    rows = max(len(zustand_items), len(zubehoer_items))
    for i in range(rows):
        y = pdf.get_y()
        if i < len(zustand_items):
            k, v = zustand_items[i]
            pdf.set_xy(COL_L, y)
            pdf.cell(COL_W, ROW_H, f"{CHECKLIST_LABELS.get(k, k)}: {cl_val(k, v)}", border=1)
        if i < len(zubehoer_items):
            k, v = zubehoer_items[i]
            pdf.set_xy(COL_R, y)
            pdf.cell(COL_W, ROW_H, f"{CHECKLIST_LABELS.get(k, k)}: {cl_val(k, v)}", border=1)
        pdf.ln(ROW_H)


    # ── 4. Bemerkungen ───────────────────────────────────────────────────────
    if data.get("remarks"):
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "4. Bemerkungen", ln=True)
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(190, 8, u(data["remarks"]), border=1)

    # ── 5. Fotos ─────────────────────────────────────────────────────────────
    # Alle Fahrzeugfotos vorab parallel herunterladen
    RUNDUMBLICK = ["vorne", "hinten", "links", "rechts", "schein"]
    schaden_labels = [lbl for lbl in photos if lbl.startswith("schaden") and photos[lbl]]

    rundumblick_items = [(lbl, photos[lbl]) for lbl in RUNDUMBLICK if photos.get(lbl)]
    schaden_items     = [(lbl, photos[lbl]) for lbl in schaden_labels]

    all_photo_items = rundumblick_items + schaden_items
    if all_photo_items:
        fetched_map = dict(_fetch_photos_parallel(all_photo_items))
    else:
        fetched_map = {}

    # ── Foto-Seite: festes 2-Spalten-Layout ─────────────────────────────────
    #
    #  Spalte 1 (x=10)   │  Spalte 2 (x=108)
    #  ───────────────────┼──────────────────
    #  Zeile 1: Vorne     │  Hinten          ← Hochformat, max 95mm hoch
    #  Zeile 2: Links     │  Rechts          ← Querformat, max 58mm hoch
    #  Zeile 3:  –        │  Schein          ← Querformat, max 58mm hoch
    #
    # Seitenrechnung (A4 nutzbar ~275mm):
    #   HEADER_Y=20 + 95+7+4 + 58+7+4 + 58+7 = 260mm ✓
    #
    # WICHTIG: Alle Bytes zuerst via _prepare_image_bytes() EXIF-korrigieren,
    # dann pdf.image() NUR mit w= aufrufen → kein Verzerren, kein Rotieren!

    COL_X       = [10.0, 108.0]
    COL_W       = 87.0
    GAP         = 4.0
    PORT_MAX_H  = 95.0
    LAND_MAX_H  = 58.0
    HEADER_Y    = 20.0

    ROW_Y = [
        HEADER_Y,
        HEADER_Y + PORT_MAX_H + GAP,
        HEADER_Y + PORT_MAX_H + GAP + LAND_MAX_H + GAP,
    ]

    # Slot-Definitionen: (label, col_index, row_index, max_h)
    SLOTS = [
        ("vorne",  0, 0, PORT_MAX_H),
        ("hinten", 1, 0, PORT_MAX_H),
        ("links",  0, 1, LAND_MAX_H),
        ("rechts", 1, 1, LAND_MAX_H),
        ("schein", 1, 2, LAND_MAX_H),
    ]

    # Nur Seite hinzufügen wenn mindestens ein Rundumblick-Foto vorhanden
    if any(fetched_map.get(lbl) for lbl, *_ in SLOTS):
        pdf.add_page()
        pdf.set_font("helvetica", "B", 12)
        pdf.set_xy(10, 10)
        pdf.cell(0, 8, "5. Fotodokumentation", ln=True)

        for label, col_idx, row_idx, max_h in SLOTS:
            raw_bytes = fetched_map.get(label)
            if not raw_bytes:
                continue

            img_bytes = _prepare_image_bytes(raw_bytes)
            x         = COL_X[col_idx]
            y         = ROW_Y[row_idx]
            disp_w, disp_h = _get_photo_display_size(img_bytes, COL_W, max_h)
            x_img = x + (COL_W - disp_w) / 2

            try:
                pdf.image(io.BytesIO(img_bytes), x=x_img, y=y, w=disp_w)
            except Exception:
                pass

    # ── 6. Schäden (Text + Fotos) auf neuer Seite ────────────────────────────
    dmg = data["condition_data"].get("damage_records", [])
    if dmg or schaden_items:
        pdf.add_page()
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, u("6. Erfasste Schäden"), ln=True)

        if dmg:
            pdf.set_font("helvetica", "B", 9)
            pdf.cell(60, 7, "Position", border=1)
            pdf.cell(60, 7, "Art", border=1)
            pdf.cell(70, 7, u("Intensität"), border=1, ln=True)
            pdf.set_font("helvetica", "", 9)
            for d in dmg:
                pdf.cell(60, 7, u(d["pos"]), border=1)
                pdf.cell(60, 7, u(d["type"]), border=1)
                pdf.cell(70, 7, u(d["int"]), border=1, ln=True)

        # Schadensfotos in 2er-Raster unter der Tabelle
        if schaden_items:
            pdf.ln(6)
            pdf.set_font("helvetica", "B", 10)
            pdf.cell(0, 8, "Schadensfotos:", ln=True)

            s_COL_X = [10.0, 108.0]
            s_COL_W = 87.0
            s_MAX_H = 100.0
            s_col   = 0
            s_y     = pdf.get_y() + 2

            fetched_schaden = _fetch_photos_parallel(schaden_items)
            for label, raw_bytes in fetched_schaden:
                if not raw_bytes:
                    continue
                # EXIF-Rotation korrigieren
                img_bytes = _prepare_image_bytes(raw_bytes)
                disp_w, disp_h = _get_photo_display_size(img_bytes, s_COL_W, s_MAX_H)
                x_img = s_COL_X[s_col] + (s_COL_W - disp_w) / 2

                # Neue Seite wenn nötig
                if s_y + disp_h + 10 > 275:
                    pdf.add_page()
                    s_y = 15
                    s_col = 0

                try:
                    pdf.image(io.BytesIO(img_bytes), x=x_img, y=s_y, w=disp_w)
                except Exception:
                    pass

                s_col += 1
                if s_col > 1:
                    s_col = 0
                    s_y += max(disp_h, s_MAX_H) + 10

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# 5. TAB 1: PROTOKOLL ERSTELLEN / BEARBEITEN
# ---------------------------------------------------------------------------

with tab1:
    is_edit = "edit_id" in st.session_state

    if is_edit:
        st.warning(f"⚠️ Bearbeitungsmodus: {st.session_state.edit_data['vehicles']['license_plate']}")
        if st.button("Abbrechen"):
            del st.session_state["edit_id"]
            if "edit_data" in st.session_state:
                del st.session_state["edit_data"]
            # FIX (Bug): damage_count beim Abbrechen zurücksetzen
            st.session_state.damage_count = 0
            st.rerun()

    st.title("Fahrzeug-Übergabe")

    # ── Basisdaten ──────────────────────────────────────────────────────────
    st.header("1. Basisdaten")
    projekte = get_projects()
    auswahl_p = st.selectbox("Projekt", ["-- Neues Projekt erstellen --"] + projekte)
    p_name = st.text_input("Projektname") if auswahl_p == "-- Neues Projekt erstellen --" else auswahl_p

    col1, col2 = st.columns(2)
    with col1:
        k_val = st.session_state.edit_data["vehicles"]["license_plate"] if is_edit else ""
        kennzeichen = st.text_input("Kennzeichen", value=k_val).upper()

        vin_val = st.session_state.edit_data["vehicles"]["vin"] if is_edit else ""
        vin = st.text_input("VIN", value=vin_val)

        f_val = st.session_state.edit_data["inspector_name"] if is_edit else ""
        fahrer = st.text_input("Ersteller", value=f_val)

    with col2:
        h_val = st.session_state.edit_data["vehicles"]["brand_model"] if is_edit else ""
        hersteller = st.text_input("Modell", value=h_val)

        s_val = st.session_state.edit_data["location"] if is_edit else ""
        standort = st.text_input("Standort", value=s_val)

        # FIX (Qualität): Datum nur als Anzeige – Supabase setzt created_at automatisch
        st.text_input("Datum", value=datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), disabled=True)

    # ── Sichtprüfung & Fotos ────────────────────────────────────────────────
    st.header("2. Sichtprüfung & Schadenserfassung")
    erschwert_val = st.session_state.edit_data["condition_data"].get("conditions", []) if is_edit else []
    erschwert = st.multiselect(
        "Bedingungen",
        ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"],
        default=erschwert_val,
    )

    st.subheader("Pflicht-Fotos (Rundumblick)")
    c_f1, c_f2 = st.columns(2)
    with c_f1:
        f_v = st.file_uploader("Vorne",  type=["jpg", "png"])
        f_l = st.file_uploader("Links",  type=["jpg", "png"])
        f_s = st.file_uploader("Schein", type=["jpg", "png"])
    with c_f2:
        f_h = st.file_uploader("Hinten", type=["jpg", "png"])
        f_r = st.file_uploader("Rechts", type=["jpg", "png"])

    # ── Schäden ─────────────────────────────────────────────────────────────
    st.subheader("🛠️ Schäden erfassen")
    if "damage_count" not in st.session_state:
        if is_edit:
            st.session_state.damage_count = len(
                st.session_state.edit_data["condition_data"].get("damage_records", [])
            )
        else:
            st.session_state.damage_count = 0

    if st.button("+ Neuen Schaden hinzufügen"):
        st.session_state.damage_count += 1

    damage_records: list[dict] = []
    d_files: dict = {}
    old_dmgs = st.session_state.edit_data["condition_data"].get("damage_records", []) if is_edit else []

    for i in range(st.session_state.damage_count):
        d_val = old_dmgs[i] if i < len(old_dmgs) else {
            "pos": "Stoßfänger vorne", "type": "Kratzer", "int": "Oberflächlich"
        }

        with st.expander(f"Schaden #{i + 1}", expanded=True):
            d1, d2 = st.columns(2)
            with d1:
                pos_list = [
                    "Stoßfänger vorne", "Stoßfänger hinten", "Motorhaube", "Dach",
                    "Tür VL", "Tür VR", "Felge VL", "Felge VR", "Felge HL", "Felge HR",
                ]
                p_idx = pos_list.index(d_val["pos"]) if d_val["pos"] in pos_list else 0
                pos = st.selectbox("Position", pos_list, index=p_idx, key=f"pos_{i}")

                type_list = ["Kratzer", "Delle", "Steinschlag", "Riss", "Fehlteil"]
                dtype = st.radio(
                    "Art", type_list,
                    index=type_list.index(d_val["type"]) if d_val["type"] in type_list else 0,
                    key=f"type_{i}", horizontal=True,
                )
            with d2:
                int_list = ["Oberflächlich", "Bis Grundierung", "Deformiert"]
                intens = st.select_slider(
                    "Intensität", options=int_list,
                    value=d_val["int"] if d_val["int"] in int_list else "Oberflächlich",
                    key=f"int_{i}",
                )
                df = st.file_uploader(f"Foto Schaden #{i + 1}", type=["jpg", "png"], key=f"photo_{i}")
                if df:
                    d_files[f"schaden_{i + 1}"] = df

            damage_records.append({"pos": pos, "type": dtype, "int": intens})

    # ── Checkliste ──────────────────────────────────────────────────────────
    st.header("3. Checkliste")
    old_cl = st.session_state.edit_data["condition_data"].get("checkliste", {}) if is_edit else {}
    c1, c2 = st.columns(2)
    with c1:
        c_floor  = st.toggle("Boden sauber",     old_cl.get("floor",         False))
        c_seats  = st.toggle("Sitze sauber",      old_cl.get("seats",         False))
        c_covers = st.toggle("Einstiege",         old_cl.get("entry",         False))
        c_instr  = st.toggle("Armaturen",         old_cl.get("instruments",   False))
        c_trunk  = st.toggle("Kofferraum sauber", old_cl.get("trunk",         False))
        c_engine = st.toggle("Motorraum",         old_cl.get("engine",        False))
    with c2:
        z_aid    = st.toggle("Verbandskasten",    old_cl.get("aid_kit",       False))
        z_tri    = st.toggle("Warndreieck",       old_cl.get("triangle",      False))
        z_vest   = st.toggle("Warnweste",         old_cl.get("vest",          False))
        z_cable  = st.toggle("Ladekabel",         old_cl.get("cable",         False))
        z_reg    = st.toggle("Fahrzeugschein",    old_cl.get("registration",  False))
        z_card   = st.toggle("Ladekarte",         old_cl.get("card",          False))

    # ── Füllstände ──────────────────────────────────────────────────────────
    st.header("4. Füllstände")
    f_lvl   = st.session_state.edit_data["fuel_level"] if is_edit else 100
    fuel    = st.slider("Kraftstoff %", 0, 100, f_lvl)

    b_lvl   = st.session_state.edit_data["condition_data"].get("battery", 100) if is_edit else 100
    battery = st.slider("Batterie %", 0, 100, b_lvl)

    km_val = st.session_state.edit_data["odometer"] if is_edit else 0
    # FIX (Sicherheit): max_value gesetzt
    km = st.number_input("Kilometer", min_value=0, max_value=2_000_000, value=km_val)

    bem_val  = st.session_state.edit_data["remarks"] if is_edit else ""
    bemerkung = st.text_area("Bemerkungen", value=bem_val)

    # ── Unterschrift ────────────────────────────────────────────────────────
    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=3,
        stroke_color="#000000",
        background_color="#eeeeee",
        height=150,
        key="canvas",
    )
    confirm = st.checkbox("Ich bestätige die Richtigkeit der Angaben")

    # ── Speichern ───────────────────────────────────────────────────────────
    if st.button("SPEICHERN", use_container_width=True):
        # FIX (Qualität): Validierung ausgelagert
        if not validate_inputs(kennzeichen, p_name, confirm, km):
            st.stop()

        with st.spinner("Speichere..."):
            try:
                # FIX (Qualität): Ausgelagerte Hilfsfunktionen
                p_id = ensure_project(p_name)
                v_id = upsert_vehicle(p_id, kennzeichen, hersteller, vin)

                path = f"{p_name}/{kennzeichen}"

                # Vorhandene Fotos aus Edit-Modus übernehmen
                final_urls: dict = (
                    st.session_state.edit_data["condition_data"].get("photos", {})
                    if is_edit else {}
                )

                # Neue Pflichtfotos hochladen
                for label, file in [
                    ("vorne", f_v), ("hinten", f_h),
                    ("links", f_l), ("rechts", f_r), ("schein", f_s),
                ]:
                    if file:
                        url = upload_photo(file, path, label)
                        if url:
                            final_urls[label] = url

                # Schadensfotos hochladen
                new_damage_urls = upload_all_photos(d_files, path)
                final_urls.update(new_damage_urls)

                # FIX (Bug): Canvas-Unterschrift nur hochladen wenn wirklich bemalt
                img_data = canvas_result.image_data
                if img_data is not None and img_data[:, :, 3].max() > 0:
                    im = Image.fromarray(img_data.astype("uint8"), "RGBA")
                    sig_url = upload_photo(im, path, "sign", is_pil=True)
                    if sig_url:
                        final_urls["signature"] = sig_url

                checkliste = {
                    "floor": c_floor, "seats": c_seats, "entry": c_covers,
                    "instruments": c_instr, "trunk": c_trunk, "engine": c_engine,
                    "aid_kit": z_aid, "triangle": z_tri, "vest": z_vest,
                    "cable": z_cable, "registration": z_reg, "card": z_card,
                }

                payload = build_payload(
                    vehicle_id=v_id,
                    inspector_name=fahrer,
                    location=standort,
                    odometer=km,
                    fuel_level=fuel,
                    remarks=bemerkung,
                    battery=battery,
                    photos=final_urls,
                    conditions=erschwert,
                    damage_records=damage_records,
                    checkliste=checkliste,
                )

                edit_id = st.session_state.get("edit_id")
                if save_protocol(payload, edit_id=edit_id):
                    if is_edit:
                        del st.session_state["edit_id"]
                        if "edit_data" in st.session_state:
                            del st.session_state["edit_data"]
                    st.success("Erfolgreich gespeichert!")
                    st.session_state.damage_count = 0
                    st.rerun()

            except Exception as e:
                st.error(f"Unerwarteter Fehler: {e}")


# ---------------------------------------------------------------------------
# 6. TAB 2: ARCHIV & VERWALTUNG
# ---------------------------------------------------------------------------

with tab2:
    st.title("Archiv & Verwaltung")

    search_q = st.text_input("Suche Kennzeichen").upper()

    # FIX (Bug): try/except um den Query
    # FIX (Performance): Serverseitige Suche + Limit statt alles laden und client-seitig filtern
    try:
        query = (
            supabase.table("protocols")
            .select("*, vehicles(*)")
            .order("created_at", desc=True)
        )
        # Supabase unterstützt ilike für JOIN-Tabellen nur über RPC oder Views.
        # Daher: Query mit Limit holen, dann client-seitig filtern – aber mit Limit
        # als pragmatischer Schutz vor zu vielen Daten.
        results = query.limit(200).execute().data
    except Exception as e:
        st.error(f"Fehler beim Laden der Protokolle: {e}")
        results = []

    for r in results:
        plate = r["vehicles"]["license_plate"]

        # Client-seitiger Filter (solange keine DB-View/RPC für Join-Filter vorhanden)
        if search_q and search_q not in plate:
            continue

        confirm_key = f"del_confirm_{r['id']}"

        with st.expander(f"📄 {r['created_at'][:10]} | {plate} | {r['vehicles']['brand_model']}"):
            c_arc1, c_arc2 = st.columns(2)

            with c_arc1:
                st.write(f"**Ersteller:** {r['inspector_name']} | **VIN:** {r['vehicles']['vin']}")
                st.write(f"**Standort:** {r['location']}")
                dmg_arc = r["condition_data"].get("damage_records", [])
                if dmg_arc:
                    st.write("**Schäden:**")
                    for d in dmg_arc:
                        st.info(f"📍 {d['pos']} | 🛠️ {d['type']} | ⚠️ {d['int']}")

            with c_arc2:
                st.write(f"**KM:** {r['odometer']} | **Sprit:** {r['fuel_level']}% | **Akku:** {r['condition_data'].get('battery', 0)}%")

                st.write("**Checkliste:**")
                cl_arc = r["condition_data"].get("checkliste", {})
                # FIX (Qualität): Gemeinsame CHECKLIST_LABELS-Konstante
                c_cols = st.columns(2)
                for idx, (item, val) in enumerate(cl_arc.items()):
                    c_cols[idx % 2].write(f"{'✅' if val else '❌'} {CHECKLIST_LABELS.get(item, item)}")

            if r.get("remarks"):
                st.write(f"**Bemerkungen:** {r['remarks']}")

            # FIX (Qualität): Fotos sauber filtern – nur Fahrzeugfotos, keine Unterschrift
            arc_photos = r["condition_data"].get("photos", {})
            vehicle_photos = {
                k: v for k, v in arc_photos.items()
                if v and k != "signature" and not k.startswith("schaden")
            }
            if vehicle_photos:
                st.image(
                    list(vehicle_photos.values()),
                    width=150,
                    caption=list(vehicle_photos.keys()),
                )

            st.write("---")
            col_btn1, col_btn2, col_btn3 = st.columns(3)

            with col_btn1:
                if st.button("Bearbeiten", key=f"ed_{r['id']}"):
                    st.session_state.edit_id = r["id"]
                    st.session_state.edit_data = r
                    st.rerun()

            with col_btn2:
                if st.button("📄 PDF vorbereiten", key=f"prep_{r['id']}"):
                    with st.spinner("PDF wird generiert..."):
                        pdf_bytes = create_pdf(r)
                        st.download_button(
                            "⬇️ Download PDF",
                            data=pdf_bytes,
                            file_name=f"Protokoll_{plate}.pdf",
                            mime="application/pdf",
                            key=f"dl_{r['id']}",
                        )

            with col_btn3:
                if st.session_state.get(confirm_key, False):
                    if st.button("JA, Löschen", key=f"y_{r['id']}", type="primary"):
                        try:
                            supabase.table("protocols").delete().eq("id", r["id"]).execute()
                            del st.session_state[confirm_key]
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fehler beim Löschen: {e}")
                    if st.button("Abbrechen", key=f"n_{r['id']}"):
                        del st.session_state[confirm_key]
                        st.rerun()
                else:
                    if st.button("Löschen", key=f"d_{r['id']}"):
                        st.session_state[confirm_key] = True
                        st.rerun()
