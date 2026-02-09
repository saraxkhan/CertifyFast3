import fitz
import re

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def extract_placeholders(pdf_path):
    """
    Scan every page of the PDF for {{placeholder}} text and return
    a dict with the EXACT font, size, color, and position of each one.

    Uses get_text("dict") which gives us span-level metadata including
    the REAL font size (not bbox height) and the actual embedded font name.

    Also extracts and registers any embedded fonts so we can reuse them
    when inserting replacement text.

    Returns:
        {
            "name": {
                "rect":           fitz.Rect,      # bounding box of the placeholder
                "font_size":      float,           # actual font size in points
                "font_name":      str,             # registered font name to use for insert
                "color":          (r, g, b),       # 0-1 float RGB
                "is_bold":        bool,
                "embedded_font":  str,             # original embedded font name
            },
            ...
        }
    """
    doc = fitz.open(pdf_path)
    placeholders = {}

    # --- Step 1: Extract and register embedded fonts ---
    registered_fonts = _register_embedded_fonts(doc)

    for page in doc:
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:   # text block
                continue

            for line in block.get("lines", []):
                # ── Concatenate all spans in this line to find placeholders
                #     that might be split across spans ──
                full_line_text = ""
                span_map = []   # (start_idx, end_idx, span_dict)
                for span in line.get("spans", []):
                    start = len(full_line_text)
                    full_line_text += span["text"]
                    end = len(full_line_text)
                    span_map.append((start, end, span))

                # ── Find all {{placeholders}} in this line ──
                for match in PLACEHOLDER_RE.finditer(full_line_text):
                    key = match.group(1).lower()
                    if key in placeholders:
                        continue   # already found (e.g. on a previous page)

                    match_start = match.start()
                    match_end = match.end()

                    # ── Find the span(s) that contain this placeholder ──
                    # Use the span that contains the opening {{ as the style source
                    style_span = None
                    bbox_spans = []
                    for s_start, s_end, span in span_map:
                        # Does this span overlap with our match?
                        if s_end > match_start and s_start < match_end:
                            bbox_spans.append(span)
                            if style_span is None:
                                style_span = span

                    if style_span is None:
                        continue

                    # ── Real font size from the span (NOT bbox height) ──
                    font_size = style_span["size"]

                    # ── Color: span["color"] is a packed int 0xRRGGBB ──
                    raw_color = style_span["color"]
                    color = (
                        ((raw_color >> 16) & 0xFF) / 255.0,
                        ((raw_color >> 8)  & 0xFF) / 255.0,
                        ( raw_color        & 0xFF) / 255.0,
                    )

                    # ── Font name from span ──
                    embedded_name = style_span.get("font", "")
                    is_bold = "bold" in embedded_name.lower()

                    # ── Determine which registered font to use ──
                    # Try to find a registered font that matches this embedded name
                    use_font = _pick_font(embedded_name, registered_fonts, is_bold)

                    # ── Bounding rect: union of all spans that hold this placeholder ──
                    x0 = min(s["bbox"][0] for s in bbox_spans)
                    y0 = min(s["bbox"][1] for s in bbox_spans)
                    x1 = max(s["bbox"][2] for s in bbox_spans)
                    y1 = max(s["bbox"][3] for s in bbox_spans)
                    rect = fitz.Rect(x0, y0, x1, y1)

                    placeholders[key] = {
                        "rect":           rect,
                        "font_size":      font_size,
                        "font_name":      use_font,
                        "color":          color,
                        "is_bold":        is_bold,
                        "embedded_font":  embedded_name,
                    }

    doc.close()
    return placeholders


# ─────────────────────────────────────────────────────────────
# Font extraction helpers
# ─────────────────────────────────────────────────────────────

def _register_embedded_fonts(doc):
    """
    Extract embedded font files from the PDF and register them with fitz
    so we can use them for inserting text.

    Returns a dict: { base_font_name: registered_name }
    """
    registered = {}
    seen_xrefs = set()

    for page in doc:
        for font_info in page.get_fonts(full=True):
            xref     = font_info[0]
            ext      = font_info[1]      # e.g. "ttf", "otf", "n/a"
            fonttype = font_info[2]      # e.g. "Type1", "TrueType", "CIDFontType0"
            basefont = font_info[3]      # e.g. "AAAAAA+Garet-Bold"

            if xref in seen_xrefs or xref <= 0:
                continue
            seen_xrefs.add(xref)

            # Strip subset prefix (6 uppercase letters + "+")
            clean_name = basefont.split("+")[-1] if "+" in basefont else basefont
            if not clean_name or clean_name in registered:
                continue

            # Try multiple extraction methods
            font_bytes = None
            
            # Method 1: extract_font (most reliable for embedded fonts)
            try:
                font_data = doc.extract_font(xref)
                if font_data and font_data[0]:  # font_data is (basename, ext, type, content)
                    font_bytes = font_data[-1]  # content is the last element
            except Exception:
                pass

            # Method 2: xref_get_key (for font streams)
            if not font_bytes:
                try:
                    # Some fonts have their data in /FontFile, /FontFile2, or /FontFile3
                    for key in ["FontFile", "FontFile2", "FontFile3"]:
                        try:
                            stream = doc.xref_get_key(xref, key)
                            if stream and stream[1]:  # stream is (type, content)
                                font_bytes = stream[1]
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            # If we got font bytes, try to register them
            if font_bytes and len(font_bytes) > 100:
                try:
                    doc.insert_font(fontname=clean_name, fontbuffer=font_bytes)
                    registered[clean_name] = clean_name
                except Exception:
                    # Registration failed - font might be corrupt or unsupported format
                    pass

    return registered


def _pick_font(embedded_name, registered_fonts, is_bold):
    """
    Pick the best font name to use for insert_text.

    Priority:
    1. If we successfully registered the embedded font, use it.
    2. Otherwise fall back to Helvetica (always available in PyMuPDF).
    """
    # Strip subset prefix
    clean = embedded_name.split("+")[-1] if "+" in embedded_name else embedded_name

    if clean in registered_fonts:
        return clean

    # Fallback to Helvetica - always available
    # Note: we use 'helv' for both regular and bold since we can't guarantee
    # that 'hebo' (Helvetica-Bold) is available in all PyMuPDF builds
    return "helv"
