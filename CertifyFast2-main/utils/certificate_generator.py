import fitz


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


def generate_certificate(template_path, output_path, row_data, placeholders):
    """
    Generate one certificate.

    row_data:     { "Vegetable": "Carrot", "Fruit": "Apple", ... }
                  Raw column→value dict from one DataFrame row.

    placeholders: { "vegetable": { rect, font_size, font_name, color … }, … }
                  Keyed by the lowercased text inside {{ }} in the template.

    Matching rule:   {{vegetable}}  ←→  column "Vegetable"
                     lowercase both sides, compare.  That is the only rule.
    """
    doc = fitz.open(template_path)
    page = doc[0]
    page_width = page.rect.width

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
        rect = meta["rect"]
        font_size = meta["font_size"]       # ← REAL size from span, not bbox height
        font_name = meta["font_name"]       # ← correct font (embedded or helv fallback)
        color = meta["color"]               # ← original color from template

        # ── Detect alignment of this placeholder ──
        alignment = _detect_alignment(page, rect, font_size)

        # ── Detect background color for clean redaction ──
        bg_color = _detect_background_color(page, rect)

        # ── Measure replacement text width at the correct font size ──
        text_width = fitz.get_text_length(value, fontsize=font_size, fontname=font_name)

        # ── Auto-shrink: if text is wider than available space, shrink ──
        # Available space = from placeholder x0 to roughly 90% of page width
        # (generous limit; real limit depends on template layout)
        max_width = page_width * 0.85 - rect.x0
        current_size = font_size
        for _ in range(30):    # max 30 shrink iterations
            if text_width <= max_width:
                break
            current_size *= 0.93   # shrink 7% per step
            text_width = fitz.get_text_length(value, fontsize=current_size, fontname=font_name)

        # ── Calculate X position ──
        if alignment == "left":
            x = rect.x0
        else:
            # Center within the placeholder's bounding rect
            x = rect.x0 + (rect.width - text_width) / 2.0
            # If centered text would go off-page, fall back to left
            if x < 0 or x + text_width > page_width:
                x = rect.x0

        # ── Calculate Y position (baseline) ──
        # fitz insert_text places text with Y at the BASELINE.
        # Baseline ≈ rect.y0 + font_size * 0.75  (ascent ratio for most fonts)
        # This places the visible text vertically centered in the rect.
        y = rect.y0 + current_size * 0.78

        # ── Redact the placeholder ──
        # Expand the redact rect slightly to catch any anti-aliasing edges
        redact_rect = fitz.Rect(
            rect.x0 - 1,
            rect.y0 - 1,
            rect.x1 + 1,
            rect.y1 + 1,
        )
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

    doc.save(output_path)
    doc.close()
