# finance/receipt_parser.py
import importlib
import io
import re
import zlib
from decimal import Decimal, InvalidOperation


MONTH_MAP_PT = {
    'jan': '01', 'janeiro': '01',
    'fev': '02', 'fevereiro': '02',
    'mar': '03', 'marco': '03', 'março': '03',
    'abr': '04', 'abril': '04',
    'mai': '05', 'maio': '05',
    'jun': '06', 'junho': '06',
    'jul': '07', 'julho': '07',
    'ago': '08', 'agosto': '08',
    'set': '09', 'setembro': '09',
    'out': '10', 'outubro': '10',
    'nov': '11', 'novembro': '11',
    'dez': '12', 'dezembro': '12',
}


def _decode_pdf_literal_string(raw_str):
    """Decodifica strings literais (...) de operadores de texto PDF."""
    out = []
    i = 0
    n = len(raw_str)
    while i < n:
        ch = raw_str[i]
        if ch == '\\' and i + 1 < n:
            nxt = raw_str[i + 1]
            if nxt in ('n', 'r', 't', 'b', 'f'):
                out.append({'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f'}[nxt])
                i += 2
            elif nxt in ('(', ')', '\\'):
                out.append(nxt)
                i += 2
            elif nxt.isdigit():
                octal = raw_str[i + 1:i + 4]
                m = re.match(r'^[0-7]{1,3}', octal)
                if m:
                    out.append(chr(int(m.group(0), 8)))
                    i += 1 + len(m.group(0))
                else:
                    i += 1
            else:
                out.append(nxt)
                i += 2
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _extract_pdf_text_fallback(file_bytes):
    """
    Extrator leve em Python puro (usando zlib) para capturar texto de streams PDF
    caso bibliotecas externas (pypdf/pdfplumber/pymupdf) não estejam instaladas.
    """
    chunks = []
    for match in re.finditer(rb'stream[\r\n]+(.*?)[\r\n]+endstream', file_bytes, re.DOTALL):
        stream_data = match.group(1)
        decompressed = None
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                decompressed = zlib.decompress(stream_data, wbits)
                break
            except Exception:
                continue
        if decompressed is None:
            decompressed = stream_data

        try:
            text_stream = decompressed.decode('latin-1', errors='ignore')
        except Exception:
            continue

        # Operadores TJ: [(texto) -10 (outro)] TJ
        for tj_arr in re.finditer(r'\[(.*?)\]\s*TJ', text_stream, re.DOTALL):
            arr_content = tj_arr.group(1)
            parts = []
            for lit in re.finditer(r'\((?:\\.|[^\\)])*\)', arr_content):
                parts.append(_decode_pdf_literal_string(lit.group(0)[1:-1]))
            if parts:
                chunks.append(''.join(parts))

        # Operadores Tj: (texto) Tj
        for tj_lit in re.finditer(r'\(((?:\\.|[^\\)])*)\)\s*Tj', text_stream):
            chunks.append(_decode_pdf_literal_string(tj_lit.group(1)))

    return '\n'.join(chunks)


def extract_text_from_uploaded_file(uploaded_file):
    """
    Tenta extrair texto de comprovantes em TXT, PDF ou IMAGEM.
    Retorna (texto_extraido, metodo_utilizado).
    """
    if not uploaded_file:
        return '', 'none'

    filename = (getattr(uploaded_file, 'name', '') or '').lower()
    uploaded_file.seek(0)
    raw_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    # 1. Arquivo TXT
    if filename.endswith('.txt') or getattr(uploaded_file, 'content_type', '') == 'text/plain':
        for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try:
                return raw_bytes.decode(enc), 'txt'
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode('utf-8', errors='ignore'), 'txt'

    # 2. Arquivo PDF
    if filename.endswith('.pdf') or getattr(uploaded_file, 'content_type', '') == 'application/pdf':
        # Tentativa com pypdf / PyPDF2
        for mod_name in ('pypdf', 'PyPDF2'):
            try:
                mod = importlib.import_module(mod_name)
                reader = mod.PdfReader(io.BytesIO(raw_bytes))
                pages_txt = [page.extract_text() or '' for page in reader.pages]
                joined = '\n'.join(pages_txt).strip()
                if joined:
                    return joined, mod_name
            except Exception:
                pass

        # Tentativa com fitz (PyMuPDF)
        try:
            fitz = importlib.import_module('fitz')
            doc = fitz.open(stream=raw_bytes, filetype='pdf')
            pages_txt = [page.get_text() for page in doc]
            joined = '\n'.join(pages_txt).strip()
            if joined:
                return joined, 'pymupdf'
        except Exception:
            pass

        # Fallback Python puro (zlib)
        fallback_txt = _extract_pdf_text_fallback(raw_bytes).strip()
        if fallback_txt:
            return fallback_txt, 'pdf_stream'
        return '', 'pdf_unreadable'

    # 3. Arquivo de Imagem (PNG, JPG, JPEG, WEBP, BMP)
    if any(filename.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.webp', '.bmp')):
        try:
            pil_image = importlib.import_module('PIL.Image')
            pytesseract = importlib.import_module('pytesseract')
            img = pil_image.open(io.BytesIO(raw_bytes))
            ocr_txt = pytesseract.image_to_string(img, lang='por+eng')
            if ocr_txt and ocr_txt.strip():
                return ocr_txt.strip(), 'pytesseract'
        except Exception:
            pass
        return '', 'image_client_ocr'

    return '', 'unsupported'


def _normalize_decimal_str(raw_val):
    """Converte string monetária brasileira (ex: '1.250,50' ou '150,00') para string '1250.50'."""
    if not raw_val:
        return ''
    s = raw_val.strip().replace('R$', '').replace(' ', '')
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        dec = Decimal(s)
        if dec > 0:
            return f"{dec:.2f}"
    except (InvalidOperation, ValueError):
        pass
    return ''


def parse_receipt_text(raw_text):
    """
    Analisa o texto extraído de um comprovante (TXT, PDF ou OCR de Imagem)
    e captura:
    - payment_date (YYYY-MM-DD)
    - payment_time (HH:MM)
    - payer_name (Nome do responsável pelo pagamento)
    - payer_account (Conta que está realizando o pagamento)
    - amount (Valor em formato 0.00)
    """
    result = {
        'payment_date': '',
        'payment_time': '',
        'payer_name': '',
        'payer_account': '',
        'amount': '',
    }
    if not raw_text or not raw_text.strip():
        return result

    text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]

    # =========================================================================
    # 1. CAPTURA DE DATA E HORA DO PAGAMENTO
    # =========================================================================
    # Padrão A: DD/MM/YYYY [às|-| ] HH:MM(:SS)
    dt_combined = re.search(
        r'\b([0-3]?\d)[/.-]([01]?\d)[/.-](20\d{2}|\d{2})(?:\s*(?:às|as|-|,|\s)\s*([0-2]?\d)[:h]([0-5]\d)(?::[0-5]\d)?)?\b',
        text,
        re.IGNORECASE,
    )
    if dt_combined:
        day = int(dt_combined.group(1))
        month = int(dt_combined.group(2))
        year_str = dt_combined.group(3)
        year = int('20' + year_str) if len(year_str) == 2 else int(year_str)
        if 1 <= day <= 31 and 1 <= month <= 12:
            result['payment_date'] = f"{year:04d}-{month:02d}-{day:02d}"
        if dt_combined.group(4) and dt_combined.group(5):
            hh = int(dt_combined.group(4))
            mm = int(dt_combined.group(5))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                result['payment_time'] = f"{hh:02d}:{mm:02d}"

    # Padrão B: Data por extenso (ex: 15 MAR 2026 ou 15 de março de 2026)
    if not result['payment_date']:
        ext_date = re.search(
            r'\b([0-3]?\d)\s*(?:de\s+)?(jan(?:eiro)?|fev(?:ereiro)?|mar(?:ço|co)?|abr(?:il)?|mai(?:o)?|jun(?:ho)?|jul(?:ho)?|ago(?:sto)?|set(?:embro)?|out(?:ubro)?|nov(?:embro)?|dez(?:embro)?)\s*(?:de\s+)?(20\d{2})\b',
            text,
            re.IGNORECASE,
        )
        if ext_date:
            day = int(ext_date.group(1))
            m_key = ext_date.group(2).lower()
            month = MONTH_MAP_PT.get(m_key) or MONTH_MAP_PT.get(m_key[:3])
            year = int(ext_date.group(3))
            if month and 1 <= day <= 31:
                result['payment_date'] = f"{year:04d}-{month}-{day:02d}"

    # Padrão C: YYYY-MM-DD
    if not result['payment_date']:
        iso_date = re.search(r'\b(20\d{2})-([01]\d)-([0-3]\d)\b', text)
        if iso_date:
            result['payment_date'] = f"{iso_date.group(1)}-{iso_date.group(2)}-{iso_date.group(3)}"

    # Se encontrou a data mas a hora estava em outra linha/posição
    if not result['payment_time']:
        time_match = re.search(
            r'(?:hora|hor[áa]rio|[àa]s)\s*:?\s*([0-2]?\d)[:h]([0-5]\d)(?::[0-5]\d)?\b|\b([0-2]\d):([0-5]\d)(?::[0-5]\d)?\b',
            text,
            re.IGNORECASE,
        )
        if time_match:
            hh = int(time_match.group(1) or time_match.group(3))
            mm = int(time_match.group(2) or time_match.group(4))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                result['payment_time'] = f"{hh:02d}:{mm:02d}"

    # =========================================================================
    # 2. CAPTURA DO VALOR DO PAGAMENTO
    # =========================================================================
    amount_patterns = [
        r'(?:valor\s*(?:pago|da\s*transfer[êe]ncia|do\s*pagamento|do\s*pix|total|da\s*transa[çc][ãa]o)?)\s*:?\s*R\$\s*([\d.]+,\d{2})',
        r'(?:valor\s*(?:pago|total|do\s*pagamento|do\s*pix))\s*:?\s*([\d.]+,\d{2})',
        r'R\$\s*([\d.]+,\d{2})',
        r'(?:valor|total)\s*:?\s*R?\$?\s*(\d+(?:[.,]\d{2}))',
    ]
    for pat in amount_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            norm = _normalize_decimal_str(m.group(1))
            if norm:
                result['amount'] = norm
                break

    # Se o rótulo "Valor" estiver em uma linha e "R$ 150,00" na linha seguinte
    if not result['amount']:
        for idx, ln in enumerate(lines):
            if re.match(r'^(?:valor(?:\s+pago|\s+total|\s+da\s+transfer[êe]ncia)?|total)\s*:?$', ln, re.IGNORECASE):
                if idx + 1 < len(lines):
                    m_next = re.search(r'([\d.]+,\d{2}|\d+\.\d{2})', lines[idx + 1])
                    if m_next:
                        norm = _normalize_decimal_str(m_next.group(1))
                        if norm:
                            result['amount'] = norm
                            break

    # =========================================================================
    # 3. CAPTURA DO NOME DO RESPONSÁVEL PELO PAGAMENTO (PAGADOR / ORIGEM / DE)
    # =========================================================================
    # Tenta isolar a seção de Origem / Pagador / Quem pagou (para não confundir com Destino / Recebedor)
    origin_section = text
    dest_split = re.split(
        r'\n\s*(?:dados\s+do\s+recebedor|dados\s+do\s+destinat[áa]rio|destinat[áa]rio|recebedor|para|favorecido|creditado)\b',
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )
    origin_match = re.search(
        r'(?:dados\s+do\s+pagador|pagador|origem|quem\s+pagou|remetente|de\b|debitado)(.*)',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if origin_match:
        candidate_sec = origin_match.group(0)
        # Corta se depois vier o destinatário
        candidate_split = re.split(
            r'\n\s*(?:dados\s+do\s+recebedor|dados\s+do\s+destinat[áa]rio|destinat[áa]rio|recebedor|para|favorecido)\b',
            candidate_sec,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        origin_section = candidate_split[0]
    elif len(dest_split) > 1:
        origin_section = dest_split[0]

    payer_inline_patterns = [
        r'(?:nome\s+do\s+pagador|respons[áa]vel(?:\s+pelo\s+pagamento)?|quem\s+pagou|pagador|remetente|ordenante|cliente)\s*:\s*([^\n\r]+)',
        r'(?:origem|de)\s*:\s*([A-Za-zÀ-ÿ][^\n\r0-9]{2,})',
        r'(?:nome)\s*:\s*([A-Za-zÀ-ÿ][^\n\r]{2,})',
    ]
    for pat in payer_inline_patterns:
        m = re.search(pat, origin_section, re.IGNORECASE)
        if not m:
            m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip(' -•:\t')
            if len(val) >= 3 and not re.match(r'^(?:cpf|cnpj|institui|banco|ag[êe]ncia|conta)\b', val, re.IGNORECASE):
                result['payer_name'] = val[:200]
                break

    # Caso multi-linha (ex: linha "Origem" ou "Pagador" ou "Nome" seguida pelo nome na linha abaixo)
    if not result['payer_name']:
        origin_lines = [ln.strip() for ln in origin_section.split('\n') if ln.strip()]
        for idx, ln in enumerate(origin_lines):
            if re.match(r'^(?:nome\s+do\s+pagador|pagador|quem\s+pagou|respons[áa]vel(?:\s+pelo\s+pagamento)?|remetente|nome|de|origem)\s*:?$', ln, re.IGNORECASE):
                # Olha até 2 linhas abaixo
                for offset in (1, 2):
                    if idx + offset < len(origin_lines):
                        cand = origin_lines[idx + offset].strip(' -•:\t')
                        if re.match(r'^(?:nome)\s*:?$', cand, re.IGNORECASE):
                            continue
                        if (
                            len(cand) >= 3
                            and not re.search(r'(?:cpf|cnpj|R\$|\d{2}/\d{2}/\d{4}|institui[çc][ãa]o|ag[êe]ncia|chave)', cand, re.IGNORECASE)
                        ):
                            result['payer_name'] = cand[:200]
                            break
                if result['payer_name']:
                    break

    # =========================================================================
    # 4. CAPTURA DA CONTA QUE ESTÁ REALIZANDO O PAGAMENTO
    # =========================================================================
    account_parts = []

    # Instituição / Banco na seção de origem
    inst_match = re.search(
        r'(?:institui[çc][ãa]o|banco(?:\s+de\s+origem)?)\s*:\s*([^\n\r]+)',
        origin_section,
        re.IGNORECASE,
    )
    if inst_match:
        inst_val = inst_match.group(1).strip(' -•:\t')
        if inst_val:
            account_parts.append(inst_val)
    else:
        # Multi-linha para Instituição / Banco
        origin_lines = [ln.strip() for ln in origin_section.split('\n') if ln.strip()]
        for idx, ln in enumerate(origin_lines):
            if re.match(r'^(?:institui[çc][ãa]o|banco(?:\s+de\s+origem)?)\s*:?$', ln, re.IGNORECASE):
                if idx + 1 < len(origin_lines):
                    account_parts.append(origin_lines[idx + 1].strip(' -•:\t'))
                break

    # Agência e Conta / Conta de origem
    acc_inline_patterns = [
        r'(?:conta\s+de\s+origem|conta\s+debitada|ag[êe]ncia\s*/\s*conta|ag[êe]ncia\s+e\s+conta|conta(?:\s+corrente|\s+pagamento)?)\s*:\s*([^\n\r]+)',
        r'(ag[êe]ncia\s*:?\s*[\d.-]+\s*(?:[/|-]|\s+conta\s*:?)\s*[\d.-]+)',
        r'(ag\.?\s*[\d.-]+\s*(?:[/|-]|\s+cc\.?|\s+c/c:?|\s+conta:?)\s*[\d.-]+)',
    ]
    for pat in acc_inline_patterns:
        m = re.search(pat, origin_section, re.IGNORECASE)
        if not m:
            m = re.search(pat, text, re.IGNORECASE)
        if m:
            acc_val = m.group(1).strip(' -•:\t')
            if acc_val and acc_val not in account_parts:
                account_parts.append(acc_val)
                break

    # Se Agência e Conta aparecem separadas
    if len(account_parts) <= 1:
        ag_m = re.search(r'ag[êe]ncia\s*:\s*([\d-]+)', origin_section, re.IGNORECASE)
        cc_m = re.search(r'conta\s*:\s*([\d.-]+)', origin_section, re.IGNORECASE)
        if ag_m and cc_m:
            combined_ag_cc = f"Ag {ag_m.group(1)} / Conta {cc_m.group(1)}"
            if combined_ag_cc not in account_parts:
                account_parts.append(combined_ag_cc)

    if account_parts:
        result['payer_account'] = ' — '.join(account_parts)[:200]

    return result
