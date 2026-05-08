#!/usr/bin/env python3
"""Interface gráfica QuickAttach — anexo de comprovantes no SIENGE."""

import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

SCRIPTS_DIR = Path(__file__).parent          # onde estão os .py
BASE_DIR    = Path.home() / 'QuickAttach'   # pasta de dados do usuário
PYTHON = sys.executable

_log_q: queue.Queue = queue.Queue()
_pix_path: str = ''
_bol_path: str = ''

# Widget refs (preenchidos por build_ui)
root: tk.Tk = None
btn_subir: ttk.Button = None
btn_relatorio: ttk.Button = None
btn_anexar: ttk.Button = None
date_entry: ttk.Entry = None
empresa_entry: ttk.Entry = None
pix_label: ttk.Label = None
bol_label: ttk.Label = None
log_text: scrolledtext.ScrolledText = None
status_var: tk.StringVar = None


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def ensure_dirs() -> None:
    for sub in ('', 'COMPROVANTES', 'COMPROVANTES_SEPARADOS', 'RELATORIO_CONTAS_PAGAS'):
        (BASE_DIR / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(s: str):
    """'20/04/2026' → ('20042026', '20260420') ou (None, None) se inválida."""
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', s.strip())
    if not m:
        return None, None
    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
    return dd + mm + yyyy, yyyy + mm + dd


def _apply_state(state: int) -> None:
    """Aplica o estado do pipeline aos botões de ação.

    0 — inicial / após anexação : Subir=ON  Emitir=OFF Anexar=OFF
    1 — após upload              : Subir=OFF Emitir=ON  Anexar=OFF
    2 — após relatório           : Subir=OFF Emitir=OFF Anexar=ON
    """
    configs = {
        0: ('normal',   'disabled', 'disabled'),
        1: ('disabled', 'normal',   'disabled'),
        2: ('disabled', 'disabled', 'normal'),
    }
    s, r, a = configs.get(state, configs[0])
    if btn_subir:     btn_subir.configure(state=s)
    if btn_relatorio: btn_relatorio.configure(state=r)
    if btn_anexar:    btn_anexar.configure(state=a)


def _disable_all() -> None:
    for btn in (btn_subir, btn_relatorio, btn_anexar):
        if btn:
            btn.configure(state='disabled')


def _append_log(text: str) -> None:
    log_text.configure(state='normal')
    log_text.insert('end', text + '\n')
    log_text.see('end')
    log_text.configure(state='disabled')


def _poll_queue() -> None:
    try:
        while True:
            item = _log_q.get_nowait()
            if isinstance(item, tuple) and item[0] == 'DONE':
                rc, callback = item[1], item[2]
                status_var.set('Concluído.' if rc == 0 else f'Erro (código {rc}).')
                if callback:
                    callback(rc)
            else:
                _append_log(str(item))
    except queue.Empty:
        pass
    root.after(100, _poll_queue)


def clear_log() -> None:
    log_text.configure(state='normal')
    log_text.delete('1.0', 'end')
    log_text.configure(state='disabled')
    status_var.set('Pronto.')


def _run_chain(steps: list[list], label: str, on_complete=None) -> None:
    """Executa uma lista de comandos sequencialmente numa thread em background.

    Posta linhas de saída no _log_q. Ao final, posta ('DONE', returncode, on_complete).
    """
    _disable_all()
    status_var.set(f'Executando: {label}…')

    def _worker() -> None:
        final_rc = 0
        for i, cmd in enumerate(steps):
            display = ' '.join(os.path.basename(c) if (os.sep in c and c.endswith('.py')) else c
                               for c in cmd)
            _log_q.put(f'\n>>> {display}\n')
            env = os.environ.copy()
            env['PYTHONUTF8'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                cwd=str(SCRIPTS_DIR),
                env=env,
            )
            for line in proc.stdout:
                _log_q.put(line.rstrip())
            proc.wait()
            final_rc = proc.returncode
            if final_rc != 0:
                _log_q.put(f'\n[ERRO no passo {i + 1} — código {final_rc}]')
                break
        _log_q.put(('DONE', final_rc, on_complete))

    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Acções dos botões
# ---------------------------------------------------------------------------

def select_pdf(tipo: str) -> None:
    global _pix_path, _bol_path
    path = filedialog.askopenfilename(
        title=f'Selecionar comprovante {tipo}',
        filetypes=[('PDF', '*.pdf'), ('Todos os ficheiros', '*.*')],
        initialdir=str(BASE_DIR),
    )
    if not path:
        return
    basename = os.path.basename(path)
    if tipo == 'PIX':
        _pix_path = path
        pix_label.configure(text=basename, foreground='#2c3e50')
    else:
        _bol_path = path
        bol_label.configure(text=basename, foreground='#2c3e50')
    # Auto-preenche data a partir do nome do arquivo (DDMMAAAA)
    m = re.search(r'(\d{8})', basename)
    if m:
        raw = m.group(1)
        dd, mm, yyyy = raw[:2], raw[2:4], raw[4:]
        date_entry.delete(0, 'end')
        date_entry.insert(0, f'{dd}/{mm}/{yyyy}')


def subir_comprovantes() -> None:
    date_str = date_entry.get().strip()
    data_lote, data_pasta = _parse_date(date_str)
    if not data_lote:
        messagebox.showerror('Data inválida', 'Use o formato DD/MM/AAAA  (ex: 20/04/2026).')
        return
    if not _pix_path and not _bol_path:
        messagebox.showerror('Sem arquivo', 'Selecione pelo menos um PDF (PIX ou BOL).')
        return

    cmd = [PYTHON, str(SCRIPTS_DIR / 'split_comprovantes.py'),
           '--data-lote', data_lote, '--data-pasta', data_pasta]
    if _pix_path:
        cmd += ['--pix', _pix_path]
    if _bol_path:
        cmd += ['--bol', _bol_path]

    _append_log(f'=== Subir Comprovantes — {date_str} ===')
    _run_chain([cmd], 'Subir Comprovantes',
               on_complete=lambda rc: _apply_state(1 if rc == 0 else 0))


def emitir_relatorio() -> None:
    date_str = date_entry.get().strip()
    data_lote, data_pasta = _parse_date(date_str)
    if not data_lote:
        messagebox.showerror('Data inválida', 'Use o formato DD/MM/AAAA  (ex: 20/04/2026).')
        return
    empresa = empresa_entry.get().strip() or '12'

    cmd_rel = [
        PYTHON, str(SCRIPTS_DIR / 'sienge_relatorio.py'),
        '--data-inicio', date_str,
        '--data-fim', date_str,
        '--empresa', empresa,
        '--data-pasta', data_pasta,
    ]
    cmd_ext = [
        PYTHON, str(SCRIPTS_DIR / 'extrair_lancamentos.py'),
        '--data-lote', data_lote,
        '--data-pasta', data_pasta,
    ]

    _append_log(f'=== Emitir Relatório + Matching — {date_str} ===')
    _run_chain([cmd_rel, cmd_ext], 'Emitir Relatório',
               on_complete=lambda rc: _apply_state(2 if rc == 0 else 1))


def anexar_comprovantes() -> None:
    date_str = date_entry.get().strip()
    data_lote, data_pasta = _parse_date(date_str)
    if not data_lote:
        messagebox.showerror('Data inválida', 'Use o formato DD/MM/AAAA  (ex: 20/04/2026).')
        return

    cmd = [
        PYTHON, str(SCRIPTS_DIR / 'sienge_anexar.py'),
        '--data-lote', data_lote,
        '--data-pasta', data_pasta,
    ]

    _append_log(f'=== Anexar Comprovantes — {date_str} ===')
    _run_chain([cmd], 'Anexar Comprovantes',
               on_complete=lambda rc: _apply_state(0))


# ---------------------------------------------------------------------------
# Construção da interface
# ---------------------------------------------------------------------------

def build_ui() -> tk.Tk:
    global root, btn_subir, btn_relatorio, btn_anexar
    global date_entry, empresa_entry, pix_label, bol_label
    global log_text, status_var

    root = tk.Tk()
    root.title('QuickAttach — Condomínio Solar Sinatra')
    root.geometry('880x700')
    root.resizable(True, True)
    root.configure(bg='#ecf0f1')

    style = ttk.Style()
    style.theme_use('clam')
    style.configure('TLabelframe', background='#ecf0f1')
    style.configure('TLabelframe.Label', background='#ecf0f1', font=('Helvetica', 9, 'bold'))
    style.configure('TFrame', background='#ecf0f1')
    style.configure('TLabel', background='#ecf0f1')
    style.configure('TButton', font=('Helvetica', 9))
    style.configure('Action.TButton', font=('Helvetica', 10, 'bold'), padding=6)

    status_var = tk.StringVar(value='Pronto.')

    # ── Cabeçalho ────────────────────────────────────────────────────────────
    hdr = ttk.Frame(root, padding='12 10 12 6')
    hdr.pack(fill='x')
    ttk.Label(hdr, text='QuickAttach', font=('Helvetica', 17, 'bold'),
              foreground='#2c3e50').pack(side='left')
    ttk.Label(hdr, text='— Condomínio Fechado Solar Sinatra',
              font=('Helvetica', 11), foreground='#7f8c8d').pack(side='left', padx=8)
    ttk.Separator(root, orient='horizontal').pack(fill='x', padx=12)

    # ── Configuração do lote ─────────────────────────────────────────────────
    cfg = ttk.LabelFrame(root, text='Configuração do Lote', padding='10 6')
    cfg.pack(fill='x', padx=12, pady=8)

    ttk.Label(cfg, text='Data do lote (DD/MM/AAAA):').grid(row=0, column=0, sticky='w', padx=4)
    date_entry = ttk.Entry(cfg, width=14, font=('Helvetica', 10))
    date_entry.insert(0, '20/04/2026')
    date_entry.grid(row=0, column=1, padx=4)

    ttk.Label(cfg, text='Empresa (código):').grid(row=0, column=2, sticky='w', padx=(20, 4))
    empresa_entry = ttk.Entry(cfg, width=8, font=('Helvetica', 10))
    empresa_entry.insert(0, '12')
    empresa_entry.grid(row=0, column=3, padx=4)

    # ── Área em duas colunas ─────────────────────────────────────────────────
    cols = ttk.Frame(root, padding='8 0')
    cols.pack(fill='x', padx=12, pady=4)
    cols.columnconfigure(0, weight=1)
    cols.columnconfigure(1, weight=1)

    # ── Coluna 1: Subir Comprovantes ─────────────────────────────────────────
    cf = ttk.LabelFrame(cols, text='1. Subir Comprovantes', padding='10 8')
    cf.grid(row=0, column=0, sticky='nsew', padx=(0, 6))

    ttk.Label(
        cf,
        text='⚠  Selecione apenas arquivos de uma única\n'
             '    data (ex: 20/04/2026).',
        foreground='#c0392b', justify='left', font=('Helvetica', 9),
    ).pack(anchor='w', pady=(0, 10))

    for tipo in ('PIX', 'BOL'):
        row = ttk.Frame(cf)
        row.pack(fill='x', pady=3)
        ttk.Label(row, text=f'{tipo}:', width=4, font=('Helvetica', 9, 'bold')).pack(side='left')
        lbl = ttk.Label(row, text='— não selecionado —', foreground='#95a5a6',
                        width=27, anchor='w', font=('Helvetica', 9))
        lbl.pack(side='left', padx=4)
        ttk.Button(row, text='Selecionar…', width=11,
                   command=lambda t=tipo: select_pdf(t)).pack(side='left')
        if tipo == 'PIX':
            pix_label = lbl
        else:
            bol_label = lbl

    btn_subir = ttk.Button(cf, text='Subir Comprovantes', style='Action.TButton',
                           command=subir_comprovantes)
    btn_subir.pack(pady=(12, 2), fill='x')

    # ── Coluna 2: Relatório de Contas Pagas ──────────────────────────────────
    rf = ttk.LabelFrame(cols, text='2. Relatório de Contas Pagas', padding='10 8')
    rf.grid(row=0, column=1, sticky='nsew')

    ttk.Label(
        rf,
        text='Acessa o SIENGE, gera o relatório\n'
             '"Contas Pagas" (PDF) e cria\n'
             'automaticamente o arquivo de\n'
             'matching (JSON) para o lote.',
        foreground='#555', justify='left', font=('Helvetica', 9),
    ).pack(anchor='w', pady=(0, 14))

    btn_relatorio = ttk.Button(rf, text='Emitir Relatório', style='Action.TButton',
                               command=emitir_relatorio)
    btn_relatorio.pack(fill='x')

    # ── Upload SIENGE ────────────────────────────────────────────────────────
    uf = ttk.LabelFrame(root, text='3. Upload SIENGE', padding='10 8')
    uf.pack(fill='x', padx=12, pady=4)

    ttk.Label(
        uf,
        text='Navega até cada lançamento no SIENGE e faz o upload do comprovante correspondente na aba Anexos.',
        foreground='#555', font=('Helvetica', 9),
    ).pack(anchor='w', pady=(0, 8))

    btn_anexar = ttk.Button(uf, text='Anexar Comprovantes ao SIENGE', style='Action.TButton',
                            command=anexar_comprovantes)
    btn_anexar.pack(anchor='w')

    # ── Log de execução ──────────────────────────────────────────────────────
    lf = ttk.LabelFrame(root, text='Log de execução', padding='6')
    lf.pack(fill='both', expand=True, padx=12, pady=(4, 10))

    lhdr = ttk.Frame(lf)
    lhdr.pack(fill='x', pady=(0, 4))
    ttk.Label(lhdr, textvariable=status_var, foreground='#2980b9',
              font=('Helvetica', 9, 'italic')).pack(side='left')
    ttk.Button(lhdr, text='Limpar', command=clear_log, width=8).pack(side='right')

    log_text = scrolledtext.ScrolledText(
        lf, state='disabled', font=('Courier', 9),
        bg='#1e1e1e', fg='#d4d4d4', wrap='none',
        insertbackground='white', relief='flat',
    )
    log_text.pack(fill='both', expand=True)

    ttk.Separator(root).pack(fill='x')
    ttk.Label(root, text='QuickAttach v1.0', font=('Helvetica', 8),
              foreground='#aaa').pack(side='right', padx=10, pady=3)

    _apply_state(0)
    root.after(100, _poll_queue)
    return root


if __name__ == '__main__':
    ensure_dirs()
    build_ui()
    root.mainloop()
