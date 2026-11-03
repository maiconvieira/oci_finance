"""
Script interativo de configuração e teste do Google Drive para o OCI Finance.
Execute com:
    python setup_gdrive.py
"""
import importlib
import io
import json
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

SCOPES = ['https://www.googleapis.com/auth/drive.file']


def main():
    print("=" * 65)
    print("  CONFIGURAÇÃO E TESTE DO GOOGLE DRIVE - OCI FINANCE")
    print("=" * 65)

    folder_id = (os.getenv('GOOGLE_DRIVE_FOLDER_ID') or '').strip()
    creds_file = (os.getenv('GOOGLE_DRIVE_CREDENTIALS_FILE') or 'gdrive_credentials.json').strip()
    token_file = (os.getenv('GOOGLE_DRIVE_TOKEN_FILE') or 'gdrive_token.json').strip()

    creds_path = BASE_DIR / creds_file if not Path(creds_file).is_absolute() else Path(creds_file)
    token_path = BASE_DIR / token_file if not Path(token_file).is_absolute() else Path(token_file)

    if not folder_id:
        print("\n[!] Falta definir GOOGLE_DRIVE_FOLDER_ID no arquivo .env")
        print("    Exemplo no .env:")
        print("    GOOGLE_DRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz")
        return

    if not creds_path.exists():
        print(f"\n[!] Arquivo de credenciais não encontrado em: {creds_path}")
        print("    Baixe o JSON no Google Cloud Console e salve na raiz do projeto como:")
        print("    gdrive_credentials.json")
        return

    raw_data = json.loads(creds_path.read_text(encoding='utf-8'))

    # Caso 1: OAuth 2.0 Client ID (Recomendado para contas @gmail.com pessoais e Workspace)
    if 'installed' in raw_data or 'web' in raw_data:
        print("\n[*] Credencial detectada: OAuth 2.0 Client ID")
        oauth_creds_mod = importlib.import_module('google.oauth2.credentials')
        requests_mod = importlib.import_module('google.auth.transport.requests')

        creds = None
        if token_path.exists():
            creds = oauth_creds_mod.Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("[*] Atualizando token de acesso...")
                creds.refresh(requests_mod.Request())
            else:
                try:
                    flow_mod = importlib.import_module('google_auth_oauthlib.flow')
                except ModuleNotFoundError:
                    print("\n[!] Para autenticar via navegador na 1ª vez, instale:")
                    print("    pip install google-auth-oauthlib")
                    return
                print("[*] Abrindo o navegador para autorizar o acesso à pasta do Google Drive...")
                flow = flow_mod.InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0)

            token_path.write_text(creds.to_json(), encoding='utf-8')
            print(f"[OK] Token salvo com sucesso em: {token_path.name}")

    # Caso 2: Service Account (Conta de Serviço)
    elif raw_data.get('type') == 'service_account':
        print("\n[*] Credencial detectada: Conta de Serviço (Service Account)")
        print(f"    E-mail da conta de serviço: {raw_data.get('client_email')}")
        print("    IMPORTANTE: Certifique-se de que a pasta do Google Drive foi compartilhada")
        print("    com esse e-mail acima com permissão de 'Editor'.")
        sa_mod = importlib.import_module('google.oauth2.service_account')
        creds = sa_mod.Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
    else:
        print("\n[!] Formato de JSON não reconhecido em gdrive_credentials.json.")
        return

    # Faz um teste real enviando um arquivo TXT de verificação para a pasta
    print(f"\n[*] Testando envio para a pasta ID: {folder_id} ...")
    try:
        discovery = importlib.import_module('googleapiclient.discovery')
        http_mod = importlib.import_module('googleapiclient.http')

        service = discovery.build('drive', 'v3', credentials=creds)
        test_content = b"Teste de integracao OCI Finance - Google Drive OK!"
        media = http_mod.MediaIoBaseUpload(io.BytesIO(test_content), mimetype='text/plain', resumable=False)
        created = service.files().create(
            body={'name': 'teste_conexao_oci_finance.txt', 'parents': [folder_id]},
            media_body=media,
            fields='id, name, webViewLink',
            supportsAllDrives=True,
        ).execute()

        print("\n[SUCESSO!] O arquivo de teste foi salvo na sua pasta do Google Drive!")
        print(f"  -> Nome: {created.get('name')}")
        print(f"  -> Link: {created.get('webViewLink')}")
        print("\nAgora todos os comprovantes enviados na tela de Liquidação serão salvos automaticamente nessa pasta!")
    except Exception as exc:
        print(f"\n[ERRO NO TESTE DE ENVIO]: {exc}")


if __name__ == '__main__':
    main()

