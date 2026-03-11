import streamlit as st
from supabase import create_client, Client
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io
import base64
import datetime
from zoneinfo import ZoneInfo
import uuid
import requests
import re
import numpy as np
import os
from fpdf import FPDF
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# 1. SETUP & KONFIGURATION
# ---------------------------------------------------------------------------

try:
    url = os.environ.get("SUPABASE_URL") or st.secrets["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_KEY") or st.secrets["SUPABASE_KEY"]
except (KeyError, FileNotFoundError):
    st.error("Supabase-Zugangsdaten fehlen. Bitte SUPABASE_URL und SUPABASE_KEY hinterlegen.")
    st.stop()
if not url or not key:
    st.error("SUPABASE_URL oder SUPABASE_KEY ist leer.")
    st.stop()

supabase: Client = create_client(url, key)

st.set_page_config(
    page_title="Vehicle Protocol Pro",
    layout="wide",
    page_icon="logo.png"
)

st.markdown('<link rel="manifest" href="/manifest.json">', unsafe_allow_html=True)

st.markdown("""
    <style>
    div[role="radiogroup"] {
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        white-space: nowrap !important;
        -webkit-overflow-scrolling: touch;
        padding-bottom: 10px;
    }
    .stButton>button { width: 100%; border-radius: 8px; height: 3em; }
    .stExpander { border: 1px solid #f0f2f6; border-radius: 8px; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

TAB_OPTIONS = [
    "📝 Protokoll erstellen / Bearbeiten",
    "🔍 Archiv & Verwaltung",
    "🚙 Fahrzeug-Überführung",
]

_redirect = st.session_state.pop("nav_redirect", None)
if _redirect in TAB_OPTIONS:
    st.session_state.nav_tab = _redirect

active_tab = st.radio(
    "Navigation",
    TAB_OPTIONS,
    horizontal=True,
    label_visibility="collapsed",
    key="nav_tab",
)
st.divider()

if "transfer_prefill" not in st.session_state:
    st.session_state.transfer_prefill = None
if "transfer_edit_id" not in st.session_state:
    st.session_state.transfer_edit_id = None

# ---------------------------------------------------------------------------
# 2. KONSTANTEN
# ---------------------------------------------------------------------------

MAX_UPLOAD_SIZE_MB = 5

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

CHECKLIST_JA_NEIN = {"aid_kit", "triangle", "vest", "cable", "registration", "card"}

LOGO_PATH           = "logo.png"
PERFECTION_IMG_PATH = "perfection_in_motion.svg"
CONTENT_TOP         = 45.0

PDF_SIG_X      = 145.0
PDF_SIG_Y      = 250.0
PDF_SIG_W      = 55.0
PDF_SIG_BOX_H  = 30.0

PDF_FOTO_COL_X  = [10.0, 108.0]
PDF_FOTO_COL_W  = 87.0
PDF_FOTO_GAP    = 4.0
PDF_FOTO_PORT_H = 95.0
PDF_FOTO_LAND_H = 58.0

PDF_TRANS_BOX_W   = 87.0
PDF_TRANS_LEFT_X  = 10.0
PDF_TRANS_RIGHT_X = 108.0
PDF_TRANS_SIG_W   = 75.0
PDF_TRANS_SIG_H   = 25.0

PDF_GRAU_X = 208.5
PDF_GRAU_Y = 50.0

# ---------------------------------------------------------------------------
# 3. HILFSFUNKTIONEN & DATENBANK
# ---------------------------------------------------------------------------

def render_header_with_logo(title_text: str):
    logo_pfad = LOGO_PATH
    if os.path.exists(logo_pfad):
        with open(logo_pfad, "rb") as img_file:
            b64_string = base64.b64encode(img_file.read()).decode()
        html = f"""
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:nowrap;margin-bottom:45px;">
            <h1 style="margin:0;padding:0;line-height:1.2;">{title_text}</h1>
            <img src="data:image/png;base64,{b64_string}" style="width:70px;flex-shrink:0;margin-right:25px;">
        </div>"""
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.title(title_text)

def sanitize_filename(text: str) -> str:
    if not text:
        return "unbekannt"
    replacements = {
        "ae": "ae", "oe": "oe", "ue": "ue",
        "Ae": "Ae", "Oe": "Oe", "Ue": "Ue",
        "ss": "ss", " ": "_", "&": "und"
    }
    uml = {"ä":"ae","ö":"oe","ü":"ue","Ä":"Ae","Ö":"Oe","Ü":"Ue","ß":"ss"," ":"_","&":"und"}
    for char, rep in uml.items():
        text = text.replace(char, rep)
    return re.sub(r"[^a-zA-Z0-9_\-]", "", text)

def compress_image(data: bytes, max_size_mb: float = MAX_UPLOAD_SIZE_MB, quality: int = 85) -> bytes:
    img = Image.open(io.BytesIO(data))
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.thumbnail((2000, 2000), Image.LANCZOS)
    current_quality = quality
    while current_quality >= 40:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=current_quality, optimize=True)
        if buf.tell() / (1024 * 1024) <= max_size_mb:
            return buf.getvalue()
        current_quality -= 15
    img.thumbnail((1000, 1000), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=40, optimize=True)
    return buf.getvalue()

def upload_photo(file, folder_path: str, p_type: str, is_pil: bool = False) -> str | None:
    if file is None:
        return None
    try:
        clean_parts = [sanitize_filename(part) for part in folder_path.split("/")]
        clean_folder = "/".join(clean_parts)
        
        today_date = datetime.datetime.now(ZoneInfo("Europe/Berlin")).date()
        ext = "jpg"
        path = f"{clean_folder}/{today_date}_{p_type}_{uuid.uuid4().hex[:5]}.{ext}"
        
        if is_pil:
            pil_src = file if isinstance(file, Image.Image) else Image.open(io.BytesIO(file))
            bg = Image.new("RGB", pil_src.size, (255, 255, 255))
            if pil_src.mode == "RGBA":
                bg.paste(pil_src, mask=pil_src.split()[3])
            else:
                bg.paste(pil_src.convert("RGBA"), mask=pil_src.convert("RGBA").split()[3])
            buf = io.BytesIO()
            bg.save(buf, format="JPEG", quality=95)
            content = buf.getvalue()
        else:
            raw = file.getvalue()
            size_mb = len(raw) / (1024 * 1024)
            if size_mb > MAX_UPLOAD_SIZE_MB:
                st.info(f"Komprimiere '{p_type}'...")
                content = compress_image(raw)
            else:
                content = raw
            
        supabase.storage.from_("vehicle-photos").upload(path, content)
        return supabase.storage.from_("vehicle-photos").get_public_url(path)
    except Exception as e:
        st.error(f"Upload-Fehler ({p_type}): {e}")
        return None

def upload_required_photos_parallel(photo_map: dict, path: str) -> dict[str, str]:
    items = [(lbl, f) for lbl, f in photo_map.items() if f is not None]
    if not items:
        return {}
    def _upload_one(args):
        lbl, f = args
        return lbl, upload_photo(f, path, lbl)
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(_upload_one, items))
    return {lbl: u for lbl, u in results if u}

@st.cache_data(ttl=60)
def get_projects() -> list[str]:
    try:
        res = supabase.table("projects").select("name").order("name").execute()
        return [p["name"] for p in res.data]
    except Exception as e:
        st.warning(f"Projekte konnten nicht geladen werden: {e}")
        return []

@st.cache_data(ttl=30)
def get_protocols(status_filter: tuple[str, ...], search_q: str = "") -> list[dict]:
    try:
        query = (
            supabase.table("protocols")
            .select("*, vehicles!inner(*)")
            .order("created_at", desc=True)
        )
        if len(status_filter) == 1:
            query = query.eq("status", status_filter[0])
        elif len(status_filter) > 1:
            query = query.in_("status", list(status_filter))
            
        if search_q:
            query = query.ilike("vehicles.license_plate", f"%{search_q}%")
            
        return query.limit(200).execute().data
    except Exception as e:
        st.error(f"Fehler beim Laden der Protokolle: {e}")
        return []

def validate_inputs(kennzeichen: str, p_name: str, confirm: bool, km: int) -> bool:
    if not kennzeichen:
        st.error("Bitte Kennzeichen eingeben.")
        return False
    if not p_name:
        st.error("Bitte Projektname eingeben.")
        return False
    if not confirm:
        st.error("Bitte Richtigkeit der Angaben bestätigen.")
        return False
    if not (0 <= km <= 2_000_000):
        st.error("KM-Stand scheint unrealistisch (max. 2.000.000 km).")
        return False
    return True

def ensure_project(name: str) -> int:
    supabase.table("projects").upsert({"name": name}, on_conflict="name").execute()
    res = supabase.table("projects").select("id").eq("name", name).execute()
    get_projects.clear()
    return res.data[0]["id"]

def upsert_vehicle(project_id: int, license_plate: str, brand_model: str, vin: str) -> int:
    existing = supabase.table("vehicles").select("id").eq("license_plate", license_plate).execute()
    if existing.data:
        v_id = existing.data[0]["id"]
        supabase.table("vehicles").update({
            "brand_model": brand_model,
            "vin": vin
        }).eq("id", v_id).execute()
        return v_id
    
    res = supabase.table("vehicles").insert(
        {"project_id": project_id, "license_plate": license_plate,
         "brand_model": brand_model, "vin": vin}
    ).execute()
    return res.data[0]["id"]

def upload_all_photos(files: dict, path: str) -> dict:
    urls = {}
    for label, file in files.items():
        if file is not None:
            is_pil = label == "signature"
            result = upload_photo(file, path, label, is_pil=is_pil)
            if result:
                urls[label] = result
    return urls

def build_payload(vehicle_id, inspector_name, location, odometer,
                  fuel_level, remarks, battery, photos, conditions,
                  damage_records, checkliste, receiver_signed_at=None) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "inspector_name": inspector_name,
        "location": location,
        "odometer": odometer,
        "fuel_level": fuel_level,
        "remarks": remarks,
        "inspection_date": datetime.datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "condition_data": {
            "battery": battery,
            "photos": photos,
            "conditions": conditions,
            "damage_records": damage_records,
            "checkliste": checkliste,
        },
    }
    if receiver_signed_at:
        payload["condition_data"]["receiver_signed_at"] = receiver_signed_at
    return payload

def save_protocol(payload: dict, edit_id: int | None = None) -> bool:
    try:
        if edit_id:
            supabase.table("protocols").update(payload).eq("id", edit_id).execute()
        else:
            supabase.table("protocols").insert(payload).execute()
        get_protocols.clear()
        return True
    except Exception as e:
        st.error(f"Fehler beim Speichern: {e}")
        return False

# ---------------------------------------------------------------------------
# 4. GETEILTE UI-KOMPONENTEN
# ---------------------------------------------------------------------------

def render_photo_upload_section(key_prefix: str) -> tuple:
    st.subheader("Pflicht-Fotos (Rundumblick)")
    c1, c2 = st.columns(2)
    with c1:
        fv = st.file_uploader("Vorne",  type=["jpg", "png"], key=f"{key_prefix}_fv")
        fl = st.file_uploader("Links",  type=["jpg", "png"], key=f"{key_prefix}_fl")
        fs = st.file_uploader("Schein", type=["jpg", "png"], key=f"{key_prefix}_fs")
    with c2:
        fh = st.file_uploader("Hinten", type=["jpg", "png"], key=f"{key_prefix}_fh")
        fr = st.file_uploader("Rechts", type=["jpg", "png"], key=f"{key_prefix}_fr")
    return fv, fh, fl, fr, fs

def render_damage_section(key_prefix: str, count_key: str, old_dmgs: list) -> tuple[list, dict]:
    st.subheader("Schäden erfassen")
    if count_key not in st.session_state:
        st.session_state[count_key] = len(old_dmgs)
    if st.button("Neuen Schaden hinzufügen", key=f"{key_prefix}_add_dmg"):
        st.session_state[count_key] += 1
    damage_records: list[dict] = []
    d_files: dict = {}
    POS_LIST  = ["Stossfänger vorne", "Stossfänger hinten", "Motorhaube", "Dach",
                 "Tuer VL", "Tuer VR", "Felge VL", "Felge VR", "Felge HL", "Felge HR"]
    TYPE_LIST = ["Kratzer", "Delle", "Steinschlag", "Riss", "Fehlteil"]
    INT_LIST  = ["Oberflächlich", "Bis Grundierung", "Deformiert"]
    for i in range(st.session_state[count_key]):
        d_val = old_dmgs[i] if i < len(old_dmgs) else {
            "pos": POS_LIST[0], "type": TYPE_LIST[0], "int": INT_LIST[0]
        }
        with st.expander(f"Schaden #{i + 1}", expanded=True):
            d1, d2 = st.columns(2)
            with d1:
                p_idx = POS_LIST.index(d_val["pos"]) if d_val["pos"] in POS_LIST else 0
                pos   = st.selectbox("Position", POS_LIST, index=p_idx, key=f"{key_prefix}_pos_{i}")
                dtype = st.radio(
                    "Art", TYPE_LIST,
                    index=TYPE_LIST.index(d_val["type"]) if d_val["type"] in TYPE_LIST else 0,
                    key=f"{key_prefix}_type_{i}", horizontal=True,
                )
            with d2:
                intens = st.select_slider(
                    "Intensität", options=INT_LIST,
                    value=d_val["int"] if d_val["int"] in INT_LIST else INT_LIST[0],
                    key=f"{key_prefix}_int_{i}",
                )
                df = st.file_uploader(f"Foto Schaden #{i+1}", type=["jpg","png"],
                                      key=f"{key_prefix}_photo_{i}")
                if df:
                    d_files[f"schaden_{i + 1}"] = df
            damage_records.append({"pos": pos, "type": dtype, "int": intens})
    return damage_records, d_files

def render_checklist(key_prefix: str, old_cl: dict) -> dict:
    c1, c2 = st.columns(2)
    with c1:
        floor  = st.toggle("Boden sauber",     old_cl.get("floor",         False), key=f"{key_prefix}_floor")
        seats  = st.toggle("Sitze sauber",     old_cl.get("seats",         False), key=f"{key_prefix}_seats")
        covers = st.toggle("Einstiege",        old_cl.get("entry",         False), key=f"{key_prefix}_entry")
        instr  = st.toggle("Armaturen",        old_cl.get("instruments",   False), key=f"{key_prefix}_instr")
        trunk  = st.toggle("Kofferraum sauber", old_cl.get("trunk",         False), key=f"{key_prefix}_trunk")
        engine = st.toggle("Motorraum",        old_cl.get("engine",        False), key=f"{key_prefix}_engine")
    with c2:
        aid    = st.toggle("Verbandskasten",   old_cl.get("aid_kit",       False), key=f"{key_prefix}_aid")
        tri    = st.toggle("Warndreieck",      old_cl.get("triangle",      False), key=f"{key_prefix}_tri")
        vest   = st.toggle("Warnweste",        old_cl.get("vest",          False), key=f"{key_prefix}_vest")
        cable  = st.toggle("Ladekabel",        old_cl.get("cable",         False), key=f"{key_prefix}_cable")
        reg    = st.toggle("Fahrzeugschein",   old_cl.get("registration",  False), key=f"{key_prefix}_reg")
        card   = st.toggle("Ladekarte",        old_cl.get("card",          False), key=f"{key_prefix}_card")
    return {
        "floor": floor, "seats": seats, "entry": covers,
        "instruments": instr, "trunk": trunk, "engine": engine,
        "aid_kit": aid, "triangle": tri, "vest": vest,
        "cable": cable, "registration": reg, "card": card,
    }

# ---------------------------------------------------------------------------
# 5. PDF-ERSTELLUNG & ZEICHNEN
# ---------------------------------------------------------------------------

def _fetch_image_bytes(url: str) -> bytes | None:
    try:
        return requests.get(url, timeout=10).content
    except Exception:
        return None

def _fetch_photos_parallel(photo_items: list[tuple]) -> list[tuple]:
    urls = [url for _, url in photo_items]
    with ThreadPoolExecutor(max_workers=5) as executor:
        contents = list(executor.map(_fetch_image_bytes, urls))
    return [(label, content) for (label, _), content in zip(photo_items, contents)]

def _prepare_image_bytes(img_bytes: bytes) -> bytes:
    try:
        from PIL import ImageOps
        pil_img = Image.open(io.BytesIO(img_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)
        if pil_img.mode in ("RGBA", "P"):
            bg = Image.new("RGB", pil_img.size, (255, 255, 255))
            rgba = pil_img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[3])
            pil_img = bg
        elif pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return img_bytes

def _get_photo_display_size(img_bytes: bytes, max_w: float, max_h: float) -> tuple[float, float]:
    try:
        pil_img = Image.open(io.BytesIO(img_bytes))
        orig_w, orig_h = pil_img.size
    except Exception:
        return max_w, max_h
    scale  = max_w / orig_w
    disp_w = max_w
    disp_h = orig_h * scale
    if disp_h > max_h:
        scale  = max_h / orig_h
        disp_h = max_h
        disp_w = orig_w * scale
    return disp_w, disp_h

def _canvas_has_stroke(image_data) -> bool:
    if image_data is None:
        return False
    return bool((image_data[:, :, 0] < 200).any())

def _u(text) -> str:
    if not isinstance(text, str):
        text = str(text)
    return text

class UnicodePDF(FPDF):
    def header(self):
        if os.path.exists(LOGO_PATH):
            try:
                self.image(LOGO_PATH, x=175, y=5, w=22)
            except Exception:
                pass
        self.set_fill_color(219, 50, 62)
        self.rect(0, 150, 3, 147, style="F")
        self.set_fill_color(63, 63, 63)
        self.rect(207, 0, 3, 100, style="F")
        
        TEXT_X = 203.0
        TEXT_Y = 100.0
        
        # NEU: Versuch das SVG als Bild zu laden
        if os.path.exists(PERFECTION_IMG_PATH):
            try:
                with self.rotation(90, x=TEXT_X, y=TEXT_Y):
                    # y - 3.0 um das Bild vertikal sauber zum Rand zu zentrieren, w=35 gibt die Breite an
                    self.image(PERFECTION_IMG_PATH, x=TEXT_X, y=TEXT_Y - 3.0, w=35)
            except Exception:
                # Falls das Bild defekt ist oder die PDF Engine es nicht mag: Fallback zum Text
                self._draw_fallback_text(TEXT_X, TEXT_Y)
        else:
            self._draw_fallback_text(TEXT_X, TEXT_Y)

    def _draw_fallback_text(self, text_x, text_y):
        self.set_font("helvetica", "", 8.5)
        self.set_text_color(63, 63, 63)
        with self.rotation(90, x=text_x, y=text_y):
            self.set_xy(text_x, text_y - 2.0)
            self.cell(37, 4, "perfection in motion", align="L")
        self.set_text_color(0, 0, 0)

def _pdf_draw_watermark(pdf: UnicodePDF):
    pdf.set_font("helvetica", "B", 52)
    pdf.set_text_color(200, 200, 200)
    with pdf.rotation(45, x=105, y=148):
        pdf.set_xy(20, 120)
        pdf.cell(0, 20, "VORLÄUFIGER ENTWURF", align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("helvetica", "", 10)

def _pdf_draw_title_and_std_signature(pdf, data, is_transfer, sig_bytes):
    pdf.set_font("helvetica", "B", 16)
    pdf.set_xy(35, 12)
    if is_transfer:
        pdf.cell(150, 10, _u("Fahrzeug-Überführungsprotokoll"), ln=False)
    else:
        pdf.cell(105, 10, _u("Fahrzeug-Übergabeprotokoll"), ln=False)

    if not is_transfer:
        pdf.set_font("helvetica", "", 8)
        pdf.set_xy(PDF_SIG_X, PDF_SIG_Y)
        pdf.cell(PDF_SIG_W, 5, f"Datum: {data['created_at'][:16].replace('T', ' ')}", ln=True, align="C")
        pdf.set_font("helvetica", "B", 8)
        pdf.set_xy(PDF_SIG_X, PDF_SIG_Y + 5)
        pdf.cell(PDF_SIG_W, 5, _u("Unterschrift"), ln=True, align="C")
        if sig_bytes:
            try:
                sp = _prepare_image_bytes(sig_bytes)
                dw, _ = _get_photo_display_size(sp, PDF_SIG_W, PDF_SIG_BOX_H - 6)
                pdf.image(io.BytesIO(sp), x=PDF_SIG_X + (PDF_SIG_W - dw) / 2, y=PDF_SIG_Y + 10, w=dw)
            except Exception:
                pass

def _pdf_draw_basisdaten(pdf, data, is_transfer):
    pdf.set_xy(10, CONTENT_TOP)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "1. Basisdaten", ln=True)
    pdf.set_font("helvetica", "", 10)

    if is_transfer:
        pdf.cell(95, 8, f"Kennzeichen: {data['vehicles']['license_plate']}", border=1)
        pdf.cell(95, 8, f"VIN: {data['vehicles']['vin']}", border=1, ln=True)
        pdf.cell(95, 8, _u(f"Modell: {data['vehicles']['brand_model']}"), border=1)
        pdf.cell(95, 8, f"KM-Stand: {data['odometer']} KM", border=1, ln=True)
        pdf.cell(95, 8, _u(f"Ersteller: {data['inspector_name']}"), border=1)
        recv = _u(data.get("receiver_name") or "-")
        pdf.cell(95, 8, f"Empfänger: {recv}", border=1, ln=True)
        von  = _u(data.get("start_location") or "-")
        nach = _u(data.get("end_location")   or "-")
        pdf.cell(95, 8, f"Von: {von}", border=1)
        pdf.cell(95, 8, f"Nach: {nach}", border=1, ln=True)
        conditions_str = _u(", ".join(data["condition_data"].get("conditions", [])))
        pdf.cell(190, 8, f"Bedingungen: {conditions_str}", border=1, ln=True)
    else:
        pdf.cell(95, 8, f"Kennzeichen: {data['vehicles']['license_plate']}", border=1)
        pdf.cell(95, 8, _u(f"Modell: {data['vehicles']['brand_model']}"), border=1, ln=True)
        pdf.cell(95, 8, f"VIN: {data['vehicles']['vin']}", border=1)
        pdf.cell(95, 8, _u(f"Ersteller: {data['inspector_name']}"), border=1, ln=True)
        pdf.cell(95, 8, f"KM-Stand: {data['odometer']} KM", border=1)
        pdf.cell(95, 8, _u(f"Standort: {data['location']}"), border=1, ln=True)

def _pdf_draw_technik(pdf, data):
    is_transfer = data.get("protocol_type") == "transfer"
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, "2. Technik & Betriebsstoffe", ln=True)
    pdf.set_font("helvetica", "", 10)
    if is_transfer:
        pdf.cell(95, 8, f"Kraftstoff: {data['fuel_level']}%", border=1)
        pdf.cell(95, 8, f"Batterie: {data['condition_data'].get('battery', 0)}%", border=1, ln=True)
    else:
        pdf.cell(63, 8, f"Kraftstoff: {data['fuel_level']}%", border=1)
        pdf.cell(63, 8, f"Batterie: {data['condition_data'].get('battery', 0)}%", border=1)
        pdf.cell(64, 8, _u(f"Bedingungen: {', '.join(data['condition_data'].get('conditions', []))}"), border=1, ln=True)

def _pdf_draw_checkliste(pdf, data):
    def cl_val(key, val):
        return ("Ja" if val else "Nein") if key in CHECKLIST_JA_NEIN else ("Sauber" if val else "Nicht sauber")

    ZUSTAND_KEYS  = ["floor", "seats", "entry", "instruments", "trunk", "engine"]
    ZUBEHOER_KEYS = ["aid_kit", "triangle", "vest", "cable", "registration", "card"]
    cl = data["condition_data"].get("checkliste", {})
    zustand_items  = [(k, cl[k]) for k in ZUSTAND_KEYS  if k in cl]
    zubehoer_items = [(k, cl[k]) for k in ZUBEHOER_KEYS if k in cl]

    pdf.ln(4)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 8, _u("3. Checkliste"), ln=True)

    COL_L = 10; COL_R = 108; COL_W = 90; ROW_H = 7
    y0 = pdf.get_y()
    pdf.set_font("helvetica", "B", 10)
    pdf.set_xy(COL_L, y0); pdf.cell(COL_W, ROW_H, "Zustand", ln=False)
    pdf.set_xy(COL_R, y0); pdf.cell(COL_W, ROW_H, _u("Zubehör"), ln=True)

    pdf.set_font("helvetica", "", 9)
    for i in range(max(len(zustand_items), len(zubehoer_items))):
        y = pdf.get_y()
        if i < len(zustand_items):
            k, v = zustand_items[i]
            pdf.set_xy(COL_L, y)
            pdf.cell(COL_W, ROW_H, f"{CHECKLIST_LABELS.get(k,k)}: {cl_val(k,v)}", border=1)
        if i < len(zubehoer_items):
            k, v = zubehoer_items[i]
            pdf.set_xy(COL_R, y)
            pdf.cell(COL_W, ROW_H, f"{CHECKLIST_LABELS.get(k,k)}: {cl_val(k,v)}", border=1)
        pdf.ln(ROW_H)

def _pdf_draw_bemerkungen(pdf, data):
    if data.get("remarks"):
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "4. Bemerkungen", ln=True)
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(190, 8, _u(data["remarks"]), border=1)

def _pdf_draw_transfer_signatures(pdf, data, sig_bytes, sig_receiver_bytes):
    if pdf.get_y() > 225:
        pdf.add_page()
    else:
        pdf.ln(8)

    footer_y = pdf.get_y()
    BW = PDF_TRANS_BOX_W
    LX = PDF_TRANS_LEFT_X
    RX = PDF_TRANS_RIGHT_X

    pdf.set_font("helvetica", "B", 9)
    pdf.set_xy(LX, footer_y)
    pdf.cell(BW, 6, _u("Übergabe durch (Ersteller)"),  border="TB", ln=False, align="C")
    pdf.set_xy(RX, footer_y)
    pdf.cell(BW, 6, _u("Übernahme durch (Empfänger)"), border="TB", ln=False, align="C")
    pdf.ln(6)

    name_y = pdf.get_y()
    pdf.set_font("helvetica", "", 9)
    pdf.set_xy(LX, name_y)
    pdf.cell(BW, 6, _u(f"Name: {data.get('inspector_name', '')}"), ln=False)
    pdf.set_xy(RX, name_y)
    pdf.cell(BW, 6, _u(f"Name: {data.get('receiver_name', '')}"),  ln=False)
    pdf.ln(6)

    sig_y = pdf.get_y()

    for sig, x in [(sig_bytes, LX), (sig_receiver_bytes, RX)]:
        if sig:
            try:
                sp  = _prepare_image_bytes(sig)
                dw, _ = _get_photo_display_size(sp, PDF_TRANS_SIG_W, PDF_TRANS_SIG_H)
                img_x = x + (BW - dw) / 2
                pdf.image(io.BytesIO(sp), x=img_x, y=sig_y, w=dw)
            except Exception:
                pass
        else:
            pdf.set_draw_color(180, 180, 180)
            pdf.set_xy(x + 5, sig_y + PDF_TRANS_SIG_H - 3)
            pdf.cell(BW - 10, 0, "", border="B")
            pdf.set_draw_color(0, 0, 0)

    ts_y = sig_y + PDF_TRANS_SIG_H + 2
    pdf.set_font("helvetica", "", 8)
    pdf.set_xy(LX, ts_y)
    pdf.cell(BW, 5, f"Datum: {data['created_at'][:16].replace('T', ' ')}", align="C")
    pdf.set_xy(RX, ts_y)
    recv_ts  = data["condition_data"].get("receiver_signed_at", "")
    recv_str = recv_ts[:16].replace("T", " ") if recv_ts else "___________"
    pdf.cell(BW, 5, f"Datum: {recv_str}", align="C")

def _pdf_draw_fotos(pdf, fetched_map):
    HEADER_Y = CONTENT_TOP + 10
    ROW_Y = [
        HEADER_Y,
        HEADER_Y + PDF_FOTO_PORT_H + PDF_FOTO_GAP,
        HEADER_Y + PDF_FOTO_PORT_H + PDF_FOTO_GAP + PDF_FOTO_LAND_H + PDF_FOTO_GAP,
    ]
    SLOTS = [
        ("vorne",  0, 0, PDF_FOTO_PORT_H),
        ("hinten", 1, 0, PDF_FOTO_PORT_H),
        ("links",  0, 1, PDF_FOTO_LAND_H),
        ("rechts", 1, 1, PDF_FOTO_LAND_H),
        ("schein", 1, 2, PDF_FOTO_LAND_H),
    ]
    if not any(fetched_map.get(lbl) for lbl, *_ in SLOTS):
        return
    pdf.add_page()
    pdf.set_font("helvetica", "B", 12)
    pdf.set_xy(10, CONTENT_TOP)
    pdf.cell(0, 8, "5. Fotodokumentation", ln=True)
    for label, col_idx, row_idx, max_h in SLOTS:
        raw = fetched_map.get(label)
        if not raw:
            continue
        img = _prepare_image_bytes(raw)
        x   = PDF_FOTO_COL_X[col_idx]
        y   = ROW_Y[row_idx]
        dw, _ = _get_photo_display_size(img, PDF_FOTO_COL_W, max_h)
        try:
            pdf.image(io.BytesIO(img), x=x + (PDF_FOTO_COL_W - dw) / 2, y=y, w=dw)
        except Exception:
            pass

def _pdf_draw_schaden(pdf, data, schaden_items):
    dmg = data["condition_data"].get("damage_records", [])
    if not dmg and not schaden_items:
        return
    pdf.add_page()
    pdf.set_xy(10, CONTENT_TOP)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, _u("6. Erfasste Schäden"), ln=True)
    if dmg:
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(60, 7, "Position", border=1)
        pdf.cell(60, 7, "Art", border=1)
        pdf.cell(70, 7, _u("Intensität"), border=1, ln=True)
        pdf.set_font("helvetica", "", 9)
        for d in dmg:
            pdf.cell(60, 7, _u(d["pos"]), border=1)
            pdf.cell(60, 7, _u(d["type"]), border=1)
            pdf.cell(70, 7, _u(d["int"]),  border=1, ln=True)
    if schaden_items:
        pdf.ln(6)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 8, "Schadensfotos:", ln=True)
        S_COL_X = [10.0, 108.0]; S_COL_W = 87.0; S_MAX_H = 100.0
        s_col = 0; s_y = pdf.get_y() + 2
        for label, raw in _fetch_photos_parallel(schaden_items):
            if not raw:
                continue
            img = _prepare_image_bytes(raw)
            dw, dh = _get_photo_display_size(img, S_COL_W, S_MAX_H)
            if s_y + dh + 10 > 275:
                pdf.add_page(); s_y = 15; s_col = 0
            try:
                pdf.image(io.BytesIO(img), x=S_COL_X[s_col] + (S_COL_W - dw) / 2, y=s_y, w=dw)
            except Exception:
                pass
            s_col += 1
            if s_col > 1:
                s_col = 0
                s_y += max(dh, S_MAX_H) + 10

def create_pdf(data: dict, is_transfer: bool = False, status: str = "final") -> bytes:
    pdf = UnicodePDF()
    pdf.add_page()
    photos = data["condition_data"].get("photos", {})

    sig_bytes = (
        _fetch_image_bytes(photos["signature"])
        if photos.get("signature") else None
    )
    sig_receiver_bytes = (
        _fetch_image_bytes(photos["signature_receiver"])
        if is_transfer and photos.get("signature_receiver") else None
    )

    _pdf_draw_title_and_std_signature(pdf, data, is_transfer, sig_bytes)
    _pdf_draw_basisdaten(pdf, data, is_transfer)
    _pdf_draw_technik(pdf, data)
    _pdf_draw_checkliste(pdf, data)
    _pdf_draw_bemerkungen(pdf, data)

    if is_transfer:
        _pdf_draw_transfer_signatures(pdf, data, sig_bytes, sig_receiver_bytes)

    RUNDUMBLICK    = ["vorne", "hinten", "links", "rechts", "schein"]
    schaden_labels = [lbl for lbl in photos if lbl.startswith("schaden") and photos[lbl]]
    all_items      = (
        [(lbl, photos[lbl]) for lbl in RUNDUMBLICK    if photos.get(lbl)]
        + [(lbl, photos[lbl]) for lbl in schaden_labels]
    )
    fetched_map   = dict(_fetch_photos_parallel(all_items)) if all_items else {}
    schaden_items = [(lbl, photos[lbl]) for lbl in schaden_labels]

    _pdf_draw_fotos(pdf, fetched_map)
    _pdf_draw_schaden(pdf, data, schaden_items)

    if status == "draft":
        total_pages = pdf.pages
        for p in range(1, total_pages + 1):
            pdf.page = p
            _pdf_draw_watermark(pdf)
        pdf.page = total_pages

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# 6. TAB 1: PROTOKOLL ERSTELLEN / BEARBEITEN
# ---------------------------------------------------------------------------

if active_tab == "📝 Protokoll erstellen / Bearbeiten":
    is_edit = "edit_id" in st.session_state and "edit_data" in st.session_state

    if is_edit:
        st.warning(f"Bearbeitungsmodus: {st.session_state.edit_data['vehicles']['license_plate']}")
        if st.button("Abbrechen"):
            del st.session_state["edit_id"]
            if "edit_data" in st.session_state:
                del st.session_state["edit_data"]
            st.session_state.damage_count = 0
            st.rerun()

    render_header_with_logo("Fahrzeug-Übergabe")

    st.header("1. Basisdaten")
    projekte  = get_projects()
    auswahl_p = st.selectbox("Projekt", ["-- Neues Projekt erstellen --"] + projekte)
    p_name    = st.text_input("Projektname") if auswahl_p == "-- Neues Projekt erstellen --" else auswahl_p

    col1, col2 = st.columns(2)
    with col1:
        k_val       = st.session_state.edit_data["vehicles"]["license_plate"] if is_edit else ""
        kennzeichen = st.text_input("Kennzeichen", value=k_val).upper()
        vin_val     = st.session_state.edit_data["vehicles"]["vin"] if is_edit else ""
        vin         = st.text_input("VIN", value=vin_val)
        f_val       = st.session_state.edit_data["inspector_name"] if is_edit else ""
        fahrer      = st.text_input("Ersteller", value=f_val)
    with col2:
        h_val      = st.session_state.edit_data["vehicles"]["brand_model"] if is_edit else ""
        hersteller = st.text_input("Modell", value=h_val)
        s_val      = st.session_state.edit_data["location"] if is_edit else ""
        standort   = st.text_input("Standort", value=s_val)
        st.text_input("Datum", value=datetime.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M"), disabled=True)

    st.header("2. Sichtprüfung & Schadenserfassung")
    erschwert_val = st.session_state.edit_data["condition_data"].get("conditions", []) if is_edit else []
    erschwert = st.multiselect(
        "Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"],
        default=erschwert_val,
    )

    f_v, f_h, f_l, f_r, f_s = render_photo_upload_section("t1")

    old_dmgs = st.session_state.edit_data["condition_data"].get("damage_records", []) if is_edit else []
    damage_records, d_files = render_damage_section("t1", "damage_count", old_dmgs)

    st.header("3. Checkliste")
    old_cl     = st.session_state.edit_data["condition_data"].get("checkliste", {}) if is_edit else {}
    checkliste = render_checklist("t1", old_cl)

    st.header("4. Füllstände")
    f_lvl    = int(st.session_state.edit_data.get("fuel_level") or 100) if is_edit else 100
    fuel     = st.slider("Kraftstoff %", 0, 100, f_lvl)
    b_lvl    = int(st.session_state.edit_data["condition_data"].get("battery") or 100) if is_edit else 100
    battery  = st.slider("Batterie %", 0, 100, b_lvl)
    km_val   = int(st.session_state.edit_data.get("odometer") or 0) if is_edit else 0
    km       = st.number_input("Kilometer", min_value=0, max_value=2_000_000, value=km_val)
    bem_val  = st.session_state.edit_data.get("remarks") or "" if is_edit else ""
    bemerkung = st.text_area("Bemerkungen", value=bem_val)

    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3,
        stroke_color="#000000", background_color="#eeeeee",
        height=150,
        width=350,
        key="canvas",
    )
    confirm = st.checkbox("Ich bestätige die Richtigkeit der Angaben")

    if st.button("SPEICHERN", use_container_width=True):
        if not validate_inputs(kennzeichen, p_name, confirm, km):
            st.stop()
        with st.spinner("Speichere..."):
            try:
                p_id = ensure_project(p_name)
                v_id = upsert_vehicle(p_id, kennzeichen, hersteller, vin)
                path = f"{p_name}/{kennzeichen}"
                final_urls: dict = (
                    st.session_state.edit_data["condition_data"].get("photos", {}).copy()
                    if is_edit else {}
                )
                new_required = upload_required_photos_parallel(
                    {"vorne": f_v, "hinten": f_h, "links": f_l, "rechts": f_r, "schein": f_s}, path
                )
                final_urls.update(new_required)
                final_urls.update(upload_all_photos(d_files, path))

                img_data = canvas_result.image_data
                if img_data is not None and _canvas_has_stroke(img_data):
                    im = Image.fromarray(img_data.astype("uint8"), "RGBA")
                    sig_url = upload_photo(im, path, "sign", is_pil=True)
                    if sig_url:
                        final_urls["signature"] = sig_url

                payload = build_payload(
                    vehicle_id=v_id, inspector_name=fahrer, location=standort,
                    odometer=km, fuel_level=fuel, remarks=bemerkung,
                    battery=battery, photos=final_urls, conditions=erschwert,
                    damage_records=damage_records, checkliste=checkliste,
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
# 7. TAB 2: ARCHIV & VERWALTUNG
# ---------------------------------------------------------------------------

elif active_tab == "🔍 Archiv & Verwaltung":
    render_header_with_logo("Archiv & Verwaltung")

    search_q = st.text_input("Suche Kennzeichen").upper()
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        filter_type = st.radio(
            "Protokoll-Typ", ["Alle", "Nur Standard", "Nur Überführungen"], horizontal=True,
        )
    with filter_col2:
        filter_status = st.multiselect("Status", ["final", "draft"], default=["final", "draft"])

    results = get_protocols(tuple(filter_status), search_q)

    for r in results:
        plate    = r["vehicles"]["license_plate"]
        r_type   = r.get("protocol_type", "standard")
        r_status = r.get("status", "final")

        if search_q and search_q not in plate:
            continue
        if filter_type == "Nur Standard"      and r_type == "transfer":
            continue
        if filter_type == "Nur Überführungen" and r_type != "transfer":
            continue

        confirm_key       = f"del_confirm_{r['id']}"
        is_transfer_entry = r_type == "transfer"
        badge = " ⚠️ ENTWURF" if r_status == "draft" else ""

        with st.expander(f"📄 {r['created_at'][:10]} | {plate} | {r['vehicles']['brand_model']}{badge}"):
            if r_status == "draft":
                if is_transfer_entry:
                    st.warning("Dieses Protokoll ist noch nicht abgeschlossen. Die Empfänger-Unterschrift fehlt noch.")
                else:
                    st.warning("Dieses Protokoll ist noch ein Entwurf und wurde noch nicht finalisiert.")

            c_arc1, c_arc2 = st.columns(2)
            with c_arc1:
                st.write(f"**Ersteller:** {r['inspector_name']} | **VIN:** {r['vehicles']['vin']}")
                if is_transfer_entry:
                    st.write(f"**Route:** {r.get('start_location') or '-'} -> {r.get('end_location') or '-'}")
                    st.write(f"**Empfänger:** {r.get('receiver_name') or '-'}")
                else:
                    st.write(f"**Standort:** {r['location']}")
                for d in r["condition_data"].get("damage_records", []):
                    st.info(f"📍 {d['pos']} | 🛠️ {d['type']} | ⚠️ {d['int']}")

            with c_arc2:
                st.write(f"**KM:** {r['odometer']} | **Sprit:** {r['fuel_level']}% | **Akku:** {r['condition_data'].get('battery', 0)}%")
                st.write("**Checkliste:**")
                cl_arc = r["condition_data"].get("checkliste", {})
                c_cols = st.columns(2)
                for idx, (item, val) in enumerate(cl_arc.items()):
                    c_cols[idx % 2].write(f"{'✅' if val else '❌'} {CHECKLIST_LABELS.get(item, item)}")

            if r.get("remarks"):
                st.write(f"**Bemerkungen:** {r['remarks']}")

            arc_photos = r["condition_data"].get("photos", {})
            vehicle_photos = {
                k: v for k, v in arc_photos.items()
                if v and k not in ("signature", "signature_receiver") and not k.startswith("schaden")
            }
            if vehicle_photos:
                st.image(list(vehicle_photos.values()), width=150, caption=list(vehicle_photos.keys()))

            st.write("---")

            col_btn1, col_btn2, col_btn3 = st.columns(3)

            with col_btn1:
                if st.button("✏️ Bearbeiten", key=f"ed_{r['id']}"):
                    if is_transfer_entry:
                        st.session_state.transfer_prefill  = r
                        st.session_state.transfer_edit_id = r["id"]
                        st.session_state.nav_redirect = "🚙 Fahrzeug-Überführung"
                    else:
                        st.session_state.edit_id   = r["id"]
                        st.session_state.edit_data = r
                        st.session_state.nav_redirect = "📝 Protokoll erstellen / Bearbeiten"
                    st.rerun()

            with col_btn2:
                pdf_key = f"pdf_bytes_{r['id']}"
                if st.button("📄 PDF generieren", key=f"prep_{r['id']}"):
                    with st.spinner("PDF wird generiert..."):
                        st.session_state[pdf_key] = create_pdf(r, is_transfer=is_transfer_entry, status=r_status)

            with col_btn3:
                if st.session_state.get(confirm_key, False):
                    if st.button("JA, Löschen", key=f"y_{r['id']}", type="primary"):
                        try:
                            supabase.table("protocols").delete().eq("id", r["id"]).execute()
                            del st.session_state[confirm_key]
                            get_protocols.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fehler beim Löschen: {e}")
                    if st.button("Abbrechen", key=f"n_{r['id']}"):
                        del st.session_state[confirm_key]; st.rerun()
                else:
                    if st.button("🗑️ Löschen", key=f"d_{r['id']}"):
                        st.session_state[confirm_key] = True; st.rerun()

        # Download-Button AUSSERHALB des Expanders
        pdf_key = f"pdf_bytes_{r['id']}"
        if st.session_state.get(pdf_key):
            fname = sanitize_filename(f"{'Ueberfuehrung' if is_transfer_entry else 'Protokoll'}_{plate}") + ".pdf"
            st.download_button(
                f"⬇️ PDF herunterladen: {plate}",
                data=st.session_state[pdf_key],
                file_name=fname,
                mime="application/pdf",
                key=f"dl_{r['id']}",
                use_container_width=True,
            )

# ---------------------------------------------------------------------------
# 8. TAB 3: FAHRZEUG-ÜBERFÜHRUNG
# ---------------------------------------------------------------------------

elif active_tab == "🚙 Fahrzeug-Überführung":
    prefill    = st.session_state.get("transfer_prefill")
    t3_edit_id = st.session_state.get("transfer_edit_id")
    is_t3_edit = prefill is not None

    if is_t3_edit:
        pf_plate = prefill["vehicles"]["license_plate"]
        st.success(f"Entwurf geladen: {pf_plate} - bitte Empfänger-Unterschrift ergänzen und finalisieren.")
        if st.button("Abbrechen / Neues Protokoll", key="t3_cancel"):
            st.session_state.transfer_prefill  = None
            st.session_state.transfer_edit_id  = None
            st.rerun()

    render_header_with_logo("Fahrzeug-Überführung")

    st.header("1. Basisdaten")
    pf_cd = prefill["condition_data"] if is_t3_edit else {}

    projekte_t3 = get_projects()
    auswahl_t3  = st.selectbox("Projekt", ["-- Neues Projekt erstellen --"] + projekte_t3, key="t3_proj_sel")
    pf_proj     = prefill["vehicles"].get("project_name", "") if is_t3_edit else ""
    p_name_t3   = (
        st.text_input("Projektname", value=pf_proj, key="t3_proj_new")
        if auswahl_t3 == "-- Neues Projekt erstellen --" else auswahl_t3
    )

    col_t3a, col_t3b = st.columns(2)
    with col_t3a:
        kennzeichen_t3   = st.text_input("Kennzeichen", value=prefill["vehicles"]["license_plate"] if is_t3_edit else "", key="t3_kz").upper()
        vin_t3           = st.text_input("VIN",         value=prefill["vehicles"]["vin"]           if is_t3_edit else "", key="t3_vin")
        fahrer_t3        = st.text_input("Ersteller",   value=prefill["inspector_name"]            if is_t3_edit else "", key="t3_fahrer")
        receiver_name_t3 = st.text_input("Empfänger Name", value=prefill.get("receiver_name","")  if is_t3_edit else "", key="t3_receiver")
    with col_t3b:
        hersteller_t3 = st.text_input("Modell",        value=prefill["vehicles"]["brand_model"]   if is_t3_edit else "", key="t3_modell")
        von_t3        = st.text_input("Von (Startort)", value=prefill.get("start_location","")     if is_t3_edit else "", key="t3_von")
        nach_t3       = st.text_input("Nach (Zielort)", value=prefill.get("end_location","")       if is_t3_edit else "", key="t3_nach")
        st.text_input("Datum", value=datetime.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M"), disabled=True, key="t3_datum")

    st.header("2. Sichtprüfung & Schadenserfassung")
    pf_cond = pf_cd.get("conditions", []) if is_t3_edit else []
    erschwert_t3 = st.multiselect(
        "Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"],
        default=pf_cond, key="t3_bed",
    )

    t3_fv, t3_fh, t3_fl, t3_fr, t3_fs = render_photo_upload_section("t3")

    old_t3_dmgs = pf_cd.get("damage_records", []) if is_t3_edit else []
    t3_damage_records, t3_d_files = render_damage_section("t3", "t3_damage_count", old_t3_dmgs)

    st.header("3. Checkliste")
    old_t3_cl     = pf_cd.get("checkliste", {}) if is_t3_edit else {}
    t3_checkliste = render_checklist("t3", old_t3_cl)

    st.header("4. Füllstände")
    t3_fuel    = st.slider("Kraftstoff %", 0, 100, int(prefill.get("fuel_level") or 100) if is_t3_edit else 100, key="t3_fuel")
    t3_battery = st.slider("Batterie %",   0, 100, int(pf_cd.get("battery") or 100)       if is_t3_edit else 100, key="t3_batt")
    t3_km      = st.number_input("Kilometer", min_value=0, max_value=2_000_000,
                                 value=int(prefill.get("odometer") or 0) if is_t3_edit else 0, key="t3_km")
    t3_bem     = st.text_area("Bemerkungen", value=prefill.get("remarks") or "" if is_t3_edit else "", key="t3_bem")

    st.header("5. Unterschriften")
    st.caption("Die Ersteller-Unterschrift reicht zum Zwischenspeichern. Beim Finalisieren werden beide benötigt.")

    sig_col1, sig_col2 = st.columns(2)
    with sig_col1:
        st.subheader("Ersteller / Überbringer")
        canvas_t3_creator = st_canvas(
            fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3,
            stroke_color="#000000", background_color="#eeeeee",
            height=150,
            width=350,
            key="canvas_t3_creator",
        )
    with sig_col2:
        st.subheader("Empfänger / Übernehmer")
        st.caption("Optional beim Zwischenspeichern - Pflicht beim Finalisieren.")
        canvas_t3_receiver = st_canvas(
            fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3,
            stroke_color="#000000", background_color="#eeeeee",
            height=150,
            width=350,
            key="canvas_t3_receiver",
        )
    confirm_t3 = st.checkbox("Ich bestätige die Richtigkeit der Angaben", key="t3_confirm")

    btn_col1, btn_col2 = st.columns(2)

    def _t3_creator_signed() -> bool:
        img = canvas_t3_creator.image_data
        return _canvas_has_stroke(img)

    def _t3_receiver_signed() -> bool:
        img = canvas_t3_receiver.image_data
        return _canvas_has_stroke(img)

    def _save_transfer(status_val: str):
        if not validate_inputs(kennzeichen_t3, p_name_t3, confirm_t3, t3_km):
            st.stop()
        if not von_t3.strip():
            st.error("Bitte Startort (Von) eingeben."); st.stop()
        if not nach_t3.strip():
            st.error("Bitte Zielort (Nach) eingeben."); st.stop()
        existing_sig_receiver = pf_cd.get("photos", {}).get("signature_receiver") if is_t3_edit else None
        if status_val == "final" and not _t3_receiver_signed() and not existing_sig_receiver:
            st.error("Für das Finalisieren wird die Empfänger-Unterschrift benötigt."); st.stop()

        with st.spinner("Speichere..."):
            try:
                p_id_t3 = ensure_project(p_name_t3)
                v_id_t3 = upsert_vehicle(p_id_t3, kennzeichen_t3, hersteller_t3, vin_t3)
                path_t3 = f"{p_name_t3}/{kennzeichen_t3}"

                final_urls_t3: dict = pf_cd.get("photos", {}).copy() if is_t3_edit else {}

                new_required_t3 = upload_required_photos_parallel(
                    {"vorne": t3_fv, "hinten": t3_fh, "links": t3_fl, "rechts": t3_fr, "schein": t3_fs},
                    path_t3
                )
                final_urls_t3.update(new_required_t3)
                final_urls_t3.update(upload_all_photos(t3_d_files, path_t3))

                if _t3_creator_signed():
                    im_c = Image.fromarray(canvas_t3_creator.image_data.astype("uint8"), "RGBA")
                    url_c = upload_photo(im_c, path_t3, "sign", is_pil=True)
                    if url_c:
                        final_urls_t3["signature"] = url_c

                if _t3_receiver_signed():
                    im_r = Image.fromarray(canvas_t3_receiver.image_data.astype("uint8"), "RGBA")
                    url_r = upload_photo(im_r, path_t3, "sign_receiver", is_pil=True)
                    if url_r:
                        final_urls_t3["signature_receiver"] = url_r

                recv_time = datetime.datetime.now(ZoneInfo("Europe/Berlin")).isoformat() if (_t3_receiver_signed() and "signature_receiver" in final_urls_t3) else None

                payload_t3 = build_payload(
                    vehicle_id=v_id_t3, inspector_name=fahrer_t3, location=von_t3,
                    odometer=t3_km, fuel_level=t3_fuel, remarks=t3_bem,
                    battery=t3_battery, photos=final_urls_t3, conditions=erschwert_t3,
                    damage_records=t3_damage_records, checkliste=t3_checkliste,
                    receiver_signed_at=recv_time
                )
                payload_t3["protocol_type"]  = "transfer"
                payload_t3["status"]         = status_val
                payload_t3["start_location"] = von_t3
                payload_t3["end_location"]   = nach_t3
                payload_t3["receiver_name"]  = receiver_name_t3

                if save_protocol(payload_t3, edit_id=t3_edit_id):
                    st.session_state.transfer_prefill = None
                    st.session_state.transfer_edit_id = None
                    st.session_state.t3_damage_count  = 0
                    label = "Finalisiert" if status_val == "final" else "Als Entwurf gespeichert"
                    st.success(f"{label}!")
                    st.rerun()

            except Exception as e:
                st.error(f"Unerwarteter Fehler: {e}")

    with btn_col1:
        if st.button("Zwischenspeichern (Entwurf)", use_container_width=True):
            _save_transfer("draft")
    with btn_col2:
        if st.button("Protokoll finalisieren", use_container_width=True, type="primary"):
            _save_transfer("final")