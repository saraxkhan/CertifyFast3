import os
import uuid
import zipfile
from flask import Flask, render_template, request, send_file, jsonify
from utils.data_loader import load_data
from utils.placeholder_extractor import extract_placeholders
from utils.certificate_generator import generate_certificate
from utils.database import init_db, store_certificate, get_certificate
from utils.crypto_utils import generate_certificate_id, sign_certificate, compute_certificate_hash, verify_signature

app = Flask(__name__)




# Secret key for signing certificates (in production, use environment variable)
SECRET_KEY = os.environ.get('CERT_SECRET_KEY', 'change-this-in-production-use-env-var')

# Base URL for verification - CHANGE THIS TO YOUR DEPLOYED URL!
# For testing locally: use ngrok or similar tunneling service
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5001')

UPLOADS = "uploads"
OUTPUT  = "output"
SIGNATURES = "signatures"  # For storing signature images
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(OUTPUT,  exist_ok=True)
os.makedirs(SIGNATURES, exist_ok=True)

# Initialize database
init_db()


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


@app.route("/verify/<cert_id>")
def verify_page(cert_id):
    """Display verification page for a certificate."""
    cert = get_certificate(cert_id)
    
    if not cert:
        return render_template("verify.html", 
                             found=False, 
                             cert_id=cert_id)
    
    # Verify signature
    cert_data = {
        'cert_id': cert['cert_id'],
        'name': cert['name'],
        'course': cert['course'],
        'date': cert['date']
    }
    
    is_valid = verify_signature(cert_data, cert['signature'], SECRET_KEY)
    
    return render_template("verify.html",
                         found=True,
                         valid=is_valid,
                         cert=cert)


@app.route("/api/verify/<cert_id>")
def verify_api(cert_id):
    """API endpoint for certificate verification."""
    cert = get_certificate(cert_id)
    
    if not cert:
        return jsonify({
            "found": False,
            "cert_id": cert_id,
            "message": "Certificate not found"
        }), 404
    
    # Verify signature
    cert_data = {
        'cert_id': cert['cert_id'],
        'name': cert['name'],
        'course': cert['course'],
        'date': cert['date']
    }
    
    is_valid = verify_signature(cert_data, cert['signature'], SECRET_KEY)
    
    return jsonify({
        "found": True,
        "valid": is_valid,
        "certificate": {
            "id": cert['cert_id'],
            "recipient": cert['name'],
            "course": cert['course'],
            "issue_date": cert['date'],
            "issued_at": cert['created_at']
        }
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """
    Phase 1: upload files, extract placeholders, return analysis JSON.
    Saves files under a session ID so phase 2 can find them.
    """
    try:
        template_file = request.files.get("template")
        data_file     = request.files.get("data")
        signature_file = request.files.get("signature")  # Optional

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
        
        # Save signature if provided
        sig_path = None
        if signature_file and signature_file.filename:
            sig_ext = os.path.splitext(signature_file.filename)[1] or ".png"
            sig_path = os.path.join(SIGNATURES, f"{sid}_signature{sig_ext}")
            signature_file.save(sig_path)
            print(f"Signature saved: {sig_path}")

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
            "has_signature": sig_path is not None
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
    zip_path = None
    try:
        print("=== GENERATE ROUTE CALLED ===")
        sid = request.form.get("session_id", "")
        qr_position = request.form.get("qr_position", "bottom-right")
        sig_position = request.form.get("sig_position", "bottom-center")
        print(f"Session ID: {sid}")
        print(f"QR Position: {qr_position}")
        print(f"Signature Position: {sig_position}")
        
        if not sid:
            return jsonify({"error": "Session expired. Please re-upload your files."}), 400

        # Find saved files
        tmpl_path = data_path = sig_path = None
        for f in os.listdir(UPLOADS):
            if f.startswith(f"{sid}_template"):
                tmpl_path = os.path.join(UPLOADS, f)
            elif f.startswith(f"{sid}_data"):
                data_path = os.path.join(UPLOADS, f)
        
        # Check for signature
        for f in os.listdir(SIGNATURES):
            if f.startswith(f"{sid}_signature"):
                sig_path = os.path.join(SIGNATURES, f)
                break

        print(f"Template: {tmpl_path}")
        print(f"Data: {data_path}")
        print(f"Signature: {sig_path if sig_path else 'None'}")

        if not tmpl_path or not data_path:
            return jsonify({"error": "Session expired. Please re-upload your files."}), 400

        # Extract placeholders and load data
        print("Extracting placeholders...")
        try:
            placeholders = extract_placeholders(tmpl_path)
            print(f"Found {len(placeholders)} placeholders: {list(placeholders.keys())}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Failed to extract placeholders from PDF: {str(e)}"}), 500
        
        print("Loading data...")
        try:
            df = load_data(data_path)
            print(f"Loaded {len(df)} rows with columns: {list(df.columns)}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Failed to load data file: {str(e)}"}), 500

        if not placeholders:
            return jsonify({"error": "No placeholders found in template"}), 400

        zip_path = os.path.abspath(os.path.join(OUTPUT, f"certificates_{sid}.zip"))
        print(f"Creating ZIP at: {zip_path}")
        
        errors = []
        success_count = 0

        # Create the ZIP file even if all certificates fail
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            print(f"Processing {len(df)} rows...")
            for idx, (_, row) in enumerate(df.iterrows()):
                out_pdf = None  # Define before try block so it exists in except
                try:
                    raw_data = {col: row[col] for col in df.columns}

                    # Use the first column's value as the filename
                    fname_val = str(row[df.columns[0]]).strip()
                    if not fname_val or fname_val.lower() == "nan":
                        fname_val = f"certificate_{idx + 1}"

                    # Sanitise filename
                    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in fname_val).strip()
                    if not safe:
                        safe = f"certificate_{idx + 1}"
                    
                    out_pdf = os.path.join(OUTPUT, f"{safe}_{idx}.pdf")

                    print(f"  Row {idx + 1}: Generating {safe}.pdf...")
                    
                    # Generate unique certificate ID
                    cert_id = generate_certificate_id()
                    
                    # Extract certificate data for signing
                    # Find 'name', 'course', 'date' columns (case-insensitive)
                    cert_data = {'cert_id': cert_id}
                    for col in df.columns:
                        col_lower = col.lower().strip()
                        if col_lower in ['name', 'student', 'recipient', 'full_name']:
                            cert_data['name'] = str(row[col]).strip()
                        elif col_lower in ['course', 'subject', 'program', 'course_name']:
                            cert_data['course'] = str(row[col]).strip()
                        elif col_lower in ['date', 'issue_date', 'completion_date', 'cert_date']:
                            cert_data['date'] = str(row[col]).strip()
                    
                    # Fallback to first 3 columns if standard ones not found
                    if 'name' not in cert_data and len(df.columns) > 0:
                        cert_data['name'] = str(row[df.columns[0]]).strip()
                    if 'course' not in cert_data and len(df.columns) > 1:
                        cert_data['course'] = str(row[df.columns[1]]).strip()
                    if 'date' not in cert_data and len(df.columns) > 2:
                        cert_data['date'] = str(row[df.columns[2]]).strip()
                    
                    # If date is still not set, use current date
                    if 'date' not in cert_data:
                        from datetime import datetime
                        cert_data['date'] = datetime.now().strftime('%Y-%m-%d')
                    
                    # Ensure all required fields have defaults
                    if 'name' not in cert_data:
                        cert_data['name'] = 'Unknown'
                    if 'course' not in cert_data:
                        cert_data['course'] = 'Unknown'
                    
                    # Sign the certificate
                    signature = sign_certificate(cert_data, SECRET_KEY)
                    data_hash = compute_certificate_hash(cert_data)
                    
                    # Build verification URL
                    verification_url = f"{BASE_URL}/verify/{cert_id}"
                    
                    # Generate the certificate with QR code and optional signature
                    generate_certificate(
                        tmpl_path, 
                        out_pdf, 
                        raw_data, 
                        placeholders,
                        cert_id=cert_id,
                        verification_url=verification_url,
                        qr_position=qr_position,
                        signature_path=sig_path,
                        sig_position=sig_position
                    )
                    
                    # Store in database
                    store_certificate(
                        cert_id,
                        cert_data.get('name', 'Unknown'),
                        cert_data.get('course', 'Unknown'),
                        cert_data.get('date', 'Unknown'),
                        signature,
                        data_hash,
                        additional_data=raw_data
                    )
                    
                    # Verify the PDF was created
                    if os.path.exists(out_pdf) and os.path.getsize(out_pdf) > 0:
                        zf.write(out_pdf, arcname=f"{safe}.pdf")
                        success_count += 1
                        print(f"  Row {idx + 1}: SUCCESS")
                        # Clean up
                        try:
                            os.remove(out_pdf)
                        except:
                            pass
                    else:
                        error_msg = f"PDF not created"
                        errors.append(f"Row {idx + 1} ({fname_val}): {error_msg}")
                        print(f"  Row {idx + 1}: FAILED - {error_msg}")
                        
                except Exception as e:
                    error_msg = str(e)[:200]
                    errors.append(f"Row {idx + 1}: {error_msg}")
                    print(f"  Row {idx + 1}: ERROR - {error_msg}")
                    import traceback
                    traceback.print_exc()
                    # Clean up partial PDF if it exists
                    if out_pdf and os.path.exists(out_pdf):
                        try:
                            os.remove(out_pdf)
                        except:
                            pass

        print(f"Generation complete: {success_count} succeeded, {len(errors)} failed")

        # Clean up session files
        try:
            os.remove(tmpl_path)
            os.remove(data_path)
            if sig_path and os.path.exists(sig_path):
                os.remove(sig_path)
        except OSError:
            pass

        # Check if we created anything
        if success_count == 0:
            error_msg = "Failed to generate any certificates."
            if errors:
                # Show first 3 errors
                error_msg += " Errors: " + " | ".join(errors[:3])
            print(f"ERROR: {error_msg}")
            return jsonify({"error": error_msg}), 500

        # If some succeeded but some failed, still return the ZIP with a warning
        if errors and success_count > 0:
            print(f"WARNING: Some certificates failed: {errors[:5]}")

        print(f"Sending ZIP file: {zip_path}")
        return send_file(zip_path, as_attachment=True, download_name="certificates.zip")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        error_detail = f"{str(e)} | Traceback: {tb[:1000]}"
        
        print(f"FATAL ERROR: {error_detail}")
        traceback.print_exc()
        
        # Clean up ZIP if it was created
        if zip_path and os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except:
                pass
                
        return jsonify({"error": error_detail}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
