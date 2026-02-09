# CertifyFast - Certificate Generator with QR Verification

Generate professional certificates with **QR codes** and **digital signatures** for verification.

## 🎯 Features

### Core Features
- ✅ **Universal Template Support** - Works with any PDF template containing `{{placeholders}}`
- ✅ **Automatic Font Matching** - Extracts and preserves original fonts, sizes, and colors
- ✅ **Smart Column Mapping** - Automatically matches data columns to placeholders
- ✅ **Batch Generation** - Generate hundreds of certificates in seconds

### Security & Verification
- 🔐 **Digital Signatures** - Each certificate is cryptographically signed
- 📱 **QR Code Integration** - Automatic QR code on each certificate
- ✅ **Online Verification** - Scan QR to verify authenticity
- 💾 **Certificate Database** - All issued certificates stored in SQLite

## 🚀 Quick Start

### Installation

```bash
# 1. Extract the zip
unzip CertifyFast2-main.zip
cd CertifyFast2-main

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

Visit: `http://localhost:5001`

### Usage

1. **Upload your PDF template** with placeholders like `{{Name}}`, `{{Course}}`, `{{Date}}`
2. **Upload your data** (Excel or CSV) with columns matching the placeholders
3. **Review the mapping** - see which placeholders matched which columns
4. **Generate & Download** - get a ZIP with all certificates

## 📋 Template Requirements

Your PDF template should contain placeholders in double curly braces:

```
{{Name}}
{{Course}}
{{Date}}
{{Organization}}
```

The system will:
- Extract the exact font, size, and color of each placeholder
- Replace it with data from your Excel/CSV
- Add a QR code for verification (bottom-right by default)

## 📊 Data File Format

Excel or CSV with columns matching your placeholders:

```csv
Name,Course,Date
Sara Khan,Python Basics,2024-01-15
Reha Ahmed,Web Development,2024-01-16
Shifa Ali,Data Science,2024-01-17
```

**Note**: Column names are case-insensitive. `Name`, `name`, and `NAME` all work.

## 🔐 Security Features

### Digital Signatures
Each certificate receives:
- Unique Certificate ID (e.g., `Xk9mP2nQ7rL`)
- Digital signature (HMAC-SHA256)
- Cryptographic hash of certificate data

### QR Code Verification
The QR code contains a URL like:
```
http://localhost:5001/verify/Xk9mP2nQ7rL
```

Scanning it shows:
- ✅ Valid/Invalid status
- Recipient name
- Course/program name
- Issue date
- Digital signature verification

## 🛠️ Configuration

### Environment Variables

```bash
# Secret key for signing (IMPORTANT: Change in production!)
export CERT_SECRET_KEY="your-super-secret-key-here"

# Base URL for QR codes
export BASE_URL="https://your-domain.com"
```

### QR Code Position

In `app.py`, line ~231, change `qr_position`:

```python
generate_certificate(
    ...
    qr_position="bottom-right"  # Options: bottom-right, bottom-left, top-right, top-left
)
```

## 📡 API Endpoints

### Verification API

```bash
GET /api/verify/<cert_id>
```

Response:
```json
{
  "found": true,
  "valid": true,
  "certificate": {
    "id": "Xk9mP2nQ7rL",
    "recipient": "Sara Khan",
    "course": "Python Basics",
    "issue_date": "2024-01-15",
    "issued_at": "2024-02-04T18:00:00"
  }
}
```

## 🗄️ Database

Certificates are stored in `certificates.db` (SQLite):

```sql
SELECT * FROM certificates WHERE recipient_name = 'Sara Khan';
```

Schema:
- `cert_id` - Unique certificate ID
- `recipient_name` - Certificate recipient
- `course_name` - Course/program name
- `issue_date` - Issue date
- `signature` - Digital signature
- `data_hash` - SHA-256 hash
- `additional_data` - JSON with all data columns
- `created_at` - Timestamp

## 🔧 Troubleshooting

### QR Code not appearing?
- Check that `qrcode[pil]` is installed: `pip install qrcode[pil]`
- Check terminal for QR generation errors

### Verification page not loading?
- Make sure `BASE_URL` matches your actual URL
- Check `certificates.db` exists and is not corrupted

### Fonts not matching?
- The system tries to extract embedded fonts from the PDF
- If extraction fails, it falls back to Helvetica
- For best results, use standard fonts in your template

## 📝 Production Deployment

**Important security steps:**

1. **Change the SECRET_KEY**:
   ```bash
   export CERT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   ```

2. **Set BASE_URL**:
   ```bash
   export BASE_URL="https://certificates.yourcompany.com"
   ```

3. **Use HTTPS** - QR codes should point to secure URLs

4. **Backup the database** - `certificates.db` contains all issued certificates

5. **Use production WSGI server**:
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5001 app:app
   ```

## 📄 License

MIT License - Free to use for personal and commercial projects.

## 🆘 Support

Issues? Questions? Check the code comments or create an issue in your repository.

---

**Built with**: Flask • PyMuPDF • QRCode • Pillow • SQLite
