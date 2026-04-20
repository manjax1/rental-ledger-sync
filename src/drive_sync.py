import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_drive_service():
    json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")
    info  = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def download_ledger(file_id: str, local_path: str) -> None:
    service    = get_drive_service()
    request    = service.files().get_media(fileId=file_id)
    fh         = io.FileIO(local_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.close()
    print(f"✅ Downloaded ledger from Google Drive to {local_path}")


def upload_ledger(file_id: str, local_path: str) -> None:
    service = get_drive_service()
    media   = MediaFileUpload(
        local_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=True,
    )
    service.files().update(fileId=file_id, media_body=media).execute()
    print(f"✅ Uploaded updated ledger to Google Drive")
