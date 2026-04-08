import sys
import os

# Add the parent directory to sys.path so we can import app.py correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# This allows Vercel to discover the app object
# when pointing to this file.
if __name__ == "__main__":
    app.run()
