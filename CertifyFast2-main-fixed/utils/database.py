"""
Database for storing issued certificates.
"""
import sqlite3
import os
from datetime import datetime
import json


DB_PATH = "certificates.db"


def init_db():
    """Initialize the certificate database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            cert_id TEXT PRIMARY KEY,
            recipient_name TEXT NOT NULL,
            course_name TEXT NOT NULL,
            issue_date TEXT NOT NULL,
            signature TEXT NOT NULL,
            data_hash TEXT NOT NULL,
            additional_data TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()


def store_certificate(cert_id, name, course, date, signature, data_hash, additional_data=None):
    """Store a certificate in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO certificates (cert_id, recipient_name, course_name, issue_date, signature, data_hash, additional_data, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        cert_id,
        name,
        course,
        date,
        signature,
        data_hash,
        json.dumps(additional_data) if additional_data else None,
        datetime.now().isoformat()
    ))
    
    conn.commit()
    conn.close()


def get_certificate(cert_id):
    """Retrieve a certificate by ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT cert_id, recipient_name, course_name, issue_date, signature, data_hash, additional_data, created_at
        FROM certificates
        WHERE cert_id = ?
    """, (cert_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            'cert_id': row[0],
            'name': row[1],
            'course': row[2],
            'date': row[3],
            'signature': row[4],
            'data_hash': row[5],
            'additional_data': json.loads(row[6]) if row[6] else None,
            'created_at': row[7]
        }
    return None
