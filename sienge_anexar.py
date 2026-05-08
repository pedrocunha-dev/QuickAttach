"""Etapas 6–7: navega até cada lançamento em SIENGE, abre a aba Anexos e
   faz upload do comprovante correspondente.
"""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_DIR = Path.home() / 'QuickAttach'
DATA_LOTE = '20042026'
DATA_PASTA = '20260420'    # AAAAMMDD

CREDS_FILE = BASE_DIR / 'sienge_credentials.json'
JSON_FILE = (BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{DATA_PASTA}'
             / f'LANCAMENTOS_MATCHED_{DATA_LOTE}.json')
COMPROVANTES_DIR = BASE_DIR / 'COMPROVANTES_SEPARADOS' / f'COMPROVANTES_SEP_{DATA_PASTA}'
SIENGE_URL = 'https://escolengenharia.sienge.com.br/sienge/'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_credentials():
    creds = json.loads(CREDS_FILE.read_text())
    return creds['login'], creds['senha']


def _dismiss_notifications(page):
    for sel in [
        'button:has-text("NÃO, OBRIGADO")',
        'button:has-text("Não, obrigado")',
        'a:has-text("NÃO, OBRIGADO")',
        'button:has-text("Fechar")',
        '[data-dismiss="modal"]',
        'button:has-text("ENTENDI")',
        'button:has-text("Entendi")',
    ]:
        try:
            for el in page.query_selector_all(sel):
                if el.is_visible():
                    el.click()
                    print(f'  Notificação dispensada: {sel}')
                    time.sleep(0.3)
        except Exception:
            pass


def _get_iframe(page):
    for _ in range(30):
        frame = page.frame(name='iFramePage')
        if frame and not frame.is_detached():
            return frame
        for f in page.frames:
            if 'iFramePage' in (f.name or '') and not f.is_detached():
                return f
        time.sleep(0.5)
    return None


def _js_fill(frame, field_id, value):
    frame.evaluate(f'''
        var el = document.getElementById("{field_id}");
        if (el) {{
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, "{value}");
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.dispatchEvent(new Event('blur', {{bubbles: true}}));
        }}
    ''')


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def login_sienge(page, login, senha):
    print('[1] Abrindo SIENGE...')
    page.goto(SIENGE_URL, timeout=30000)
    try:
        page.wait_for_selector('input[name="username"], #username', timeout=15000)
    except Exception:
        time.sleep(5)

    for sel in ['input[name="username"]', '#username']:
        try:
            if page.query_selector(sel):
                page.fill(sel, login)
                break
        except Exception:
            pass

    for sel in ['button[type="submit"]', 'button:has-text("Entrar")']:
        try:
            if page.query_selector(sel):
                page.click(sel)
                break
        except Exception:
            pass

    try:
        page.wait_for_selector('input[type="password"]', timeout=10000)
    except Exception:
        time.sleep(3)
    for sel in ['input[type="password"]']:
        try:
            if page.query_selector(sel):
                page.fill(sel, senha)
                page.click('button[type="submit"]')
                break
        except Exception:
            pass

    print('[2] Aguardando login/MFA (complete no browser se solicitado)...')
    mfa_msg_shown = False
    i = 0
    while True:
        time.sleep(5)
        try:
            if page.is_closed():
                raise RuntimeError('Browser fechado antes de concluir o login.')
            url = page.url
            print(f'  [{i * 5}s] {url}')
            if 'index.html' in url:
                print('  Login OK!')
                break
            if 'multifactor-authentication' in url and not mfa_msg_shown:
                mfa_msg_shown = True
                print('  MFA detectado — complete a verificacao no browser e aguarde.')
        except RuntimeError:
            raise
        except Exception:
            pass
        i += 1

    for _ in range(20):
        time.sleep(2)
        try:
            if 'Olá' in page.inner_text('body'):
                break
        except Exception:
            pass
    time.sleep(2)


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def navigate_to_titulos(page):
    print('[3] Navegando para Consulta de Títulos a Pagar...')
    _dismiss_notifications(page)

    SPA_TITULOS = ('https://escolengenharia.sienge.com.br/sienge/8/'
                   'index.html#/financeiro/contas-pagar/titulos')
    page.goto(SPA_TITULOS, timeout=20000)

    for _ in range(30):
        if 'titulos' in page.url or '#/' in page.url:
            print(f'  SPA carregado: {page.url}')
            break
        time.sleep(0.5)

    try:
        page.wait_for_selector('label:has-text("Título")', timeout=15000)
        print('  Formulário renderizado.')
    except Exception:
        time.sleep(3)

    return page


# ---------------------------------------------------------------------------
# Search + open lançamento
# ---------------------------------------------------------------------------

def _fill_titulo_field(frame, lancamento):
    try:
        label = frame.query_selector('label:has-text("Título")')
        if label:
            input_id = label.get_attribute('for')
            if input_id:
                frame.fill(f'#{input_id}', lancamento)
                print(f'  Campo Título preenchido via label→#{input_id}')
                return True
    except Exception:
        pass

    try:
        el = frame.query_selector('#section-component input[type="text"]')
        if el:
            el.fill(lancamento)
            print('  Campo Título preenchido via first input em #section-component')
            return True
    except Exception:
        pass

    return False


def search_lancamento(page, frame, lancamento):
    print(f'  Buscando lançamento {lancamento}...')
    _dismiss_notifications(page)
    time.sleep(0.5)
    _dismiss_notifications(page)

    if not _fill_titulo_field(frame, lancamento):
        print('  ERRO: campo Título não encontrado')
        return None

    time.sleep(0.5)

    consultar_clicked = False
    for sel in [
        '#button-consultar-titulos-a-pagar',
        'button:has-text("CONSULTAR")',
        'button:has-text("Consultar")',
        'input[value="Consultar"]',
        'input[value="CONSULTAR"]',
    ]:
        try:
            el = frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f'  CONSULTAR clicado: {sel}')
                consultar_clicked = True
                break
        except Exception:
            pass

    if not consultar_clicked:
        print('  ERRO: botão CONSULTAR não encontrado')
        return None

    try:
        page.wait_for_selector('[role="row"]:not([aria-rowindex="1"])', timeout=8000)
    except Exception:
        pass
    time.sleep(1)
    return page


def click_editar(page, frame, lancamento):
    print(f'  Clicando em Editar — lançamento {lancamento}...')
    _dismiss_notifications(page)

    editar_clicked = False
    for sel in [
        'button[aria-label="Editar"]',
        'button[aria-label="editar"]',
        '[aria-label="Editar"]',
        'img[src*="botEditar"]',
        'img[title="Editar"]',
        'a[title="Editar"]',
    ]:
        try:
            el = frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f'  Ícone Editar clicado: {sel}')
                editar_clicked = True
                break
        except Exception:
            pass

    if not editar_clicked:
        print(f'  ERRO: ícone Editar não encontrado — lançamento {lancamento}')
        return None

    # Detect iFramePage by content (may take >20s in SPA v9.x)
    time.sleep(2)
    cadastro_frame = None
    for attempt in range(60):
        for f in page.frames:
            if f.is_detached():
                continue
            name = f.name or ''
            url = f.url or ''
            if ('iFramePage' in name or 'editTitulo' in url or
                    ('CPG' in url and 'Titulo' in url)):
                try:
                    f.wait_for_selector('a, table, form', timeout=2000)
                    cadastro_frame = f
                    break
                except Exception:
                    pass
            try:
                body = f.inner_text('body')
                if 'Cadastro' in body and 'Parcelas' in body:
                    cadastro_frame = f
                    break
            except Exception:
                pass
        if cadastro_frame:
            break
        if attempt % 8 == 0:
            names = [(f.name, f.url[:80]) for f in page.frames if not f.is_detached()]
            print(f'  [click_editar tentativa {attempt}] frames: {names}')
        time.sleep(0.5)

    if cadastro_frame:
        print(f'  Cadastro iframe: name={cadastro_frame.name!r} url={cadastro_frame.url[:80]}')
        return cadastro_frame

    # Fallback: content scan
    for f in page.frames:
        if f.is_detached():
            continue
        try:
            body = f.inner_text('body')
            if ('Cadastro' in body or 'Título' in body) and 'Parcelas' in body:
                print(f'  Cadastro encontrado por conteúdo: name={f.name!r}')
                return f
        except Exception:
            pass

    # Fallback: Cadastro loaded directly in SPA page
    try:
        page.wait_for_selector('a:has-text("Anexos"), [role="tab"]:has-text("Anexos")', timeout=3000)
        print('  Cadastro carregado diretamente na SPA (sem iFrame)')
        return page
    except Exception:
        pass

    all_frames = [(f.name, f.url) for f in page.frames if not f.is_detached()]
    print(f'  AVISO: frame do Cadastro não encontrado — {len(all_frames)} frames disponíveis')
    return page


def open_anexos_tab(page, frame, lancamento):
    print(f'  Abrindo aba Anexos — lançamento {lancamento}...')
    _dismiss_notifications(page)

    anexos_clicked = False
    for sel in [
        'a:has-text("Anexos")',
        'button:has-text("Anexos")',
        '[role="tab"]:has-text("Anexos")',
        'td:has-text("Anexos") a',
        'li:has-text("Anexos") a',
        'span:has-text("Anexos")',
        'table.abas td:nth-child(8) a',
        'tr td:nth-child(8) a',
    ]:
        try:
            el = frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f'  Aba Anexos clicada: {sel}')
                anexos_clicked = True
                break
        except Exception:
            pass

    if not anexos_clicked:
        print(f'  ERRO: aba Anexos não encontrada — lançamento {lancamento}')
        return None

    time.sleep(1.5)
    fresh_frame = _get_iframe(page)
    return fresh_frame if fresh_frame else frame


# ---------------------------------------------------------------------------
# Etapa 7: upload do comprovante
# ---------------------------------------------------------------------------

def _already_attached(frame, comprovante_nome):
    try:
        text = frame.inner_text('body')
        base = comprovante_nome.replace('.pdf', '')
        return comprovante_nome in text or base in text
    except Exception:
        return False


def upload_comprovante(page, frame, lancamento, comprovante_nome):
    file_path = COMPROVANTES_DIR / comprovante_nome
    if not file_path.exists():
        print(f'  ERRO: arquivo não encontrado: {file_path}')
        return False

    time.sleep(1)

    if _already_attached(frame, comprovante_nome):
        print(f'  SKIP: {comprovante_nome} já está anexado em {lancamento}')
        return True

    # ── Clicar em ADICIONAR ──────────────────────────────────────────────────
    adicionar_clicked = False
    for sel in [
        'input[value="Adicionar"]',
        'input[value="ADICIONAR"]',
        'a:has-text("Adicionar")',
        'button:has-text("Adicionar")',
        'input[value="Incluir"]',
        'a:has-text("Incluir")',
        'button:has-text("Incluir")',
    ]:
        try:
            el = frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f'  ADICIONAR clicado: {sel}')
                adicionar_clicked = True
                break
        except Exception:
            pass

    if not adicionar_clicked:
        print(f'  ERRO: botão ADICIONAR não encontrado — lançamento {lancamento}')
        return False

    time.sleep(1.5)
    upload_frame = _get_iframe(page) or frame

    # ── Localizar a nova linha (última com input[type="file"]) ───────────────
    time.sleep(0.5)
    new_row = None
    try:
        rows = upload_frame.query_selector_all('tr:has(input[type="file"])')
        if rows:
            new_row = rows[-1]
            print(f'  Nova linha identificada (última de {len(rows)} com file input)')
    except Exception:
        pass

    # ── Selecionar arquivo ───────────────────────────────────────────────────
    file_set = False
    if new_row:
        try:
            file_inp = new_row.query_selector('input[type="file"]')
            if file_inp:
                file_inp.set_input_files(str(file_path))
                print(f'  Arquivo definido: {comprovante_nome}')
                file_set = True
        except Exception as e:
            print(f'  AVISO set_input_files na nova linha: {e}')
    if not file_set:
        try:
            all_file_inputs = upload_frame.query_selector_all('input[type="file"]')
            if all_file_inputs:
                all_file_inputs[-1].set_input_files(str(file_path))
                print(f'  Arquivo definido via fallback: {comprovante_nome}')
                file_set = True
        except Exception as e:
            print(f'  ERRO ao definir arquivo: {e}')
            return False

    time.sleep(0.5)

    # ── Preencher descrição na nova linha ────────────────────────────────────
    desc_filled = False
    if new_row:
        try:
            desc_inp = new_row.query_selector(
                'input[type="text"]:not([readonly]):not([disabled]),'
                'textarea:not([readonly]):not([disabled])'
            )
            if desc_inp and desc_inp.is_visible():
                desc_inp.fill(comprovante_nome)
                print(f'  Descrição preenchida: {comprovante_nome}')
                desc_filled = True
        except Exception:
            pass
    if not desc_filled:
        for desc_sel in ['input[name="nmAnexo"]', 'input[name="deAnexo"]', '#nmAnexo', '#deAnexo']:
            try:
                el = upload_frame.query_selector(desc_sel)
                if el and el.is_visible():
                    el.fill(comprovante_nome)
                    print(f'  Descrição preenchida ({desc_sel}): {comprovante_nome}')
                    desc_filled = True
                    break
            except Exception:
                pass

    if not desc_filled:
        print('  AVISO: campo de descrição não encontrado, prosseguindo')

    # ── Salvar ───────────────────────────────────────────────────────────────
    saved = False
    all_save_ctxs = [upload_frame, frame] + [
        f for f in page.frames if not f.is_detached() and f is not upload_frame and f is not frame
    ] + [page]
    for save_sel in [
        '#btSalvar',
        'input[name="btSalvar"]',
        'input[type="submit"][value="Salvar"]',
        'input[value="Salvar"]',
        'input[value="SALVAR"]',
        'input[value="Gravar"]',
        'button:has-text("Salvar")',
        'button:has-text("SALVAR")',
    ]:
        for ctx in all_save_ctxs:
            try:
                el = ctx.query_selector(save_sel)
                if el:
                    ctx.evaluate(
                        f"var el = document.querySelector('{save_sel}');"
                        "if (el) el.scrollIntoView({block: 'center'});"
                    )
                    time.sleep(0.3)
                    el.click(force=True)
                    origin = 'page' if ctx is page else f'frame({ctx.url[:60]})'
                    print(f'  Salvar clicado ({origin}): {save_sel}')
                    saved = True
                    break
            except Exception:
                pass
        if saved:
            break

    if not saved:
        print(f'  ERRO: botão Salvar não encontrado — lançamento {lancamento}')
        return False

    time.sleep(2)

    # ── Verificar resultado ──────────────────────────────────────────────────
    final_frame = _get_iframe(page) or upload_frame
    if _already_attached(final_frame, comprovante_nome):
        print(f'  OK: {comprovante_nome} anexado com sucesso em {lancamento}')
    else:
        print(f'  AVISO: não foi possível confirmar o anexo de {comprovante_nome} em {lancamento}')

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global DATA_LOTE, DATA_PASTA, JSON_FILE, COMPROVANTES_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-lote', default=DATA_LOTE)
    parser.add_argument('--data-pasta', default=DATA_PASTA)
    args = parser.parse_args()
    DATA_LOTE = args.data_lote
    DATA_PASTA = args.data_pasta
    JSON_FILE = (BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{DATA_PASTA}'
                 / f'LANCAMENTOS_MATCHED_{DATA_LOTE}.json')
    COMPROVANTES_DIR = BASE_DIR / 'COMPROVANTES_SEPARADOS' / f'COMPROVANTES_SEP_{DATA_PASTA}'

    login, senha = read_credentials()
    data = json.loads(JSON_FILE.read_text())
    pairs = data['pairs']
    print(f'  {len(pairs)} pares a processar.')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        ctx = browser.new_context(viewport={'width': 1600, 'height': 900})
        page = ctx.new_page()

        login_sienge(page, login, senha)
        frame = navigate_to_titulos(page)

        ok = 0
        skip = 0

        for pair in pairs:
            lancamento = pair['lancamento']
            comprovante = pair['comprovante']
            print(f'\n[>>>] {comprovante}  →  lançamento {lancamento}')

            frame = search_lancamento(page, frame, lancamento)
            if frame is None:
                skip += 1
                frame = navigate_to_titulos(page)
                continue

            frame = click_editar(page, frame, lancamento)
            if frame is None:
                skip += 1
                frame = navigate_to_titulos(page)
                continue

            frame = open_anexos_tab(page, frame, lancamento)
            if frame is None:
                skip += 1
                frame = navigate_to_titulos(page)
                continue

            if not upload_comprovante(page, frame, lancamento, comprovante):
                skip += 1
                frame = navigate_to_titulos(page)
                continue

            ok += 1
            frame = navigate_to_titulos(page)

        print(f'\n[CONCLUÍDO] OK={ok}  SKIP={skip}  Total={len(pairs)}')
        time.sleep(5)
        browser.close()


if __name__ == '__main__':
    main()
