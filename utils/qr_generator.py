"""
QR code generation for certificate verification.
"""
import qrcode
from io import BytesIO


def generate_qr_code(verification_url, size_pixels=200):
    """
    Generate a QR code image for the verification URL.
    
    Returns: PIL Image object
    """
    qr = qrcode.QRCode(
        version=1,  # Auto-adjust size
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction
        box_size=10,
        border=2,
    )
    qr.add_data(verification_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Resize to desired size
    img = img.resize((size_pixels, size_pixels))
    
    return img


def qr_to_bytes(qr_image):
    """Convert PIL Image to bytes for embedding in PDF."""
    buf = BytesIO()
    qr_image.save(buf, format='PNG')
    buf.seek(0)
    return buf.read()
