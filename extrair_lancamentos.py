"""Etapa 5: Extrair lançamentos do RELATORIO_CONTAS_PAGAS e cruzar com comprovantes."""

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pdfplumber

BASE_DIR = Path.home() / 'QuickAttach'
DATA_PASTA = '20260420'    # AAAAMMDD
DATA_LOTE = '20042026'
COMPROVANTES_DIR = BASE_DIR / 'COMPROVANTES_SEPARADOS' / f'COMPROVANTES_SEP_{DATA_PASTA}'
RELATORIO_PDF = (BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{DATA_PASTA}'
                 / f'RELATORIO_CONTAS_PAGAS_{DATA_LOTE}.pdf')
OUTPUT_JSON = (BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{DATA_PASTA}'
               / f'LANCAMENTOS_MATCHED_{DATA_LOTE}.json')


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_valor(s):
    """'1.458,86T' -> 1458.86"""
    return float(s.strip().rstrip('T').replace('.', '').replace(',', '.'))


def _sanitize(name):
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    return re.sub(r'_+', '_', name.upper().replace(' ', '_').replace('\n', '_')).strip('_')


def parse_relatorio(pdf_path):
    """Return list of lançamento dicts extracted from the PDF report."""
    lancamentos = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or not table[0] or 'Lançamento' not in table[0]:
                    continue
                idx = {col: i for i, col in enumerate(table[0]) if col}
                for row in table[1:]:
                    lancamento_val = row[idx.get('Lançamento', 3)]
                    if not lancamento_val or lancamento_val == 'Total':
                        continue
                    try:
                        lancamentos.append({
                            'credor': row[idx['Credor']].replace('\n', ' ').strip(),
                            'cd_cred': row[idx['Cd. cred.']],
                            'documento': row[idx['Documento']],
                            'lancamento': lancamento_val.split('/')[0],
                            'data_pagto': row[idx['Dt. pagto.']],
                            'liquido': _parse_valor(row[idx['Líquido']]),
                        })
                    except (ValueError, KeyError, TypeError):
                        pass
    return lancamentos


def parse_comprovantes(directory):
    """Return list of dicts parsed from filenames in COMPROVANTES_SEPARADOS/.

    Detects the optional _XDE Y suffix added when multiple pages share the
    same (valor, nome), e.g. CONCRECON_..._1DE2 and CONCRECON_..._2DE2.
    """
    comprovantes = []
    for f in sorted(directory.glob('COMPROVANTE-*.pdf')):
        m = re.match(r'COMPROVANTE-(\d{8})-([\d,]+)-(.+)\.pdf', f.name)
        if not m:
            continue
        data, valor_str, nome_raw = m.group(1), m.group(2), m.group(3)
        suffix = re.search(r'_(\d+)DE(\d+)$', nome_raw)
        if suffix:
            idx   = int(suffix.group(1))
            total = int(suffix.group(2))
            nome_base = nome_raw[:suffix.start()]
        else:
            idx, total, nome_base = 1, 1, nome_raw
        comprovantes.append({
            'filename':  f.name,
            'data':      data,
            'valor':     float(valor_str.replace(',', '.')),
            'nome':      nome_raw,
            'nome_base': nome_base,
            'idx':       idx,
            'total':     total,
        })
    return comprovantes


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _name_score(nome_comp, credor_sienge):
    """Token overlap score between comprovante name and SIENGE credor."""
    a = set(_sanitize(nome_comp).split('_'))
    b = set(_sanitize(credor_sienge).split('_'))
    if not a or not b:
        return 0
    return len(a & b) / len(a | b)


def match(lancamentos, comprovantes):
    """Match comprovantes -> lançamentos by valor líquido, with positional
    matching when multiple files share the same (valor, nome_base).

    Files with suffix _XDE Y are grouped and matched positionally against the
    SIENGE lançamentos that share the same valor, in report order.  A single
    file without suffix falls back to name-similarity tiebreaking.
    """
    # SIENGE lançamentos indexed by valor, preserving report order
    by_valor = {}
    for l in lancamentos:
        by_valor.setdefault(l['liquido'], []).append(l)

    # Group comprovantes by (valor, nome_base), sorted by position index
    groups = {}
    for c in comprovantes:
        key = (c['valor'], c['nome_base'])
        groups.setdefault(key, []).append(c)
    for key in groups:
        groups[key].sort(key=lambda c: c['idx'])

    matched    = {}   # filename -> [lançamento dict]
    unmatched_c = []

    for (valor, nome_base), group in groups.items():
        candidates = by_valor.get(valor, [])
        n_comp = len(group)
        n_sien = len(candidates)

        if n_sien == 0:
            unmatched_c.extend(group)

        elif n_comp == n_sien:
            # Counts match: positional assignment (1st file -> 1st lançamento…)
            for c, l in zip(group, candidates):
                matched[c['filename']] = [l]

        elif n_comp == 1 and n_sien > 1:
            # Single comprovante, multiple SIENGE entries: name tiebreaker
            scored = sorted(candidates,
                            key=lambda l: _name_score(nome_base, l['credor']),
                            reverse=True)
            best_score   = _name_score(nome_base, scored[0]['credor'])
            second_score = _name_score(nome_base, scored[1]['credor'])
            if best_score > second_score:
                matched[group[0]['filename']] = [scored[0]]
            else:
                # Indistinguishable — attach to all
                matched[group[0]['filename']] = candidates

        else:
            # Count mismatch (data problem): match as many as possible
            for c, l in zip(group, candidates):
                matched[c['filename']] = [l]
            for c in group[n_sien:]:
                unmatched_c.append(c)

    matched_ids = {l['lancamento'] for cands in matched.values() for l in cands}
    unmatched_l = [l for l in lancamentos if l['lancamento'] not in matched_ids]

    return matched, unmatched_c, unmatched_l


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(matched, unmatched_c, unmatched_l):
    def fmt_valor(v):
        return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    multi = {f: cands for f, cands in matched.items() if len(cands) > 1}
    single = {f: cands for f, cands in matched.items() if len(cands) == 1}

    print(f"\n{'='*70}")
    print(f"  MATCHES 1:1 ({len(single)})")
    print('='*70)
    for fname, cands in sorted(single.items()):
        l = cands[0]
        print(f"  {fname}")
        print(f"    -> {l['lancamento']} | {l['credor']} | {fmt_valor(l['liquido'])}")

    if multi:
        print(f"\n{'='*70}")
        print(f"  MATCHES 1:N — comprovante anexado em todos ({len(multi)})")
        print('='*70)
        for fname, cands in multi.items():
            print(f"  {fname} | {fmt_valor(cands[0]['liquido'])}")
            for l in cands:
                print(f"    -> {l['lancamento']} | {l['credor']} | {l['documento']}")

    if unmatched_c:
        print(f"\n{'='*70}")
        print(f"  COMPROVANTES SEM MATCH NO SIENGE ({len(unmatched_c)})")
        print('='*70)
        for c in unmatched_c:
            print(f"  {c['filename']} | {fmt_valor(c['valor'])}")

    if unmatched_l:
        print(f"\n{'='*70}")
        print(f"  LANÇAMENTOS SIENGE SEM COMPROVANTE ({len(unmatched_l)})")
        print('='*70)
        for l in unmatched_l:
            print(f"  {l['lancamento']} | {l['credor']} | {fmt_valor(l['liquido'])}")

    print(f"\n{'='*70}")
    total_pairs = sum(len(c) for c in matched.values())
    print(f"  Comprovantes: {len(matched)}  |  Pares (comprovante->lançamento): {total_pairs}  |  "
          f"Sem match: {len(unmatched_c)}")
    print('='*70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-lote', default=DATA_LOTE, help='Data no formato DDMMAAAA')
    parser.add_argument('--data-pasta', default=DATA_PASTA, help='Data no formato AAAAMMDD')
    args = parser.parse_args()

    data_lote = args.data_lote
    data_pasta = args.data_pasta

    comprovantes_dir = BASE_DIR / 'COMPROVANTES_SEPARADOS' / f'COMPROVANTES_SEP_{data_pasta}'
    relatorio_pdf = (BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{data_pasta}'
                     / f'RELATORIO_CONTAS_PAGAS_{data_lote}.pdf')
    output_json = (BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{data_pasta}'
                   / f'LANCAMENTOS_MATCHED_{data_lote}.json')

    print(f"[1] Lendo relatório: {relatorio_pdf.name}")
    lancamentos = parse_relatorio(relatorio_pdf)
    print(f"    {len(lancamentos)} lançamentos extraídos")

    print(f"[2] Lendo comprovantes: {comprovantes_dir.name}/")
    comprovantes = parse_comprovantes(comprovantes_dir)
    print(f"    {len(comprovantes)} comprovantes encontrados")

    print("[3] Cruzando por valor líquido...")
    matched, unmatched_c, unmatched_l = match(lancamentos, comprovantes)

    print_report(matched, unmatched_c, unmatched_l)

    pairs = [
        {'comprovante': fname, 'lancamento': l['lancamento']}
        for fname, cands in matched.items()
        for l in cands
    ]
    result = {
        'pairs': pairs,
        'unmatched_comprovantes': [c['filename'] for c in unmatched_c],
        'unmatched_lancamentos': [
            {'lancamento': l['lancamento'], 'credor': l['credor'], 'liquido': l['liquido']}
            for l in unmatched_l
        ],
    }
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[4] Resultado salvo em: {output_json.name}")

    return result


if __name__ == '__main__':
    main()
