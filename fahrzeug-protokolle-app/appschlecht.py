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
import tempfile
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

# ---------------------------------------------------------------------------
# 2. KONSTANTEN
# ---------------------------------------------------------------------------

LOGO_WEB_PATH       = "logo.png"            
LOGO_PDF_PATH       = "carhandling.png"     
CONTENT_TOP         = 45.0

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

PDF_SIG_BOX_H  = 30.0

st.set_page_config(
    page_title="Vehicle Protocol Pro",
    layout="wide",
    page_icon=LOGO_WEB_PATH
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
    
    /* Tabs für Mobile untereinander stapeln und Sticky Header */
    div[data-testid="stTabs"] {
        display: flex;
        flex-direction: column;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-list"] {
        flex-direction: column !important;
        width: 100% !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab"] {
        width: 100% !important;
        text-align: left !important;
        padding: 10px 20px !important;
    }
    div[data-testid="stTabs"] > div:first-child {
        position: sticky;
        top: 0;
        background-color: var(--default-backgroundColor); 
        z-index: 999;
        padding-top: 10px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.2);
    }
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

tab1, tab2, tab3 = st.tabs(TAB_OPTIONS)

if "transfer_prefill" not in st.session_state:
    st.session_state.transfer_prefill = None
if "transfer_edit_id" not in st.session_state:
    st.session_state.transfer_edit_id = None

# ---------------------------------------------------------------------------
# 3. HILFSFUNKTIONEN & DATENBANK
# ---------------------------------------------------------------------------

def render_header_with_logo(title_text: str):
    logo_pfad = LOGO_WEB_PATH
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
        fh = st.file_uploader("Hinten", type=["jpg", "png"], key=f"{key_prefix}_fh")
    with c2:
        fr = st.file_uploader("Rechts", type=["jpg", "png"], key=f"{key_prefix}_fr")
        fs = st.file_uploader("Schein", type=["jpg", "png"], key=f"{key_prefix}_fs")
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
        "cable": cable, "registration": reg, "card": card
    }

# ---------------------------------------------------------------------------
# 5. PDF ERSTELLUNG (Exakt mit RAHMEN, großen Logo & richtigen Schriftmaßen)
# ---------------------------------------------------------------------------

class PDF(FPDF):
    def header(self):
        # Roter Streifen links unten
        self.set_fill_color(219, 50, 62)
        self.rect(0, 150, 3, 147, style="F")
        
        # Grauer Streifen rechts oben
        self.set_fill_color(63, 63, 63)
        self.rect(207, 0, 3, 100, style="F")
        
        # Slogan vertikal links NEBEN dem grauen Balken (RICHTIGE GRÖßE & POSITION)
        self.set_font("helvetica", "", 12)
        self.set_text_color(63, 63, 63)
        TEXT_X = 204.0
        TEXT_Y = 95.0
        
        with self.rotation(90, x=TEXT_X, y=TEXT_Y):
            self.set_xy(TEXT_X - 50, TEXT_Y - 2)
            self.cell(50, 5, "perfection in motion", align="R")
            
        self.set_text_color(0, 0, 0) # Wichtig: Textfarbe wieder auf Schwarz setzen
        
        # Logo richtig platziert (oben rechts)
        if os.path.exists(LOGO_PDF_PATH):
            self.image(LOGO_PDF_PATH, x=160, y=10, w=40)
            
        self.set_y(15)
        self.set_font("helvetica", "B", 16)
        title = getattr(self, "doc_title", "Fahrzeug-Übergabeprotokoll")
        self.cell(0, 10, title, ln=True, align="L")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Seite {self.page_no()}", align="C")

def _u(text: str) -> str:
    return str(text).encode('latin-1', 'replace').decode('latin-1')

def create_pdf(data: dict, is_transfer: bool = False, status: str = "final") -> bytes:
    pdf = PDF()
    pdf.doc_title = "Fahrzeug-Übergabeprotokoll" if not is_transfer else "Fahrzeug-Transferprotokoll"
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    LX = 10.0
    RX = 105.0
    BW = 90.0

    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "1. Basisdaten", ln=True)
    pdf.set_font("helvetica", "", 10)

    v = data["vehicles"]
    c_data = data.get("condition_data", {})

    pdf.set_xy(LX, CONTENT_TOP)
    # RAHMEN EINGEFÜGT (border=1)
    pdf.cell(BW, 8, _u(f"Kennzeichen: {v['license_plate']}"), border=1)
    pdf.set_xy(LX, CONTENT_TOP + 8)
    pdf.cell(BW, 8, _u(f"VIN: {v['vin']}"), border=1)
    pdf.set_xy(LX, CONTENT_TOP + 16)
    pdf.cell(BW, 8, _u(f"KM-Stand: {data['odometer']} KM"), border=1)
    
    pdf.set_xy(RX, CONTENT_TOP)
    if is_transfer:
        pdf.cell(BW, 8, _u(f"Marke: {c_data.get('brand','-')} | Modell: {v['brand_model']}"), border=1)
        pdf.set_xy(RX, CONTENT_TOP + 8)
        pdf.cell(BW, 8, _u(f"Start: {data.get('start_location','-')} -> Ziel: {data.get('end_location','-')}"), border=1)
        pdf.set_xy(RX, CONTENT_TOP + 16)
        pdf.cell(BW, 8, _u(f"Status: {status.upper()}"), border=1)
    else:
        pdf.cell(BW, 8, _u(f"Modell: {v['brand_model']}"), border=1)
        pdf.set_xy(RX, CONTENT_TOP + 8)
        pdf.cell(BW, 8, _u(f"Ersteller: {data['inspector_name']}"), border=1)
        pdf.set_xy(RX, CONTENT_TOP + 16)
        pdf.cell(BW, 8, _u(f"Standort: {data['location']}"), border=1)

    y_tech = CONTENT_TOP + 28
    pdf.set_xy(LX, y_tech)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "2. Technik & Betriebsstoffe", ln=True)
    pdf.set_font("helvetica", "", 10)
    
    pdf.set_xy(LX, y_tech + 10)
    pdf.cell(BW, 8, _u(f"Kraftstoff: {data['fuel_level']}%"), border=1)
    pdf.set_xy(LX, y_tech + 18)
    pdf.cell(BW, 8, _u(f"Batterie: {c_data.get('battery', 0)}%"), border=1)

    y_chk = y_tech + 30
    pdf.set_xy(LX, y_chk)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "3. Checkliste", ln=True)
    pdf.set_font("helvetica", "B", 10)
    
    # RAHMEN EINGEFÜGT (border=1, fill=True)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_xy(LX, y_chk + 10)
    pdf.cell(BW, 6, "Zustand", border=1, fill=True)
    pdf.set_xy(RX, y_chk + 10)
    pdf.cell(BW, 6, "Zubehör", border=1, fill=True)
    
    pdf.set_font("helvetica", "", 9)
    cl = c_data.get("checkliste", {})
    y_list = y_chk + 16

    keys_zustand = ["floor", "seats", "entry", "instruments", "trunk", "engine"]
    keys_zubehor = ["aid_kit", "triangle", "vest", "cable", "registration", "card"]

    for i, k in enumerate(keys_zustand):
        pdf.set_xy(LX, y_list + i*6)
        val = cl.get(k, False)
        status_text = "Sauber" if val else "Nicht Sauber"
        if k in ["instruments", "engine"]:
            status_text = "OK" if val else "Mangel"
        pdf.cell(BW, 6, _u(f"{CHECKLIST_LABELS.get(k, k)}: {status_text}"), border=1)

    for i, k in enumerate(keys_zubehor):
        pdf.set_xy(RX, y_list + i*6)
        val = cl.get(k, False)
        status_text = "Ja" if val else "Nein"
        pdf.cell(BW, 6, _u(f"{CHECKLIST_LABELS.get(k, k)}: {status_text}"), border=1)

    y_rem = y_list + max(len(keys_zustand), len(keys_zubehor))*6 + 8
    pdf.set_xy(LX, y_rem)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "4. Bemerkungen", ln=True)
    pdf.set_font("helvetica", "", 10)
    
    y_text = y_rem + 10
    if data.get("remarks"):
        pdf.set_xy(LX, y_text)
        pdf.multi_cell(185, 6, _u(data["remarks"]), border=1)
        y_text = pdf.get_y() + 4

    conds = c_data.get("conditions", [])
    if conds:
        pdf.set_xy(LX, y_text)
        pdf.cell(185, 6, _u(f"Bedingungen: {', '.join(conds)}"), border=1)
        y_text += 8

    date_str = data.get("inspection_date", data.get("created_at", ""))[:16].replace("T", " ")
    pdf.set_xy(LX, y_text)
    pdf.cell(185, 6, _u(f"Datum: {date_str}"), border=1)

    y_sig_title = y_text + 12
    pdf.set_xy(LX, y_sig_title)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "Unterschrift", ln=True)

    sig_url = c_data.get("photos", {}).get("signature") or c_data.get("photos", {}).get("sig_inspector") or c_data.get("photos", {}).get("sig_driver")
    
    # Kasten für die Unterschrift
    pdf.rect(LX, y_sig_title + 10, BW, PDF_SIG_BOX_H)
    if is_transfer:
        pdf.rect(RX, y_sig_title + 10, BW, PDF_SIG_BOX_H)
        
    if sig_url:
        try:
            img_data = requests.get(sig_url, timeout=10).content
            img = Image.open(io.BytesIO(img_data))
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                img.save(tmp.name, format="JPEG")
                pdf.image(tmp.name, x=LX+2, y=y_sig_title + 11, h=PDF_SIG_BOX_H-2)
        except Exception:
            pass

    name_y = y_sig_title + 10 + PDF_SIG_BOX_H
    pdf.set_font("helvetica", "", 10)
    if is_transfer:
        pdf.set_xy(LX, name_y)
        pdf.cell(BW, 6, _u(f"Name: {data.get('inspector_name', '')}"), border=1)
        pdf.set_xy(RX, name_y)
        pdf.cell(BW, 6, _u(f"Name: {data.get('receiver_name', '')}"), border=1)
    else:
        pdf.set_xy(LX, name_y)
        pdf.cell(BW, 6, _u(f"Name: {data.get('inspector_name', '')}"), border=1)

    # FOTOS AUF SEITE 2
    dmg = c_data.get("damage_records", [])
    photos = c_data.get("photos", {})
    
    valid_p = {}
    for lbl, purl in photos.items():
        if purl and not lbl.startswith("sig") and lbl != "signature":
            valid_p[lbl] = purl

    if dmg or valid_p:
        pdf.add_page()
        LX = 10.0
        
        if dmg:
            pdf.set_font("helvetica", "B", 12)
            pdf.cell(0, 10, "Erfasste Schäden", ln=True)
            pdf.set_font("helvetica", "B", 9)
            pdf.cell(50, 6, "Position", border=1, fill=True)
            pdf.cell(40, 6, "Art", border=1, fill=True)
            pdf.cell(40, 6, "Intensität", border=1, fill=True, ln=True)
            pdf.set_font("helvetica", "", 9)
            for d in dmg:
                pdf.cell(50, 6, _u(d["pos"]), border=1)
                pdf.cell(40, 6, _u(d["type"]), border=1)
                pdf.cell(40, 6, _u(d["int"]), border=1, ln=True)
            pdf.ln(8)

        if valid_p:
            pdf.set_font("helvetica", "B", 12)
            pdf.cell(0, 10, "5. Fotodokumentation", ln=True)
            
            s_col = 0
            s_y = pdf.get_y()
            S_COL_W = 87.0
            S_MAX_H = 58.0
            
            for lbl, purl in valid_p.items():
                if pdf.get_y() > 220:
                    pdf.add_page()
                    s_y = 20
                    s_col = 0
                try:
                    p_data = requests.get(purl, timeout=10).content
                    p_img = Image.open(io.BytesIO(p_data))
                    iw, ih = p_img.size
                    ratio = iw / ih
                    
                    dh = min(S_MAX_H, S_COL_W / ratio)
                    dw = dh * ratio
                    
                    if dw > S_COL_W:
                        dw = S_COL_W
                        dh = dw / ratio
                        
                    import tempfile
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        with open(tmp.name, "wb") as f:
                            f.write(p_data)
                        pdf.image(tmp.name, x=10.0 + s_col*(S_COL_W + 10) + (S_COL_W - dw) / 2, y=s_y, w=dw)
                except Exception:
                    pass
                s_col += 1
                if s_col > 1:
                    s_col = 0
                    s_y += max(dh, S_MAX_H) + 10

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# TAB 1: PROTOKOLL ERSTELLEN / BEARBEITEN
# ---------------------------------------------------------------------------

with tab1:
    is_edit = st.session_state.get("edit_id") is not None
    if is_edit:
        st.warning(f"Bearbeitungsmodus aktiv: ID {st.session_state.edit_id}")
        if st.button("Bearbeiten abbrechen"):
            st.session_state.edit_id = None
            st.session_state.edit_data = None
            st.rerun()

    render_header_with_logo("Fahrzeugannahme")

    st.header("1. Basisdaten")
    projects = get_projects()
    proj_sel = st.selectbox("Projekt auswählen", ["-- Neues Projekt --"] + projects)
    p_name = st.text_input("Neuer Projektname") if proj_sel == "-- Neues Projekt --" else proj_sel

    col1, col2 = st.columns(2)
    with col1:
        kennzeichen = st.text_input("Kennzeichen", st.session_state.edit_data["vehicles"]["license_plate"] if is_edit else "").upper()
        marke = st.text_input("Marke", st.session_state.edit_data.get("condition_data", {}).get("brand", "") if is_edit else "")
        modell = st.text_input("Modell", st.session_state.edit_data["vehicles"]["brand_model"] if is_edit else "")
        vin = st.text_input("VIN", st.session_state.edit_data["vehicles"]["vin"] if is_edit else "")
    with col2:
        standort = st.text_input("Standort", st.session_state.edit_data.get("location", "") if is_edit else "")
        datum = st.text_input("Datum", datetime.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M"))

    st.header("2. Sichtprüfung & Fotos")
    cond_prefill = st.session_state.edit_data["condition_data"].get("conditions", []) if is_edit else []
    erschwert = st.multiselect("Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"], default=cond_prefill)

    fv, fh, fl, fr, fs = render_photo_upload_section("t1")
    t1_damage_records, t1_d_files = render_damage_section(
        "t1", "t1_damage_count", 
        st.session_state.edit_data["condition_data"].get("damage_records", []) if is_edit else []
    )

    st.header("3. Checkliste")
    old_cl = st.session_state.edit_data["condition_data"].get("checkliste", {}) if is_edit else {}
    checkliste = render_checklist("t1", old_cl)

    st.header("4. Füllstände")
    f_lvl = int(st.session_state.edit_data.get("fuel_level") or 100) if is_edit else 100
    fuel = st.slider("Kraftstoff %", 0, 100, f_lvl)
    
    b_lvl = int(st.session_state.edit_data.get("condition_data", {}).get("battery", 100)) if is_edit else 100
    battery = st.slider("Batterie %", 0, 100, b_lvl)
    
    km = st.number_input("Kilometerstand", min_value=0, value=int(st.session_state.edit_data.get("odometer", 0)) if is_edit else 0, step=1)

    st.header("5. Abschluss")
    bemerkung = st.text_area("Bemerkungen", st.session_state.edit_data.get("remarks", "") if is_edit else "")
    ersteller = st.text_input("Ersteller", st.session_state.edit_data.get("inspector_name", "") if is_edit else "")

    st.write("Unterschrift Ersteller")
    canvas_result = st_canvas(fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3, stroke_color="#000000", background_color="#eeeeee", height=150, width=350, key="canvas_t1")
    
    confirm = st.checkbox("Ich bestätige die Richtigkeit der Angaben", value=False)

    if st.button("SPEICHERN", type="primary", use_container_width=True):
        if validate_inputs(kennzeichen, p_name, confirm, km):
            with st.spinner("Speichere Daten..."):
                pid = ensure_project(p_name)
                vid = upsert_vehicle(pid, kennzeichen, modell, vin)
                base_path = f"{sanitize_filename(p_name)}/{sanitize_filename(kennzeichen)}/annahme"

                photo_map = {"vorne": fv, "hinten": fh, "links": fl, "rechts": fr, "schein": fs}
                for i, (k, df) in enumerate(t1_d_files.items()):
                    photo_map[k] = df
                
                final_urls = st.session_state.edit_data["condition_data"].get("photos", {}) if is_edit else {}
                new_urls = upload_required_photos_parallel(photo_map, base_path)
                final_urls.update(new_urls)

                if canvas_result.image_data is not None and np.any(canvas_result.image_data[:, :, 3] > 0):
                    sig_im = Image.fromarray(canvas_result.image_data.astype("uint8"), "RGBA")
                    sig_url = upload_photo(sig_im, base_path, "sig_insp", is_pil=True)
                    if sig_url: final_urls["signature"] = sig_url

                payload = build_payload(vid, ersteller, standort, km, fuel, bemerkung, battery, final_urls, erschwert, t1_damage_records, checkliste)
                payload["protocol_type"] = "intake"
                payload["status"] = "final"
                payload["condition_data"]["brand"] = marke

                if save_protocol(payload, st.session_state.edit_id if is_edit else None):
                    st.session_state.edit_id = None
                    st.session_state.edit_data = None
                    st.session_state.t1_damage_count = 0
                    st.success("Annahme erfolgreich gespeichert!")
                    st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: ARCHIV & VERWALTUNG
# ---------------------------------------------------------------------------

with tab2:
    st.title("Archiv & Verwaltung")
    filter_val = st.radio("Status Filter", ["Alle", "Entwürfe", "Abgeschlossen"], horizontal=True)
    search_q = st.text_input("Suche (Kennzeichen)...", "")

    status_tuple = ("draft", "final")
    if filter_val == "Entwürfe": status_tuple = ("draft",)
    if filter_val == "Abgeschlossen": status_tuple = ("final",)

    results = get_protocols(status_tuple, search_q)
    
    if not results:
        st.info("Keine Protokolle gefunden.")
    else:
        for r in results:
            v = r["vehicles"]
            is_transfer_entry = r.get("protocol_type") == "transfer"
            p_type_lbl = "TRANSFER" if is_transfer_entry else "ANNAHME"
            date_str = r["created_at"][:16].replace("T", " ")
            status_lbl = "ENTWURF" if r.get("status") == "draft" else "FINAL"

            with st.expander(f"{date_str} | {v['license_plate']} | {v['brand_model']} | {p_type_lbl} [{status_lbl}]"):
                if status_lbl == "ENTWURF":
                    st.warning("Dieses Protokoll ist ein Entwurf und wurde noch nicht finalisiert.")
                c_arc1, c_arc2 = st.columns(2)
                with c_arc1:
                    st.write(f"**Ersteller:** {r['inspector_name']} | **VIN:** {v['vin']}")
                    if is_transfer_entry:
                        st.write(f"**Route:** {r.get('start_location') or '-'} -> {r.get('end_location') or '-'}")
                    else:
                        st.write(f"**Standort:** {r['location']}")
                with c_arc2:
                    st.write(f"**KM:** {r['odometer']} | **Kraftstoff:** {r['fuel_level']}%")
                
                c_btn1, c_btn2, c_btn3 = st.columns(3)
                with c_btn1:
                    if st.button("Bearbeiten", key=f"edit_{r['id']}"):
                        if is_transfer_entry:
                            st.session_state.transfer_edit_id = r["id"]
                            st.session_state.transfer_prefill = r
                            st.session_state.nav_redirect = "🚙 Fahrzeug-Überführung"
                        else:
                            st.session_state.edit_id = r["id"]
                            st.session_state.edit_data = r
                            st.session_state.nav_redirect = "📝 Protokoll erstellen / Bearbeiten"
                        st.rerun()
                with c_btn2:
                    if st.button("PDF generieren", key=f"pdf_{r['id']}"):
                        try:
                            pdf_bytes = create_pdf(r, is_transfer=is_transfer_entry, status=r.get("status", "final"))
                            fn = f"{p_type_lbl}_{v['license_plate']}_{date_str[:10]}.pdf"
                            st.download_button("Download PDF", data=pdf_bytes, file_name=fn, mime="application/pdf", key=f"dl_{r['id']}")
                        except Exception as e:
                            st.error(f"PDF-Fehler: {e}")
                with c_btn3:
                    if st.button("Löschen", key=f"del_{r['id']}", type="secondary"):
                        supabase.table("protocols").delete().eq("id", r["id"]).execute()
                        get_protocols.clear()
                        st.rerun()

# ---------------------------------------------------------------------------
# TAB 3: FAHRZEUG-ÜBERFÜHRUNG
# ---------------------------------------------------------------------------

with tab3:
    is_t3_edit = st.session_state.transfer_edit_id is not None
    prefill = st.session_state.transfer_prefill or {}

    if is_t3_edit:
        st.warning(f"Bearbeitungsmodus Transfer: ID {st.session_state.transfer_edit_id}")
        if st.button("Transfer-Bearbeitung abbrechen"):
            st.session_state.transfer_edit_id = None
            st.session_state.transfer_prefill = None
            st.rerun()

    render_header_with_logo("Fahrzeug-Überführung")

    st.header("1. Basisdaten & Route")
    t3_projects = get_projects()
    t3_proj_sel = st.selectbox("Projekt", ["-- Neues Projekt --"] + t3_projects, key="t3_proj_sel")
    t3_p_name = st.text_input("Neuer Projektname", key="t3_p_name") if t3_proj_sel == "-- Neues Projekt --" else t3_proj_sel

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        t3_kz = st.text_input("Kennzeichen", value=prefill.get("vehicles", {}).get("license_plate", "") if is_t3_edit else "", key="t3_kz").upper()
        t3_marke = st.text_input("Marke", value=prefill.get("condition_data", {}).get("brand", "") if is_t3_edit else "", key="t3_brand")
        t3_modell = st.text_input("Modell", value=prefill.get("vehicles", {}).get("brand_model", "") if is_t3_edit else "", key="t3_mod")
        vin_t3 = st.text_input("VIN", value=prefill.get("vehicles", {}).get("vin", "") if is_t3_edit else "", key="t3_vin")
    with col_t2:
        von_t3 = st.text_input("Start-Standort", value=prefill.get("start_location", "") if is_t3_edit else "", key="t3_von")
        nach_t3 = st.text_input("Ziel-Standort", value=prefill.get("end_location", "") if is_t3_edit else "", key="t3_nach")
        datum_t3 = st.text_input("Datum/Zeit", value=datetime.datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M"), key="t3_datum")

    st.header("2. Zustand bei Ankunft & Fotos")
    
    t3_cond_prefill = prefill.get("condition_data", {}).get("conditions", []) if is_t3_edit else []
    erschwert_t3 = st.multiselect("Bedingungen", ["Verschmutzung", "Regen", "Dunkelheit", "Schlechtes Licht"], default=t3_cond_prefill, key="t3_conditions")

    c_t3_1, c_t3_2 = st.columns(2)
    with c_t3_1:
        t3_km = st.number_input("Kilometerstand (Ziel)", min_value=0, value=int(prefill.get("odometer", 0)) if is_t3_edit else 0, key="t3_km")
    with c_t3_2:
        t3_fuel = st.slider("Kraftstoff %", 0, 100, int(prefill.get("fuel_level", 100)) if is_t3_edit else 100, key="t3_fuel")
        t3_battery = st.slider("Batterie %", 0, 100, int(prefill.get("condition_data", {}).get("battery", 100)) if is_t3_edit else 100, key="t3_bat")

    ft_v, ft_h, ft_l, ft_r, ft_s = render_photo_upload_section("t3")
    t3_damage_records, t3_d_files = render_damage_section(
        "t3", "t3_damage_count",
        prefill.get("condition_data", {}).get("damage_records", []) if is_t3_edit else []
    )

    st.header("3. Checkliste")
    t3_old_cl = prefill.get("condition_data", {}).get("checkliste", {}) if is_t3_edit else {}
    t3_checkliste = render_checklist("t3", t3_old_cl)

    st.header("4. Übergabe & Unterschriften")
    t3_bem = st.text_area("Besondere Vorkommnisse / Bemerkungen", value=prefill.get("remarks", "") if is_t3_edit else "", key="t3_bem")
    
    c_s1, c_s2 = st.columns(2)
    with c_s1:
        fahrer_t3 = st.text_input("Ersteller (Fahrer)", value=prefill.get("inspector_name", "") if is_t3_edit else "", key="t3_fahrer")
        st.write("Unterschrift Fahrer:")
        canvas_f = st_canvas(fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3, stroke_color="#000000", background_color="#eeeeee", height=150, width=350, key="canvas_f_t3")
    with c_s2:
        receiver_name_t3 = st.text_input("Name Empfänger", value=prefill.get("receiver_name", "") if is_t3_edit else "", key="t3_empf")
        st.write("Unterschrift Empfänger:")
        canvas_r = st_canvas(fill_color="rgba(255, 165, 0, 0.3)", stroke_width=3, stroke_color="#000000", background_color="#eeeeee", height=150, width=350, key="canvas_r_t3")

    btn_col1, btn_col2 = st.columns(2)
    
    def _save_transfer(status_val: str):
        if not (t3_kz and t3_p_name and fahrer_t3):
            st.error("Projekt, Kennzeichen und Fahrer sind Pflichtfelder!")
            return
        with st.spinner("Speichere Transfer..."):
            try:
                p_id_t3 = ensure_project(t3_p_name)
                v_id_t3 = upsert_vehicle(p_id_t3, t3_kz, t3_modell, vin_t3)
                base_path_t3 = f"{sanitize_filename(t3_p_name)}/{sanitize_filename(t3_kz)}/transfer"

                photo_map_t3 = {"vorne": ft_v, "hinten": ft_h, "links": ft_l, "rechts": ft_r, "schein": ft_s}
                for i, (k, df) in enumerate(t3_d_files.items()):
                    photo_map_t3[k] = df
                
                final_urls_t3 = prefill.get("condition_data", {}).get("photos", {}) if is_t3_edit else {}
                new_urls_t3 = upload_required_photos_parallel(photo_map_t3, base_path_t3)
                final_urls_t3.update(new_urls_t3)

                if canvas_f.image_data is not None and np.any(canvas_f.image_data[:, :, 3] > 0):
                    sig_im_f = Image.fromarray(canvas_f.image_data.astype("uint8"), "RGBA")
                    s_url_f = upload_photo(sig_im_f, base_path_t3, "sig_driver", is_pil=True)
                    if s_url_f: final_urls_t3["sig_inspector"] = s_url_f
                
                if canvas_r.image_data is not None and np.any(canvas_r.image_data[:, :, 3] > 0):
                    sig_im_r = Image.fromarray(canvas_r.image_data.astype("uint8"), "RGBA")
                    s_url_r = upload_photo(sig_im_r, base_path_t3, "sig_recv", is_pil=True)
                    if s_url_r: final_urls_t3["sig_receiver"] = s_url_r

                recv_time = datetime.datetime.now(ZoneInfo("Europe/Berlin")).isoformat() if status_val == "final" else None

                payload_t3 = build_payload(
                    v_id_t3, fahrer_t3, von_t3, t3_km, t3_fuel, t3_bem, 
                    t3_battery, final_urls_t3, erschwert_t3, t3_damage_records, t3_checkliste, recv_time
                )
                payload_t3["protocol_type"] = "transfer"
                payload_t3["status"] = status_val
                payload_t3["start_location"] = von_t3
                payload_t3["end_location"] = nach_t3
                payload_t3["receiver_name"] = receiver_name_t3
                payload_t3["condition_data"]["brand"] = t3_marke

                if save_protocol(payload_t3, st.session_state.transfer_edit_id if is_t3_edit else None):
                    st.session_state.transfer_prefill = None
                    st.session_state.transfer_edit_id = None
                    st.session_state.t3_damage_count = 0
                    msg = "Transfer erfolgreich finalisiert!" if status_val == "final" else "Transfer als Entwurf gespeichert."
                    st.success(msg)
                    st.rerun()
            except Exception as e:
                st.error(f"Unerwarteter Fehler: {e}")

    with btn_col1:
        if st.button("Als Entwurf speichern", use_container_width=True):
            _save_transfer("draft")
    with btn_col2:
        if st.button("Transfer abschließen", type="primary", use_container_width=True):
            _save_transfer("final")