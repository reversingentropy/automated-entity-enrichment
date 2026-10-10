"""
Test configuration.

Every test here runs offline. Importing the job modules pulls in the Supabase
and Gemini clients, which read credentials at call time rather than import
time, so placeholders are enough to import them safely.
"""

import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
