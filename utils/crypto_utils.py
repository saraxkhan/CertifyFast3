"""
Cryptographic utilities for certificate signing and verification.
"""
import hashlib
import secrets
from datetime import datetime


def generate_certificate_id():
    """Generate a unique certificate ID."""
    return secrets.token_urlsafe(16)


def compute_certificate_hash(cert_data):
    """
    Compute a SHA-256 hash of certificate data for verification.
    
    cert_data should be a dict with: name, course, date, cert_id
    """
    # Create a canonical string representation
    canonical = f"{cert_data['name']}|{cert_data['course']}|{cert_data['date']}|{cert_data['cert_id']}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def sign_certificate(cert_data, secret_key):
    """
    Create a digital signature for the certificate.
    
    In production, this would use asymmetric cryptography (RSA/ECDSA).
    For this implementation, we use HMAC-SHA256.
    """
    canonical = f"{cert_data['name']}|{cert_data['course']}|{cert_data['date']}|{cert_data['cert_id']}"
    signature = hashlib.sha256(f"{canonical}|{secret_key}".encode()).hexdigest()
    return signature


def verify_signature(cert_data, signature, secret_key):
    """Verify a certificate signature."""
    expected = sign_certificate(cert_data, secret_key)
    return secrets.compare_digest(signature, expected)
