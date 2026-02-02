import os
import uuid
import zipfile
from flask import Flask, render_template, request, send_file, jsonify
from utils.data_loader import load_data
from utils.placeholder_extractor import extract_placeholders
from utils.certificate_generator import generate_certificate

app = Flask(__name__)

UPLOADS = "uploads"
OUTPUT  = "output"
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(OUTPUT,  exist_ok=True)


# ─────────────────────────────────────────────────────────────
# Helper: figure out which placeholder each data column maps to
# ─────────────────────────────────────────────────────────────
def _compute_mapping(df_columns, placeholder_keys):
    """
    For each placeholder key, check if any column name matches it
    (case-insensitive).  That is the only rule.

    Returns:
      matched:   [{ "placeholder": key, "column": original_col_name }, ...]
      unmatched: [ key, ... ]   — placeholders with no column match
    """
    # lowercase column name  →  original column name
    col_map = { col.strip().lower(): col for col in df_columns }

    matched   = []
    matched_keys = set()

    for key in placeholder_keys:
        if key in col_map:                          # key is already lowercase
            matched.append({ "placeholder": key, "column": col_map[key] })
            matched_keys.add(key)

    unmatched = [ k for k in placeholder_keys if k not in matched_keys ]
    return matched, unmatched


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    Phase 1: upload files, extract placeholders, return analysis JSON.
    Saves files under a session ID so phase 2 can find them.
    """
    try:
        template_file = request.files.get("template")
        data_file     = request.files.get("data")

        if not template_file or not data_file:
            return jsonify({"error": "Both a PDF template and a data file are required."}), 400

        # Save with session prefix
        sid = uuid.uuid4().hex[:10]
        tmpl_ext  = os.path.splitext(template_file.filename)[1] or ".pdf"
        data_ext  = os.path.splitext(data_file.filename)[1]     or ".xlsx"
        tmpl_path = os.path.join(UPLOADS, f"{sid}_template{tmpl_ext}")
        data_path = os.path.join(UPLOADS, f"{sid}_data{data_ext}")

        template_file.save(tmpl_path)
        data_file.save(data_path)

        # --- extract ---
        placeholders = extract_placeholders(tmpl_path)
        df           = load_data(data_path)

        if not placeholders:
            return jsonify({"error": "No {{placeholders}} found in the PDF template. "
                                     "Make sure placeholders look like {{Name}}, {{Course}}, etc."}), 400

        # --- compute mapping ---
        matched, unmatched = _compute_mapping(df.columns.tolist(), list(placeholders.keys()))

        # --- preview rows (first 5) ---
        preview = []
        for _, row in df.head(5).iterrows():
            preview.append({col: str(row[col]) for col in df.columns})

        return jsonify({
            "session_id":   sid,
            "placeholders": list(placeholders.keys()),
            "columns":      df.columns.tolist(),
            "matched":      matched,
            "unmatched":    unmatched,
            "total":        len(df),
            "preview":      preview,
        })

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/generate", methods=["POST"])
def generate():
    """
    Phase 2: generate all certificates and return a ZIP.
    """
    try:
        sid = request.form.get("session_id", "")
        if not sid:
            return jsonify({"error": "Session expired. Please re-upload your files."}), 400

        # Find saved files
        tmpl_path = data_path = None
        for f in os.listdir(UPLOADS):
            if f.startswith(f"{sid}_template"):
                tmpl_path = os.path.join(UPLOADS, f)
            elif f.startswith(f"{sid}_data"):
                data_path = os.path.join(UPLOADS, f)

        if not tmpl_path or not data_path:
            return jsonify({"error": "Session expired. Please re-upload your files."}), 400

        placeholders = extract_placeholders(tmpl_path)
        df           = load_data(data_path)

        zip_path = os.path.join(OUTPUT, f"certificates_{sid}.zip")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, (_, row) in enumerate(df.iterrows()):
                raw_data = {col: row[col] for col in df.columns}

                # Use the first column's value as the filename
                fname_val = str(row[df.columns[0]]).strip()
                if not fname_val or fname_val.lower() == "nan":
                    fname_val = f"certificate_{idx + 1}"

                # Sanitise filename
                safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in fname_val).strip()
                out_pdf = os.path.join(OUTPUT, f"{safe}.pdf")

                generate_certificate(tmpl_path, out_pdf, raw_data, placeholders)
                zf.write(out_pdf, arcname=f"{safe}.pdf")
                os.remove(out_pdf)   # clean up individual PDF

        # Clean up session files
        try:
            os.remove(tmpl_path)
            os.remove(data_path)
        except OSError:
            pass

        return send_file(zip_path, as_attachment=True, download_name="certificates.zip")

    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

