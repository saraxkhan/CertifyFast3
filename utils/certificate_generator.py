import fitz
from utils.qr_generator import generate_qr_code, qr_to_bytes


def _detect_background_color(page, rect):
    """
    Sample the pixel color at the center of a rect to determine the
    background color for redaction fill.

    Returns an RGB tuple (0-1 floats).  Defaults to white if sampling fails.
    """
    try:
        # Render a small clip around the rect center at low res
        cx = (rect.x0 + rect.x1) / 2
        cy = (rect.y0 + rect.y1) / 2
        clip = fitz.Rect(cx - 1, cy - 1, cx + 1, cy + 1)
        pix = page.get_pixmap(clip=clip, dpi=(72, 72))
        # Get the color of the center pixel
        # pix.samples is bytes: R G B R G B ...
        samples = pix.samples
        if len(samples) >= 3:
            r, g, b = samples[0] / 255.0, samples[1] / 255.0, samples[2] / 255.0
            return (r, g, b)
    except Exception:
        pass
    return (1.0, 1.0, 1.0)   # default white


def _detect_alignment(page, placeholder_rect, font_size):
    """
    Detect whether placeholder text is LEFT-aligned or CENTER-aligned
    by comparing it to nearby static text on the same horizontal band.

    Logic:
      - Find all text spans within ±(font_size * 1.5) vertical pixels
        of the placeholder
      - If most of those spans start at roughly the same x0 as the
        placeholder, it's LEFT-aligned
      - If the placeholder's x-center is significantly different from
        its x0 + half-width, and other text is similarly centered,
        it's CENTER-aligned

    Returns: "left" or "center"
    """
    ph_x0 = placeholder_rect.x0
    ph_cx = (placeholder_rect.x0 + placeholder_rect.x1) / 2
    ph_y_center = (placeholder_rect.y0 + placeholder_rect.y1) / 2

    text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    nearby_x0s = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sy0 = span["bbox"][1]
                sy1 = span["bbox"][3]
                s_y_center = (sy0 + sy1) / 2

                # Skip the placeholder itself
                if "{{" in span["text"]:
                    continue

                # Is this span vertically near the placeholder?
                if abs(s_y_center - ph_y_center) < font_size * 2.5:
                    nearby_x0s.append(span["bbox"][0])

    if not nearby_x0s:
        return "left"   # no nearby text to compare → assume left

    # If most nearby text starts at the same x as the placeholder → left-aligned
    tolerance = 5.0   # points
    left_aligned_count = sum(1 for x in nearby_x0s if abs(x - ph_x0) < tolerance)

    if left_aligned_count > len(nearby_x0s) * 0.4:
        return "left"

    return "center"


def generate_certificate(template_path, output_path, row_data, placeholders, cert_id=None, verification_url=None, qr_position="bottom-right", signature_path=None, sig_position="bottom-center"):
    """
    Generate one certificate with QR code and signature for verification.

    row_data:          { "Vegetable": "Carrot", "Fruit": "Apple", ... }
    placeholders:      { "vegetable": { rect, font_size, font_name, color … }, … }
    cert_id:           Unique certificate ID (optional)
    verification_url:  URL for QR code (optional)
    qr_position:       Where to place QR code: "bottom-right", "bottom-left", "top-right", "top-left"
    signature_path:    Path to signature image file (optional)
    sig_position:      Where to place signature: "bottom-center", "bottom-left", "bottom-right"
    """
    doc = None
    try:
        doc = fitz.open(template_path)
        page = doc[0]
        page_width = page.rect.width
        page_height = page.rect.height

        # Build a simple lookup:  "vegetable" → "Carrot"
        # (lowercase the column name, keep the value as-is)
        col_lookup = { col.strip().lower(): val for col, val in row_data.items() }

        for key, meta in placeholders.items():
            # key is already lowercased by the extractor
            if key not in col_lookup:
                continue   # no matching column in the data → leave placeholder alone

            # Value straight from the cell, converted to string, nothing else
            value = str(col_lookup[key]).strip()
            if not value or value.lower() == "nan":
                continue   # empty / NaN cell → skip
            
            try:
                rect = meta["rect"]
                font_size = meta["font_size"]
                font_name = meta["font_name"]
                color = meta["color"]

                # ── Detect alignment of this placeholder ──
                alignment = _detect_alignment(page, rect, font_size)

                # ── Detect background color for clean redaction ──
                bg_color = _detect_background_color(page, rect)

                # ── Measure replacement text width at the correct font size ──
                try:
                    text_width = fitz.get_text_length(value, fontsize=font_size, fontname=font_name)
                except Exception as e:
                    # Font might not be available - try with a guaranteed base font
                    font_name = "Helvetica"
                    text_width = fitz.get_text_length(value, fontsize=font_size, fontname=font_name)

                # ── Auto-shrink: if text is wider than available space, shrink ──
                max_width = page_width * 0.85 - rect.x0
                current_size = font_size
                for _ in range(30):
                    if text_width <= max_width:
                        break
                    current_size *= 0.93
                    text_width = fitz.get_text_length(value, fontsize=current_size, fontname=font_name)

                # ── Calculate X position ──
                if alignment == "left":
                    x = rect.x0
                else:
                    x = rect.x0 + (rect.width - text_width) / 2.0
                    if x < 0 or x + text_width > page_width:
                        x = rect.x0

                # ── Calculate Y position (baseline) ──
                y = rect.y0 + current_size * 0.78

                # ── Redact the placeholder ──
                redact_rect = fitz.Rect(rect.x0 - 1, rect.y0 - 1, rect.x1 + 1, rect.y1 + 1)
                page.add_redact_annot(redact_rect, fill=bg_color)
                page.apply_redactions()

                # ── Insert replacement text ──
                page.insert_text(
                    (x, y),
                    value,
                    fontsize=current_size,
                    fontname=font_name,
                    color=color,
                )
            except Exception as e:
                # If a single placeholder fails, log it but continue with others
                raise Exception(f"Failed to replace {{{{{{key}}}}}}: {str(e)}")

        # ── Add QR code if verification URL provided ──
        if verification_url:
            try:
                qr_img = generate_qr_code(verification_url, size_pixels=120)
                qr_bytes = qr_to_bytes(qr_img)
                
                # Calculate QR position based on qr_position parameter
                qr_size = 120  # pixels
                margin = 20    # points from edge
                
                if qr_position == "bottom-right":
                    qr_rect = fitz.Rect(
                        page_width - qr_size - margin,
                        page_height - qr_size - margin,
                        page_width - margin,
                        page_height - margin
                    )
                elif qr_position == "bottom-left":
                    qr_rect = fitz.Rect(
                        margin,
                        page_height - qr_size - margin,
                        margin + qr_size,
                        page_height - margin
                    )
                elif qr_position == "top-right":
                    qr_rect = fitz.Rect(
                        page_width - qr_size - margin,
                        margin,
                        page_width - margin,
                        margin + qr_size
                    )
                else:  # top-left
                    qr_rect = fitz.Rect(
                        margin,
                        margin,
                        margin + qr_size,
                        margin + qr_size
                    )
                
                # Insert QR code image
                page.insert_image(qr_rect, stream=qr_bytes)
                
                # Add cert ID text below QR if cert_id provided
                if cert_id:
                    cert_text = f"ID: {cert_id}"
                    text_y = qr_rect.y1 + 10
                    page.insert_text(
                        (qr_rect.x0, text_y),
                        cert_text,
                        fontsize=8,
                        fontname="Helvetica",
                        color=(0.3, 0.3, 0.3)
                    )
            except Exception as e:
                print(f"Warning: Failed to add QR code: {str(e)}")
                # Continue anyway - QR failure shouldn't break the whole certificate

        # ── Add signature image if provided ──
        if signature_path:
            try:
                import os
                if os.path.exists(signature_path):
                    # Calculate signature position
                    sig_width = 150   # Width in points
                    sig_height = 60   # Height in points
                    margin = 30
                    
                    if sig_position == "bottom-center":
                        sig_rect = fitz.Rect(
                            (page_width - sig_width) / 2,
                            page_height - sig_height - margin,
                            (page_width + sig_width) / 2,
                            page_height - margin
                        )
                    elif sig_position == "bottom-left":
                        sig_rect = fitz.Rect(
                            margin,
                            page_height - sig_height - margin,
                            margin + sig_width,
                            page_height - margin
                        )
                    else:  # bottom-right
                        sig_rect = fitz.Rect(
                            page_width - sig_width - margin,
                            page_height - sig_height - margin,
                            page_width - margin,
                            page_height - margin
                        )
                    
                    # Insert signature image
                    page.insert_image(sig_rect, filename=signature_path, keep_proportion=True)
                    print(f"Signature added at {sig_position}")
            except Exception as e:
                print(f"Warning: Failed to add signature image: {str(e)}")
                # Continue anyway - signature failure shouldn't break the whole certificate

        doc.save(output_path)
        
    except Exception as e:
        raise Exception(f"Certificate generation failed: {str(e)}")
    finally:
        if doc:
            doc.close()
