import firebase_admin
from firebase_admin import credentials, storage
import os
from dotenv import load_dotenv

load_dotenv()

def initialize_firebase():
    """Initialize Firebase with credentials"""
    cred = credentials.Certificate({
        "type": "service_account",
        "project_id": os.getenv("FIREBASE_PROJECT_ID"),
        "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
        "private_key": os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
        "client_id": os.getenv("FIREBASE_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.getenv("FIREBASE_CLIENT_CERT_URL")
    })
    
    firebase_admin.initialize_app(cred, {
        'storageBucket': os.getenv("FIREBASE_STORAGE_BUCKET")
    })
    
    return storage.bucket()

async def upload_file_to_firebase(file_path: str, destination_blob_name: str) -> str:
    """Upload a file to Firebase Storage"""
    bucket = storage.bucket()
    blob = bucket.blob(destination_blob_name)
    
    # Upload the file
    blob.upload_from_filename(file_path)
    
    # Make the blob publicly accessible
    blob.make_public()
    
    return blob.public_url

async def download_file_from_firebase(source_blob_name: str, destination_file_path: str):
    """Download a file from Firebase Storage"""
    bucket = storage.bucket()
    blob = bucket.blob(source_blob_name)
    blob.download_to_filename(destination_file_path) 