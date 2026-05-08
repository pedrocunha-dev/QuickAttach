# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git & GitHub workflow

The canonical remote is `origin` (GitHub). After every meaningful change — bug fix, new feature, refactor — commit and push to `origin main`:

```bash
git add <changed files>
git commit -m "concise description"
git push origin main
```

Never commit `sienge_credentials.json` (it is in `.gitignore`).  
Never force-push to `main` without explicit user confirmation.

## Installation & setup

First-time setup on any machine — run the appropriate script from the project folder:

```bash
# Linux
bash instalar.sh

# Windows (double-click or run from cmd)
instalar.bat
```

Both scripts: install pip dependencies, download Playwright Chromium, and create a desktop shortcut.

To install manually:
```bash
pip3 install pymupdf playwright requests pdfplumber
python3 -m playwright install chromium
```

## Running

```bash
# Primary entry point — opens the GUI
python3 app.py        # Linux
pythonw app.py        # Windows (no console window)

# Run individual pipeline stages via CLI
python3 split_comprovantes.py --pix PATH --bol PATH --data-lote DDMMAAAA --data-pasta AAAAMMDD
python3 sienge_relatorio.py   --data-inicio DD/MM/AAAA --data-fim DD/MM/AAAA --empresa CD --data-pasta AAAAMMDD
python3 extrair_lancamentos.py --data-lote DDMMAAAA --data-pasta AAAAMMDD
python3 sienge_anexar.py       --data-lote DDMMAAAA --data-pasta AAAAMMDD
```

All scripts fall back to hardcoded defaults when run without arguments (last processed batch: `20042026` / `20260420`).

---

## Purpose

Automates the processing of batch payment receipts (comprovantes de pagamento) exported from Santander Internet Banking Empresarial for **Condomínio Fechado Solar Sinatra**:

1. Split multi-page PDFs (PIX + BOL) into individual receipt files with standardized names
2. Log into SIENGE, generate the "Contas Pagas" report PDF
3. Match each receipt to its SIENGE lançamento → JSON file
4. Navigate to each lançamento in SIENGE, open the Anexos tab, and upload the matching receipt

---

## Folder structure (per batch)

Date formats used across the project:
- **DDMMAAAA** — used in filenames (e.g. `20042026`)
- **AAAAMMDD** — used in folder names (e.g. `20260420`)

```
COMPROVANTES/
└── COMPROVANTES_{AAAAMMDD}/          ← source PDFs from Santander
    ├── COMPROVANTE {DDMMAAAA} PIX.pdf
    └── COMPROVANTE {DDMMAAAA} BOL.pdf

COMPROVANTES_SEPARADOS/
└── COMPROVANTES_SEP_{AAAAMMDD}/      ← one PDF per comprovante
    └── COMPROVANTE-{DDMMAAAA}-{VALOR}-{NOME}.pdf

RELATORIO_CONTAS_PAGAS/
└── RELATORIO_CONTAS_{AAAAMMDD}/      ← SIENGE report + matching JSON
    ├── RELATORIO_CONTAS_PAGAS_{DDMMAAAA}.pdf
    └── LANCAMENTOS_MATCHED_{DDMMAAAA}.json
```

---

## app.py — Interface gráfica

**Framework:** tkinter (built-in)  
Invoca os scripts como subprocessos (`subprocess.Popen`), captura stdout/stderr linha a linha via `queue.Queue` + `root.after(100)` e exibe no log.

**Duas constantes de caminho:**
- `SCRIPTS_DIR = Path(__file__).parent` — pasta dos `.py`; usado como `cwd` nos subprocessos e para localizar os scripts
- `BASE_DIR = Path.home() / 'QuickAttach'` — pasta de dados do utilizador; criada automaticamente por `ensure_dirs()` na abertura

**`ensure_dirs()`** cria `~/QuickAttach/` e as subpastas `COMPROVANTES/`, `COMPROVANTES_SEPARADOS/`, `RELATORIO_CONTAS_PAGAS/` com `exist_ok=True`. Chamada antes de `build_ui()`.

**Campos de configuração:** Data do lote (DD/MM/AAAA) e Empresa (código). A data é auto-preenchida ao selecionar um PDF pelo nome do arquivo.

**Três ações com máquina de estados (0→1→2→0):**
1. **Subir Comprovantes** (estado 0) — seleciona PDFs PIX/BOL → `split_comprovantes.py`; ao concluir, habilita só "Emitir Relatório"
2. **Emitir Relatório** (estado 1) — `sienge_relatorio.py` + `extrair_lancamentos.py` em sequência; ao concluir, habilita só "Anexar Comprovantes"
3. **Anexar Comprovantes ao SIENGE** (estado 2) — `sienge_anexar.py`; ao concluir, volta ao estado 0

---

## Etapa 1: Divisão e renomeação de comprovantes

**Script:** `split_comprovantes.py`

Reads source PDFs, splits each page, saves to `COMPROVANTES_SEPARADOS/COMPROVANTES_SEP_{DATA_PASTA}/`.

### File naming convention

`COMPROVANTE-{DDMMAAAA}-{VALOR}-{NOME_FANTASIA}.pdf`

- **Value**: `1608,85` — no `R$`, no thousands separator, comma as decimal
- **Name**: uppercase, spaces → underscores, accents removed
- **Duplicates**: `_1DE2`, `_2DE2` suffix when multiple pages share the same (valor, nome)

### Parsing logic by type

**PIX**: value after `Valor\nR$ `; name between `Para\n` and `\nChave\n`

**BOL** (Santander "2ª via de Comprovante"):
- Value after `Valor total pago:\nR$\xa0`
- Name: **last** `Nome Fantasia:` before `Dados do Pagador` (prefers Sacador Avalista when present); fallback to first `Razão Social:`

---

## Etapa 2: Relatório SIENGE

**Script:** `sienge_relatorio.py`  
**Credentials:** `sienge_credentials.json` (`login`, `senha`)

Saves PDF to `RELATORIO_CONTAS_PAGAS/RELATORIO_CONTAS_{DATA_PASTA}/RELATORIO_CONTAS_PAGAS_{date_str}.pdf`.

### Key selectors (iframe `iFramePage`)

| Campo | Seletor |
|---|---|
| Empresa (código) | `#entity\.empresa\.cdEmpresaView` + Tab |
| Data início/fim | `entity.dtPagtoInicio` / `entity.dtPagtoFim` — JS masked input |
| Ordenação | `#tpOrdenacao` — select value `R` |
| Processar parcelas | `#flTodasC` |
| Lupa Tipo de Baixa | `#tipoBaixaCPG img[src*="botProcurar.png"]:first-of-type` |
| Botão Visualizar | `input[value="Visualizar"]` → nova aba |

---

## Etapa 3: Extração e matching de lançamentos

**Script:** `extrair_lancamentos.py`

Reads `RELATORIO_CONTAS_PAGAS_{DATA_LOTE}.pdf` with `pdfplumber`, matches each comprovante by **valor líquido**.

### Matching logic

Primary key: `liquido` value. Disambiguation when multiple SIENGE entries share the same value:
- **Positional** — when `_XDE Y` suffix count equals SIENGE entry count, paired in report order
- **Name similarity** — Jaccard token-overlap score between sanitized comprovante name and `credor`
- **Attach to all** — when best and second-best name scores are equal

### JSON output format

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

Reads `LANCAMENTOS_MATCHED_{DATA_LOTE}.json` from `RELATORIO_CONTAS_PAGAS/RELATORIO_CONTAS_{DATA_PASTA}/`. For each pair:

1. Navega para a SPA de Títulos via URL direta
2. Preenche "Título" → CONSULTAR → Editar
3. Aguarda iFramePage do Cadastro de Títulos (detecção por conteúdo)
4. Aba Anexos → ADICIONAR → upload na **última linha** do grid → SALVAR

### Seletores confirmados

| Elemento | Seletor | Contexto |
|---|---|---|
| Campo Título | `label:has-text("Título")` → `for` → `#{id}` | SPA (`page`) |
| Botão CONSULTAR | `#button-consultar-titulos-a-pagar` | SPA (`page`) |
| Botão Editar | `button[aria-label="Editar"]` | SPA (`page`) |
| Aba Anexos | `a:has-text("Anexos")` | iFramePage |
| Botão ADICIONAR | `input[value="Adicionar"]` | iFramePage |
| File input nova linha | `tr:has(input[type="file"])` → último → `input[type="file"]` | iFramePage |
| Descrição nova linha | `tr:has(input[type="file"])` → último → `input[type="text"]:not([readonly])` | iFramePage |
| Botão SALVAR | `#btSalvar` com `force=True` + `scrollIntoView` | iFramePage |

---

## Arquitetura do SIENGE no Playwright — lições aprendidas

### Estrutura de frames

| Frame | Identificador | Uso |
|---|---|---|
| Página principal | `index.html` | sidebar SPA (React/MUI) |
| Formulário clássico | `iframe[name="iFramePage"]` em `/sienge/CPG/...` | relatório, Cadastro de Títulos, Anexos |
| Overlay de busca | URL contendo `spjGenericSearch.do` | resultados de lupas IS_request |

**Detecção do iFramePage (SPA v9.x):** o frame aparece com `name=''` e `url=''` por até 20s. Usar polling por conteúdo dentro do loop:

```python
for attempt in range(60):
    for f in page.frames:
        if f.is_detached():
            continue
        try:
            body = f.inner_text('body')
            if 'Cadastro' in body and 'Parcelas' in body:
                return f
        except Exception:
            pass
    time.sleep(0.5)
```

### Masked inputs

Campos de data e código rejeitam `fill()` e `type()`. Usar JS + native value setter + eventos `input`/`change`/`blur`.  
Ler valor atual via `frame.evaluate('document.getElementById("id").value')` — nunca `get_attribute('value')`.

### Padrão IS_request / lupas

1. Clicar na lupa no frame do formulário
2. Overlay carrega num **novo iframe** na página principal (não janela nova)
3. Identificar frame pela URL (`spjGenericSearch.do`)
4. Interagir com checkboxes → `input[value="Selecionar"]`

### Notificações push

```python
for sel in ['button:has-text("NÃO, OBRIGADO")', 'button:has-text("Fechar")', '[data-dismiss="modal"]']:
    el = page.query_selector(sel)
    if el and el.is_visible():
        el.click()
```

### Download de relatório PDF

Após "Visualizar", nova aba abre `please_wait_frame.jsp?url=/sienge/viewReportSPW.do?...`. Capturar a URL via `response` listener e baixar com `requests` + cookies do contexto Playwright.

### Arquitetura híbrida SPA + JSP

- **JSP (clássico):** `sienge_relatorio.py` — conteúdo em `iFramePage`, inputs com máscara, lupas IS_request
- **SPA (React/MUI):** `sienge_anexar.py` — conteúdo direto na `page`, inputs MUI sem `placeholder`

`page.content()` retorna apenas o HTML externo — usar `frame.content()` para inspecionar iframes.  
`page.screenshot()` renderiza o viewport completo incluindo iframes.
