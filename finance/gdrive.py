# finance/gdrive.py
"""
Integração de upload de comprovantes para uma pasta do Google Drive usando
`google-api-python-client` e `google-auth`.

Suporta:
1. OAuth2 Token (`gdrive_token.json` gerado pelo script `setup_gdrive.py` — funciona em contas @gmail.com pessoais e Workspace)
2. Service Account JSON (`GOOGLE_DRIVE_CREDENTIALS_FILE` no `.env`)
3. Google Apps Script Webhook (`GOOGLE_DRIVE_WEBHOOK_URL` no `.env`)
"""
import base64
import importlib
import io
import json
import mimetypes
import os
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(path_str):
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p if p.exists() else None


def get_gdrive_credentials():
    """
    Carrega as credenciais do Google Drive:
    1º Verifica se existe token OAuth2 autorizado (`GOOGLE_DRIVE_TOKEN_FILE` ou `gdrive_token.json`).
    2º Verifica se o arquivo em `GOOGLE_DRIVE_CREDENTIALS_FILE` é uma Service Account.
    """
    load_dotenv(BASE_DIR / '.env', override=True)
    scopes = ['https://www.googleapis.com/auth/drive.file']
    token_file_str = (os.getenv('GOOGLE_DRIVE_TOKEN_FILE') or 'gdrive_token.json').strip()
    token_path = _resolve_path(token_file_str)

    # 1. Token OAuth2 de usuário (funciona em @gmail.com pessoal e Google Workspace)
    if token_path:
        oauth_creds_mod = importlib.import_module('google.oauth2.credentials')
        requests_mod = importlib.import_module('google.auth.transport.requests')
        creds = oauth_creds_mod.Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(requests_mod.Request())
            token_path.write_text(creds.to_json(), encoding='utf-8')
        if creds and creds.valid:
            return creds

    # 2. Service Account JSON
    creds_file_str = (os.getenv('GOOGLE_DRIVE_CREDENTIALS_FILE') or 'gdrive_credentials.json').strip()
    creds_path = _resolve_path(creds_file_str)
    if creds_path:
        raw_json = json.loads(creds_path.read_text(encoding='utf-8'))
        if raw_json.get('type') == 'service_account':
            sa_mod = importlib.import_module('google.oauth2.service_account')
            return sa_mod.Credentials.from_service_account_file(str(creds_path), scopes=scopes)

    return None


def upload_receipt_to_google_drive(uploaded_file, filename_prefix=''):
    """
    Envia o arquivo de comprovante para a pasta do Google Drive configurada no .env (`GOOGLE_DRIVE_FOLDER_ID`).
    Retorna um dicionário:
      {'success': True/False, 'file_id': '...', 'web_view_link': '...', 'error': '...'}
    """
    if not uploaded_file:
        return {'success': False, 'skipped': True}

    load_dotenv(BASE_DIR / '.env', override=True)
    folder_id = (os.getenv('GOOGLE_DRIVE_FOLDER_ID') or '').strip()
    webhook_url = (os.getenv('GOOGLE_DRIVE_WEBHOOK_URL') or '').strip()

    raw_name = getattr(uploaded_file, 'name', 'comprovante') or 'comprovante'
    original_name = Path(raw_name).name
    final_name = f"{filename_prefix}_{original_name}" if filename_prefix else original_name
    mime_type = (
        getattr(uploaded_file, 'content_type', None)
        or mimetypes.guess_type(original_name)[0]
        or 'application/octet-stream'
    )

    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    # -------------------------------------------------------------------------
    # OPÇÃO 1: API Oficial do Google Drive (`google-api-python-client` + `google-auth`)
    # -------------------------------------------------------------------------
    if folder_id:
        try:
            creds = get_gdrive_credentials()
            if creds is not None:
                discovery = importlib.import_module('googleapiclient.discovery')
                http_mod = importlib.import_module('googleapiclient.http')

                service = discovery.build('drive', 'v3', credentials=creds)
                file_metadata = {
                    'name': final_name,
                    'parents': [folder_id],
                }
                media = http_mod.MediaIoBaseUpload(
                    io.BytesIO(raw_bytes),
                    mimetype=mime_type,
                    resumable=False,
                )
                created = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, webViewLink',
                    supportsAllDrives=True,
                ).execute()

                return {
                    'success': True,
                    'file_id': created.get('id', ''),
                    'web_view_link': created.get('webViewLink', ''),
                }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    # -------------------------------------------------------------------------
    # OPÇÃO 2: Webhook Google Apps Script (alternativa sem Google Cloud Console)
    # -------------------------------------------------------------------------
    if webhook_url:
        try:
            payload = json.dumps({
                'filename': final_name,
                'mimeType': mime_type,
                'folderId': folder_id,
                'fileBase64': base64.b64encode(raw_bytes).decode('ascii'),
            }).encode('utf-8')

            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp_body = resp.read().decode('utf-8', errors='ignore')
                data = json.loads(resp_body)
                if data.get('success') or data.get('webViewLink') or data.get('id'):
                    return {
                        'success': True,
                        'file_id': data.get('id', ''),
                        'web_view_link': data.get('webViewLink', ''),
                    }
                return {'success': False, 'error': data.get('error', 'Erro no Webhook do Google Drive.')}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    return {'success': False, 'skipped': True}
