import os
import sys

# Add the parent directory to sys.path so we can import Vehicle.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Vehicle import app

# Vercel serverless handler expects 'app'
