import argparse
import fitz
import re
import os
import unicodedata
from pathlib import Path


def sanitize(name):
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    name = name.upper().replace(' ', '_')
    name = re.sub(r'[/\\:*?"<>|]', '', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name


def extract_valor_pix(text):
    m = re.search(r'Valor\nR\$\s*([\d.,]+)', text)
    if m:
        return m.group(1).replace('.', '')
    return 'VALOR_DESCONHECIDO'


def extract_valor_bol(text):
    m = re.search(r'Valor total pago:\nR\$[\xa0\s]*([\d.,]+)', text)
    if m:
        return m.group(1).replace('.', '')
    return 'VALOR_DESCONHECIDO'


def extract_nome_pix(text):
    m = re.search(r'Para\n(.+?)\nChave\n', text, re.DOTALL)
    if m:
        name = m.group(1).strip().replace('\n', ' ')
        return sanitize(name)
    return 'NOME_DESCONHECIDO'


def _extract_multiline_field(text_after_label):
    lines = []
    for line in text_after_label.split('\n'):
        if not line.strip():
            break
        if re.match(r'(Dados|CNPJ:|Razão Social:|Nome Fantasia:|Código|Nosso Número)', line):
            break
        lines.append(line.strip())
    return ' '.join(lines)


def extract_nome_bol(text):
    before_pagador = text.split('Dados do Pagador')[0]

    # Try Nome Fantasia first (last occurrence = Sacador Avalista when present)
    parts = before_pagador.split('Nome Fantasia:\n')
    if len(parts) >= 2:
        name = _extract_multiline_field(parts[-1])
        if name:
            return sanitize(name)

    # Fallback: use Razão Social of beneficiary (first occurrence)
    parts_rs = before_pagador.split('Razão Social:\n')
    if len(parts_rs) >= 2:
        name = _extract_multiline_field(parts_rs[1])
        if name:
            return sanitize(name)

    return 'NOME_DESCONHECIDO'


def split_pdf(pdf_path, output_dir, tipo):
    date = re.search(r'(\d{8})', os.path.basename(pdf_path))
    date_str = date.group(1) if date else 'DATADESCONHECIDA'

    doc = fitz.open(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    # First pass: collect metadata for all pages to detect duplicates
    pages = []
    for page in doc:
        text = page.get_text()
        if tipo == 'PIX':
            valor = extract_valor_pix(text)
            nome  = extract_nome_pix(text)
        else:
            valor = extract_valor_bol(text)
            nome  = extract_nome_bol(text)
        pages.append((valor, nome))

    # Count occurrences of each (valor, nome) pair
    from collections import Counter
    counts = Counter(pages)
    occurrence = {}

    results = []
    for i, (valor, nome) in enumerate(pages):
        key = (valor, nome)
        total = counts[key]
        occurrence[key] = occurrence.get(key, 0) + 1
        idx = occurrence[key]

        base = f"COMPROVANTE-{date_str}-{valor}-{nome}"
        filename = f"{base}_{idx}DE{total}.pdf" if total > 1 else f"{base}.pdf"
        out_path = os.path.join(output_dir, filename)

        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=i, to_page=i)
        new_doc.save(out_path)
        new_doc.close()

        results.append((i + 1, filename))
        print(f"  [{i+1:02d}] {filename}")

    doc.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pix', default=None, help='Caminho para o PDF de comprovantes PIX')
    parser.add_argument('--bol', default=None, help='Caminho para o PDF de comprovantes BOL')
    parser.add_argument('--data-lote', default='20042026', help='Data no formato DDMMAAAA')
    parser.add_argument('--data-pasta', default='20260420', help='Data no formato AAAAMMDD')
    args = parser.parse_args()

    base = str(Path.home() / 'QuickAttach')
    DATA_LOTE = args.data_lote
    DATA_PASTA = args.data_pasta

    lote_dir = os.path.join(base, 'COMPROVANTES', f'COMPROVANTES_{DATA_PASTA}')
    output = os.path.join(base, 'COMPROVANTES_SEPARADOS', f'COMPROVANTES_SEP_{DATA_PASTA}')

    arquivos = {}
    if args.pix:
        arquivos['PIX'] = args.pix
    else:
        arquivos['PIX'] = os.path.join(lote_dir, f'COMPROVANTE {DATA_LOTE} PIX.pdf')
    if args.bol:
        arquivos['BOL'] = args.bol
    else:
        arquivos['BOL'] = os.path.join(lote_dir, f'COMPROVANTE {DATA_LOTE} BOL.pdf')

    total = 0
    for tipo, path in arquivos.items():
        if not os.path.exists(path):
            print(f"  AVISO: arquivo não encontrado, pulando: {path}")
            continue
        print(f"\n=== {tipo} ({os.path.basename(path)}) ===")
        results = split_pdf(path, output, tipo)
        total += len(results)

    print(f"\nConcluído: {total} comprovantes salvos em {output}")
    print(f"Fonte: {lote_dir}")


if __name__ == '__main__':
    main()
