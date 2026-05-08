# QuickAttach

A desktop automation tool that processes batch payment receipts exported from **Santander Internet Banking Empresarial** and uploads them as attachments to their corresponding entries in **SIENGE** — an ERP (Enterprise Resource Planning) platform widely used in Brazilian civil construction.

## Overview

In civil construction projects, dozens of payments are made every month to suppliers, subcontractors, and service providers. Each payment generates a receipt (*comprovante de pagamento*) that must be manually attached to its corresponding financial entry in SIENGE for audit and accounting purposes.

QuickAttach automates the entire workflow end-to-end:

1. **Split** — Takes multi-page PIX and boleto receipt PDFs from Santander and splits them into individual files with standardized names.
2. **Report** — Logs into SIENGE, generates the *Contas Pagas* (Paid Accounts) report for the given period, and downloads it as a PDF.
3. **Match** — Parses the SIENGE report and matches each receipt file to its corresponding financial entry (*lançamento*) using the net payment value, with name-similarity disambiguation for duplicates.
4. **Attach** — Navigates to each matched entry in SIENGE and uploads the receipt as an attachment.

## Requirements

- Python 3.8+
- Linux or Windows

## Installation

Run the setup script from the project folder:

```bash
# Linux
bash instalar.sh

# Windows (double-click or run from cmd)
instalar.bat
```

This installs all Python dependencies, downloads the Playwright Chromium browser, and creates a desktop shortcut.

To install manually:

```bash
pip3 install pymupdf playwright requests pdfplumber
python3 -m playwright install chromium
```

## Configuration

Create a `sienge_credentials.json` file in the project folder with your SIENGE login:

```json
{
  "login": "your_username",
  "senha": "your_password"
}
```

> **Never commit this file to version control.** It is listed in `.gitignore`.

## Running

### GUI (recommended)

```bash
python3 app.py        # Linux
pythonw app.py        # Windows
```

The GUI guides you through the three steps sequentially. Enter the batch date (DD/MM/YYYY) and the SIENGE company code, then run each step in order.

### CLI

Each pipeline stage can also be run independently:

```bash
python3 split_comprovantes.py  --pix PATH --bol PATH --data-lote DDMMAAAA --data-pasta AAAAMMDD
python3 sienge_relatorio.py    --data-inicio DD/MM/AAAA --data-fim DD/MM/AAAA --empresa CD --data-pasta AAAAMMDD
python3 extrair_lancamentos.py --data-lote DDMMAAAA --data-pasta AAAAMMDD
python3 sienge_anexar.py       --data-lote DDMMAAAA --data-pasta AAAAMMDD
```

## Data folder structure

QuickAttach stores all files under `~/QuickAttach/`:

```
~/QuickAttach/
├── COMPROVANTES/
│   └── COMPROVANTES_{AAAAMMDD}/          # source PDFs from Santander
│       ├── COMPROVANTE {DDMMAAAA} PIX.pdf
│       └── COMPROVANTE {DDMMAAAA} BOL.pdf
│
├── COMPROVANTES_SEPARADOS/
│   └── COMPROVANTES_SEP_{AAAAMMDD}/      # one PDF per receipt
│       └── COMPROVANTE-{DDMMAAAA}-{VALOR}-{NOME}.pdf
│
└── RELATORIO_CONTAS_PAGAS/
    └── RELATORIO_CONTAS_{AAAAMMDD}/      # SIENGE report + matching results
        ├── RELATORIO_CONTAS_PAGAS_{DDMMAAAA}.pdf
        └── LANCAMENTOS_MATCHED_{DDMMAAAA}.json
```

Date format conventions:
- `DDMMAAAA` — used in filenames (e.g. `08052026`)
- `AAAAMMDD` — used in folder names (e.g. `20260508`)

## Tech stack

| Dependency | Purpose |
|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) | PDF splitting and text extraction |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | Structured table extraction from SIENGE report |
| [Playwright](https://playwright.dev/python/) | Browser automation for SIENGE (Chromium) |
| [requests](https://docs.python-requests.org/) | Downloading report PDFs via authenticated session |
| tkinter | Cross-platform desktop GUI (Python built-in) |

## License

MIT
