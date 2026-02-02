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
        for font_tuple in page.get_fonts(ext=True):
            # font_tuple: (xref, ext, type, basefont, name, encoding, ...)
            xref      = font_tuple[0]
            ext       = font_tuple[1]   # e.g. "ttf", "otf"
            basefont  = font_tuple[3]   # e.g. "AAAAAA+Garet-Bold"
            name      = font_tuple[4]   # e.g. "Garet-Bold"

            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            # Strip the subset prefix (6 uppercase letters + "+")
            clean_name = basefont.split("+")[-1] if "+" in basefont else basefont

            if clean_name in registered:
                continue

            try:
                # Extract the font file bytes
                font_bytes = doc.get_font_image(xref)
                if font_bytes and len(font_bytes) > 100:
                    # Register it so insert_text can use it
                    doc.insert_font(fontname=clean_name, fontbytes=font_bytes)
                    registered[clean_name] = clean_name
            except Exception:
                # get_font_image might not work for all font types;
                # that's fine, we fall back to standard fonts
                pass

    return registered


def _pick_font(embedded_name, registered_fonts, is_bold):
    """
    Pick the best font name to use for insert_text.

    Priority:
    1. If we successfully registered the embedded font, use it.
    2. Otherwise fall back to standard Helvetica variants.
    """
    # Strip subset prefix
    clean = embedded_name.split("+")[-1] if "+" in embedded_name else embedded_name

    if clean in registered_fonts:
        return clean

    # Fallback to standard fonts
    return "helv-bold" if is_bold else "helv"
