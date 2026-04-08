import os
import random
import string
import sys

# Add parent directory to path to allow importing app and models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, User
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

def generate_random_string(length=12):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(length))

def setup_official():
    with app.app_context():
        print("\n" + "="*40)
        print("   NOX TOOLS - OFFICIAL SETUP")
        print("="*40)
        
        # 1. Clear existing users
        print("\n[1/3] Clearing all existing users from the database...")
        try:
            num_deleted = User.query.delete()
            print(f"      Successfully removed {num_deleted} users.")
        except Exception as e:
            print(f"      Error clearing users: {str(e)}")
            return
        
        # 2. Generate random credentials
        print("[2/3] Generating random admin credentials...")
        admin_username = "admin_" + generate_random_string(6).lower()
        admin_password = generate_random_string(16)
        
        # 3. Create Master Admin
        print("[3/3] Creating Master Admin account...")
        try:
            master_admin = User(
                username=admin_username,
                password_hash=generate_password_hash(admin_password),
                role='ADMIN',
                must_change_password=False,
                display_name="Master Admin"
            )
            
            db.session.add(master_admin)
            db.session.commit()
            print("      Master Admin created successfully.")
        except Exception as e:
            print(f"      Error creating account: {str(e)}")
            db.session.rollback()
            return
        
        print("\n" + "#"*40)
        print("   OFFICIAL ADMIN ACCOUNT CREATED")
        print("#"*40)
        print(f"   LOGIN:    {admin_username}")
        print(f"   PASSWORD: {admin_password}")
        print("#"*40)
        print("\n   SAVE THESE DETAILS SECURELY!")
        print("   Use this account to add other users.")
        print("   All other accounts have been deleted.")
        print("#"*40 + "\n")

if __name__ == "__main__":
    setup_official()
