"""
Run this ONCE locally to generate your SESSION_STRING.
Copy the output string into Railway Variables as SESSION_STRING.

Usage:
  pip install pyrofork tgcrypto-pyrofork
  python session_gen.py
"""
from pyrogram import Client

api_id   = int(input("Enter API_ID: ").strip())
api_hash = input("Enter API_HASH: ").strip()

with Client("temp_session", api_id=api_id, api_hash=api_hash) as app:
    print("\n✅ SESSION_STRING:")
    print(app.export_session_string())
