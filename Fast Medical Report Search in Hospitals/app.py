# app.py
"""
Fast Medical Report Search (Demo)
Single-file Streamlit + Whoosh prototype.

Features:
- Upload report files (plain .txt or .pdf).
- Extract text from PDFs (pdfplumber).
- Index reports with Whoosh (title, patient_id, date, content).
- Fast search with ranking, plus filters.
- View/download matched reports.

Run:
    pip install streamlit whoosh pdfplumber
    streamlit run app.py
"""

import streamlit as st
import tempfile
import os
import io
import datetime
import base64
import pdfplumber
from whoosh import index
from whoosh.fields import Schema, TEXT, ID, DATETIME, STORED
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh.analysis import StemmingAnalyzer
import streamlit as st

# --- Hide Streamlit Deploy Button ---
hide_deploy_btn = """
    <style>
    .stDeployButton {display: none;}
    </style>
"""
st.markdown(hide_deploy_btn, unsafe_allow_html=True)
from reportlab.pdfgen import canvas

def save_pdf(text, filename):
    c = canvas.Canvas(filename)  # Creates a proper PDF
    c.drawString(100, 750, text)
    c.save()

# Example
save_pdf("This is a valid medical report", "report.pdf")


# -------- Config & Helpers --------
INDEX_DIR = "whoosh_index"

def ensure_index():
    """Create or open the Whoosh index directory."""
    schema = Schema(
        doc_id=ID(stored=True, unique=True),
        title=TEXT(stored=True, analyzer=StemmingAnalyzer()),
        patient_id=ID(stored=True),
        date=DATETIME(stored=True),
        content=TEXT(stored=True, analyzer=StemmingAnalyzer())
    )
    if not os.path.exists(INDEX_DIR):
        os.mkdir(INDEX_DIR)
        ix = index.create_in(INDEX_DIR, schema)
    else:
        try:
            ix = index.open_dir(INDEX_DIR)
        except:
            # recreate if corrupted
            for f in os.listdir(INDEX_DIR):
                os.remove(os.path.join(INDEX_DIR, f))
            ix = index.create_in(INDEX_DIR, schema)
    return ix

def extract_text_from_pdf(file_bytes):
    """Extract text from a PDF bytes using pdfplumber."""
    text = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
    return "\n".join(text)

def save_raw_file(content_bytes, filename):
    """Save uploaded file to data folder for download/view later."""
    data_dir = "uploaded_reports"
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, filename)
    with open(path, "wb") as f:
        f.write(content_bytes)
    return path

def encode_download_link(file_path, label="Download"):
    """Return a safe download link for display in Streamlit."""
    with open(file_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode()
    fn = os.path.basename(file_path)
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{fn}">{label}</a>'
    return href

# -------- Streamlit UI --------
st.set_page_config(page_title="Fast Medical Report Search", layout="wide")
st.title("🔎 Fast Medical Report Search")

# Simple role-based login (demo only)
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if not st.session_state.logged_in:
    st.sidebar.header("Login")
    username = st.sidebar.text_input("Username")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        # Demo credentials: Doctor / Pass@123
        if username == "Doctor" and password == "Pass@123":
            st.session_state.logged_in = True
            st.sidebar.success("Logged in as doctor")
        else:
            st.sidebar.error("Invalid credentials (Doctor / Pass@123)")
    st.stop()

# Index initialization
ix = ensure_index()

# Layout: Left column for upload & indexing, right column for search
left, right = st.columns([1, 2])

with left:
    st.header("📤 Upload & Index Reports")
    uploaded = st.file_uploader("Upload report file (txt or pdf)", type=["txt", "pdf"], accept_multiple_files=True)
    with st.form("index_form"):
        t_title = st.text_input("Report Title (required)")
        t_patient = st.text_input("Patient ID (optional)")
        t_date = st.date_input("Report Date (defaults to today)", value=datetime.date.today())
        index_submit = st.form_submit_button("Index uploaded file(s)")
    if index_submit:
        if not uploaded:
            st.warning("Please upload at least one file.")
        elif not t_title:
            st.warning("Please enter a report title.")
        else:
            writer = ix.writer()
            for uf in uploaded:
                raw = uf.read()
                fname = uf.name
                # extract text
                if fname.lower().endswith(".pdf"):
                    try:
                        content = extract_text_from_pdf(raw)
                        if not content.strip():
                            st.warning(f"No text extracted from {fname}. It may be scanned; OCR is not enabled in this App.")
                    except Exception as e:
                        st.error(f"Error extracting PDF text from {fname}: {e}")
                        content = ""
                else:
                    try:
                        content = raw.decode(errors="ignore")
                    except:
                        content = ""
                # build doc_id unique
                ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
                doc_id = f"{fname}_{ts}"
                # save raw file for download/view
                saved_path = save_raw_file(raw, doc_id + "_" + fname)
                # add to index
                try:
                    writer.add_document(
                        doc_id=doc_id,
                        title=t_title or fname,
                        patient_id=(t_patient or ""),
                        date=datetime.datetime.combine(t_date, datetime.time.min),
                        content=content
                    )
                    st.success(f"Indexed {fname} as '{t_title}' (doc_id {doc_id})")
                except Exception as e:
                    st.error(f"Index error for {fname}: {e}")
            writer.commit()

    st.markdown("---")
    if st.button("Rebuild index (clear & recreate)"):
        # WARNING: deletes index
        if os.path.exists(INDEX_DIR):
            for f in os.listdir(INDEX_DIR):
                os.remove(os.path.join(INDEX_DIR, f))
            os.rmdir(INDEX_DIR)
        ix = ensure_index()
        st.success("Index rebuilt (empty).")

with right:
    st.header("🔍 Search Reports")
    q_col, filter_col = st.columns([3, 1])
    with q_col:
        query_text = st.text_input("Enter your search query (keywords, phrases)")
        k = st.slider("Number of results", 1, 20, 10)
    with filter_col:
        pid_filter = st.text_input("Filter by Patient ID")
        date_from = st.date_input("From date", value=None)
        date_to = st.date_input("To date", value=None)
        # allow empty date selection
        if date_from == datetime.date(1900,1,1):
            date_from = None
    if st.button("Search"):
        if not query_text.strip():
            st.warning("Please enter a query.")
        else:
            with ix.searcher() as searcher:
                parser = MultifieldParser(["title", "content", "patient_id"], schema=ix.schema, group=OrGroup)
                q = parser.parse(query_text)
                results = searcher.search(q, limit=k)
                # post-filter by patient and dates
                filtered = []
                for hit in results:
                    hit_date = hit.get("date")
                    if hit_date is not None:
                        # hit_date is datetime
                        pass
                    # filter patient
                    if pid_filter:
                        if hit.get("patient_id", "").lower() != pid_filter.lower():
                            continue
                    # filter date range
                    if date_from:
                        if hit.get("date") is None or hit.get("date").date() < date_from:
                            continue
                    if date_to:
                        if hit.get("date") is None or hit.get("date").date() > date_to:
                            continue
                    filtered.append(hit)
                st.markdown(f"**{len(filtered)} results** (showing up to {k})")
                for i, h in enumerate(filtered):
                    st.subheader(f"{i+1}. {h['title']}")
                    st.write(f"**Patient ID:** {h.get('patient_id','N/A')}  |  **Date:** {h.get('date')}")
                    content = h.get("content", "")
                    snippet = content[:1000] + ("..." if len(content) > 1000 else "")
                    with st.expander("Show snippet / highlights"):
                        st.write(snippet.replace("\n", "  \n"))
                    # find saved file if exists
                    candidates = []
                    data_dir = "uploaded_reports"
                    if os.path.exists(data_dir):
                        for fn in os.listdir(data_dir):
                            if fn.startswith(h["doc_id"] + "_"):
                                candidates.append(os.path.join(data_dir, fn))
                    if candidates:
                        for p in candidates:
                            st.markdown(encode_download_link(p, "Download original file"), unsafe_allow_html=True)
                    else:
                        st.info("Original uploaded file not found (maybe was removed).")

    st.markdown("---")
    st.header("🧾 Indexed Documents (preview)")
    # show a table of indexed docs (IDs, title, patient, date)
    try:
        with ix.searcher() as searcher:
            all_docs = searcher.documents()
            docs = []
            for d in all_docs:
                docs.append({
                    "doc_id": d.get("doc_id"),
                    "title": d.get("title"),
                    "patient_id": d.get("patient_id"),
                    "date": d.get("date")
                })
            if docs:
                st.table(docs)
            else:
                st.info("No documents indexed yet.")
    except Exception as e:
        st.error(f"Error listing index: {e}")

st.sidebar.markdown("---")
st.sidebar.write("Demo notes:")
st.sidebar.write("- Login: `Doctor` / `Pass@123`")
# st.sidebar.write("- To upload many reports, use the upload panel and enter a common title, or extend the UI to capture metadata per file.")
# st.sidebar.write("- PDF OCR (scanned images) not included. Use pytesseract + PIL for OCR on images.")
