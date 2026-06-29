import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- App ---
SECRET_KEY ='0077'

# --- MySQL connection ---
# Override these with real values, e.g. via environment variables,
# or just edit the defaults below for local development.
DB_HOST = "162.215.252.35"
DB_USER = "shorthu4_charan"
DB_PASSWORD = "Charan@123$"          # Change if your root user has a password
DB_NAME = "shorthu4_charan" 

# --- Uploads ---
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size

# --- Default admin account (auto-created on first run if no admin exists) ---
DEFAULT_ADMIN_NAME = os.environ.get('DEFAULT_ADMIN_NAME', 'Administrator')
DEFAULT_ADMIN_EMAIL = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
DEFAULT_ADMIN_PASSWORD = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'Admin@123')
