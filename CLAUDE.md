# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git & GitHub workflow

The canonical remote is `origin` (GitHub). Branch is `master`.

**IMPORTANT: After completing ANY code change — without waiting for the user to ask — always run:**

```bash
git add <changed files>
git commit -m "concise description"
git push origin master
```

Do this automatically at the end of every task. Never leave changes uncommitted or unpushed.

`sienge_credentials.json` is in `.gitignore` and must never be committed.

## Installation & setup

```bash
# Linux
bash instalar.sh

# Windows (double-click or run from cmd)
instalar.bat
```

Both scripts install pip dependencies, download Playwright Chromium, and create a desktop shortcut with the `quickattach.ico` icon. The `.ico` file must be present in the project root — it is copied to `%USERPROFILE%\QuickAttach\` during installation.

Manual install:
```bash
pip3 install pymupdf playwright requests pdfplumber
python3 -m playwright install chromium
```

**Credentials file** — create `sienge_credentials.json` in the project folder (preserved across reinstalls):
```json
{ "login": "your_username", "senha": "your_password" }
```

## Running

```bash
# Primary entry point — opens the GUI
python3 app.py        # Linux
pythonw app.py        # Windows (no console window)

# Run individual pipeline stages via CLI
python3 split_comprovantes.py  --pix PATH --bol PATH --data-lote DDMMAAAA --data-pasta AAAAMMDD
python3 sienge_relatorio.py    --data-inicio DD/MM/AAAA --data-fim DD/MM/AAAA --empresa CD --data-pasta AAAAMMDD
python3 extrair_lancamentos.py --data-lote DDMMAAAA --data-pasta AAAAMMDD
python3 sienge_anexar.py       --data-lote DDMMAAAA --data-pasta AAAAMMDD
```

All scripts fall back to hardcoded defaults (`20042026` / `20260420`) when run without arguments.

When running scripts directly on Windows (not via app.py), launch with `python -u` and redirect output to a log file to avoid buffering. The app.py subprocess launcher already sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`.

---

## Purpose

Automates processing of batch payment receipts (*comprovantes de pagamento*) exported from Santander Internet Banking Empresarial for **Condomínio Fechado Solar Sinatra**:

1. Split multi-page PIX + BOL PDFs into individual files with standardized names
2. Log into SIENGE, generate the "Contas Pagas" report PDF
3. Match each receipt to its SIENGE lançamento → JSON file
4. Navigate to each lançamento in SIENGE, open the Anexos tab, and upload the matching receipt

---

## Folder structure (per batch)

Date formats used across the project:
- **DDMMAAAA** — used in filenames (e.g. `14042026`)
- **AAAAMMDD** — used in folder names (e.g. `20260414`)

```
~/QuickAttach/                            <- BASE_DIR (user data)
├── COMPROVANTES/
│   └── COMPROVANTES_{AAAAMMDD}/         <- source PDFs from Santander
│       ├── COMPROVANTE {DDMMAAAA} PIX.pdf
│       └── COMPROVANTE {DDMMAAAA} BOL.pdf
├── COMPROVANTES_SEPARADOS/
│   └── COMPROVANTES_SEP_{AAAAMMDD}/     <- one PDF per comprovante
└── RELATORIO_CONTAS_PAGAS/
    └── RELATORIO_CONTAS_{AAAAMMDD}/     <- SIENGE report + matching JSON
        ├── RELATORIO_CONTAS_PAGAS_{DDMMAAAA}.pdf
        └── LANCAMENTOS_MATCHED_{DDMMAAAA}.json
```

`SCRIPTS_DIR` (`Path(__file__).parent`) and `BASE_DIR` (`Path.home() / 'QuickAttach'`) are separate constants. When the repo is cloned directly to `~/QuickAttach/`, they point to the same directory.

---

## app.py — Interface gráfica

**Framework:** tkinter (built-in). Invokes scripts as subprocesses (`subprocess.Popen`), captures stdout/stderr line-by-line via `queue.Queue` + `root.after(100)`, displays in log widget.

**Three-step state machine (0→1→2→0):**
1. **Subir Comprovantes** (state 0) → `split_comprovantes.py`; on success enables only "Emitir Relatório"
2. **Emitir Relatório** (state 1) → `sienge_relatorio.py` + `extrair_lancamentos.py` in sequence; on success enables only "Anexar Comprovantes"
3. **Anexar Comprovantes ao SIENGE** (state 2) → `sienge_anexar.py`; on success resets to state 0

The batch date field defaults to today's date (`date.today()`) and is overwritten automatically when the user selects a PDF whose filename contains an 8-digit date (DDMMAAAA).

---

## Etapa 1: Divisão e renomeação de comprovantes

**Script:** `split_comprovantes.py` | **PDF library:** PyMuPDF (text extraction + page splitting)

File naming convention: `COMPROVANTE-{DDMMAAAA}-{VALOR}-{NOME_FANTASIA}.pdf`
- Value: `1608,85` — no `R$`, no thousands separator, comma as decimal
- Name: uppercase, spaces → underscores, accents removed
- Duplicates: `_1DE2`, `_2DE2` suffix when multiple pages share (valor, nome)

Parsing by type:
- **PIX**: value after `Valor\nR$ `; name between `Para\n` and `\nChave\n`
- **BOL**: value after `Valor total pago:\nR$\xa0`; name from last `Nome Fantasia:` before `Dados do Pagador` (prefers Sacador Avalista); fallback to first `Razão Social:`

---

## Etapa 2: Relatório SIENGE

**Script:** `sienge_relatorio.py` | **Credentials:** `sienge_credentials.json` (`login`, `senha`)

### Key selectors (inside iframe `iFramePage`)

| Campo | Seletor |
|---|---|
| Empresa (código) | `#entity\.empresa\.cdEmpresaView` + Tab |
| Data início/fim | `entity.dtPagtoInicio` / `entity.dtPagtoFim` — JS masked input |
| Ordenação | `#tpOrdenacao` |
| Processar parcelas | `#flTodasC` |
| Lupa Tipo de Baixa | `#tipoBaixaCPG img[src*="botProcurar.png"]:first-of-type` |
| Botão Visualizar | `input[value="Visualizar"]` → nova aba |

`select_tipo_baixa()` clicks the Tipo de Baixa lupa, waits for the `spjGenericSearch.do` overlay iframe, and selects **both** "Baixa" and "Antecipação" checkboxes before confirming. Both types must be selected to capture all paid entries.

---

## Etapa 3: Extração e matching de lançamentos

**Script:** `extrair_lancamentos.py` | **PDF library:** pdfplumber (structured table extraction from SIENGE report)

Primary match key: `liquido` value. Disambiguation when multiple SIENGE entries share the same value:
- **Positional** — when `_XDE Y` suffix count equals SIENGE entry count, paired in report order
- **Name similarity** — Jaccard token-overlap score between sanitized comprovante name and `credor`
- **Attach to all** — when best and second-best name scores are tied

JSON output:
```json
{
  "pairs": [{"comprovante": "COMPROVANTE-....pdf", "lancamento": "71416"}],
  "unmatched_comprovantes": [],
  "unmatched_lancamentos": [{"lancamento": "71416", "credor": "...", "liquido": 4125.0}]
}
```

`lancamento` stores only the numeric part before `/`.

---

## Etapas 4–5: Navegação e upload de comprovantes

**Script:** `sienge_anexar.py`

For each pair in `LANCAMENTOS_MATCHED_{DATA_LOTE}.json`:
1. Navigate to Títulos SPA via direct URL
2. Fill "Título" → CONSULTAR → Editar
3. Wait for iFramePage of Cadastro de Títulos (content-based detection)
4. Aba Anexos → ADICIONAR → upload in **last row** of grid → SALVAR

**Idempotency:** `_already_attached()` checks whether a file with the same name is already present in the Anexos grid before uploading. Re-running `sienge_anexar.py` on a partially completed batch is safe — already-attached files are skipped.

### Confirmed selectors

| Elemento | Seletor | Contexto |
|---|---|---|
| Campo Título | `label:has-text("Título")` → `for` → `#{id}` | SPA (`page`) |
| Botão CONSULTAR | `#button-consultar-titulos-a-pagar` | SPA (`page`) |
| Botão Editar | `button[aria-label="Editar"]` | SPA (`page`) |
| Aba Anexos | `a:has-text("Anexos")` | iFramePage |
| Botão ADICIONAR | `input[value="Adicionar"]` | iFramePage |
| File input nova linha | `tr:has(input[type="file"])` → last → `input[type="file"]` | iFramePage |
| Descrição nova linha | `tr:has(input[type="file"])` → last → `input[type="text"]:not([readonly])` | iFramePage |
| Botão SALVAR | `#btSalvar` with `force=True` + `scrollIntoView` | iFramePage |

---

## Arquitetura do SIENGE no Playwright — lições aprendidas

### Estrutura de frames

| Frame | Identificador | Uso |
|---|---|---|
| Página principal | SPA React/MUI | sidebar, Consulta de Títulos |
| Formulário clássico | `iframe[name="iFramePage"]` em `/sienge/CPG/...` | relatório, Cadastro de Títulos, Anexos |
| Overlay de busca | URL contendo `spjGenericSearch.do` | resultados de lupas IS_request |

### Login e detecção pós-MFA

After credentials are submitted, SIENGE may require MFA. The redirect back to the application **stays in the same Playwright page** (it does NOT open a new tab or context). The correct detection pattern:

```python
page.wait_for_url(
    lambda url: (
        'escolengenharia.sienge.com.br' in url and
        'login.sienge.com.br' not in url
    ),
    timeout=600000,
)
```

The post-login URL is `https://escolengenharia.sienge.com.br/sienge/index.jsp` (not `index.html`). Do NOT poll `page.url` in a loop or scan `page.context.pages` — the redirect happens in the original tab.

`login_sienge()` returns `page` so the caller can do `page = login_sienge(page, login, senha)`.

### Detecção do iFramePage

The iframe for the Contas Pagas form loads asynchronously after menu navigation. Use a polling loop (up to 30s) checking multiple identifiers, not a fixed sleep:

```python
frame = None
for _ in range(60):
    frame = page.frame(name='iFramePage')
    if not frame:
        frame = page.frame(url='*filterContaPagas*')
    if not frame:
        for f in page.frames:
            if f.is_detached(): continue
            try:
                u = f.url or ''
                if any(k in u for k in ('ContaPagas', 'filterContaPagas', 'CPG')):
                    frame = f; break
            except Exception: pass
    if frame: break
    time.sleep(0.5)
```

For the Cadastro de Títulos iframe (in `sienge_anexar.py`), detect by body content:
```python
body = f.inner_text('body')
if 'Cadastro' in body and 'Parcelas' in body:
    return f
```

### Masked inputs

Date and code fields reject `fill()` and `type()`. Use JS native value setter:
```python
frame.evaluate(f'''
    var el = document.getElementById("{field_id}");
    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, "{value}");
    el.dispatchEvent(new Event('input', {{bubbles: true}}));
    el.dispatchEvent(new Event('change', {{bubbles: true}}));
    el.dispatchEvent(new Event('blur', {{bubbles: true}}));
''')
```
Read current value via `frame.evaluate('document.getElementById("id").value')` — never `get_attribute('value')`.

### Padrão IS_request / lupas

1. Click lupa inside the form frame
2. Overlay loads in a **new iframe** on the main page (not a new window) — identify by URL (`spjGenericSearch.do`)
3. Interact with checkboxes → confirm with `input[value="Selecionar"]`

### Notificações push

```python
for sel in ['button:has-text("NÃO, OBRIGADO")', 'button:has-text("Fechar")', '[data-dismiss="modal"]']:
    el = page.query_selector(sel)
    if el and el.is_visible():
        el.click()
```

### Download de relatório PDF

After "Visualizar", a new tab opens `please_wait_frame.jsp?url=/sienge/viewReportSPW.do?...`. Capture the URL via a `response` event listener and download with `requests` + cookies from the Playwright context.

### Arquitetura híbrida SPA + JSP

- **JSP (clássico):** `sienge_relatorio.py` — content in `iFramePage`, masked inputs, IS_request lookups
- **SPA (React/MUI):** `sienge_anexar.py` — content directly in `page`, MUI inputs without `placeholder`

`page.content()` returns only the outer HTML shell — use `frame.content()` to inspect iframes.

### Windows encoding

Avoid non-ASCII characters in `print()` statements. The Windows console uses cp1252 by default, which cannot encode characters like `→`. Use ASCII alternatives (e.g. `->`) in all user-facing output. The app.py subprocess launcher sets `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8`, but scripts run directly from the terminal do not have this guarantee.
