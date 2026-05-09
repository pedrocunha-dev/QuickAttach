"""Generates and saves the 'Contas Pagas' report from SIENGE."""
import argparse
import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_DIR = Path.home() / 'QuickAttach'
DATA_INICIO = '20/04/2026'
DATA_FIM = '20/04/2026'
EMPRESA_CD = '12'
DATA_PASTA = '20260420'    # AAAAMMDD


def read_credentials():
    creds = json.loads((BASE_DIR / 'sienge_credentials.json').read_text())
    return creds['login'], creds['senha']


def login_sienge(page, login, senha):
    print('[1] Abrindo SIENGE...')
    page.goto('https://escolengenharia.sienge.com.br/sienge/', timeout=30000)
    try:
        page.wait_for_selector('input[name="username"], #username', timeout=15000)
    except:
        time.sleep(5)

    for sel in ['input[name="username"]', '#username']:
        try:
            if page.query_selector(sel):
                page.fill(sel, login); break
        except: pass

    for sel in ['button[type="submit"]', 'button:has-text("Entrar")']:
        try:
            if page.query_selector(sel):
                page.click(sel); break
        except: pass

    try:
        page.wait_for_selector('input[type="password"]', timeout=10000)
    except:
        time.sleep(3)
    for sel in ['input[type="password"]']:
        try:
            if page.query_selector(sel):
                page.fill(sel, senha)
                page.click('button[type="submit"]')
                break
        except: pass

    print('[2] Aguardando login/MFA (complete no browser se solicitado)...')
    if 'multifactor-authentication' in page.url:
        print('  MFA detectado — complete a verificacao no browser e aguarde.')

    # Aguarda navegação para qualquer URL fora do domínio login.sienge.com.br
    try:
        page.wait_for_url(
            lambda url: (
                'escolengenharia.sienge.com.br' in url and
                'login.sienge.com.br' not in url
            ),
            timeout=600000,
        )
    except Exception as e:
        print(f'  wait_for_url falhou: {e}')

    print(f'  Login OK! ({page.url[:80]})')
    for _ in range(20):
        time.sleep(2)
        try:
            if 'Olá' in page.inner_text('body'): break
        except: pass
    time.sleep(2)
    return page


def navigate_to_form(page):
    print('[3] Navegando para Contas Pagas...')
    page.click('[aria-label="FIN"]', timeout=10000)
    time.sleep(2)
    page.click('text=Contas a Pagar', timeout=10000)
    time.sleep(2)
    page.click('text=Relatórios', timeout=10000)
    time.sleep(2)
    page.click('text=Contas pagas', timeout=10000)

    print('  Aguardando iframe do formulário (até 60s)...')
    main_url = page.url
    frame = None
    for _ in range(120):
        frame = page.frame(name='iFramePage')
        if not frame:
            frame = page.frame(url='*filterContaPagas*')
        if not frame:
            for f in page.frames:
                if f.is_detached():
                    continue
                try:
                    u = f.url or ''
                    # exclude the main SPA frame
                    if u == main_url or u.startswith(main_url.split('#')[0] + '#'):
                        continue
                    if any(k in u for k in ('ContaPagas', 'filterContaPagas', 'CPG')):
                        frame = f
                        break
                except Exception:
                    pass
        # fallback: detect by presence of Contas Pagas form elements
        if not frame:
            for f in page.frames:
                if f.is_detached():
                    continue
                try:
                    u = f.url or ''
                    if u == main_url or u.startswith(main_url.split('#')[0] + '#'):
                        continue
                    if (f.query_selector('[name="entity.dtPagtoInicio"]') or
                            f.query_selector('#tipoBaixaCPG') or
                            f.query_selector('[name="entity.empresa.cdEmpresaView"]')):
                        frame = f
                        break
                except Exception:
                    pass
        if frame:
            break
        time.sleep(0.5)

    if not frame:
        urls = []
        for f in page.frames:
            try:
                urls.append(f.url)
            except Exception:
                pass
        print(f'  Frames disponiveis: {urls}')
        raise RuntimeError('Iframe do formulário não encontrado')
    print(f'  Iframe localizado: {frame.url[:80]}')
    return frame


def _dismiss_notifications(page):
    for sel in [
        'button:has-text("NÃO, OBRIGADO")',
        'button:has-text("Não, obrigado")',
        'a:has-text("NÃO, OBRIGADO")',
        'button:has-text("Fechar")',
        '[data-dismiss="modal"]',
    ]:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                print(f'  Notificação dispensada: {sel}')
                time.sleep(0.5)
                return
        except:
            pass


def select_tipo_baixa(ctx, frame, page):
    print('[8] Selecionando Tipo de Baixa via lupa...')

    _dismiss_notifications(page)

    lupa_sel = '#tipoBaixaCPG img[src*="botProcurar.png"]:first-of-type'
    if not frame.query_selector(lupa_sel):
        lupa_sel = 'img[src*="botProcurar"][title="Abre a consulta"]'

    if not frame.query_selector(lupa_sel):
        print('  AVISO: lupa #tipoBaixaCPG não encontrada no frame.')
        return

    print(f'  Clicando lupa: {lupa_sel}')
    frame.click(lupa_sel)
    time.sleep(3)

    _dismiss_notifications(page)
    time.sleep(1)

    overlay_frame = None
    for f in page.frames:
        if 'searchTipoBaixaCPG' in f.url or ('spjGenericSearch' in f.url and 'tipoBaixa' in f.url):
            overlay_frame = f
            print(f'  Overlay frame encontrado: {f.url[:100]}')
            break

    if not overlay_frame:
        print('  AVISO: overlay do Tipo de Baixa não encontrado.')
        return

    TIPOS = ['Pagamento', 'Adiantamento']
    selected_tipos = []

    for row in overlay_frame.query_selector_all('tr'):
        try:
            cb = row.query_selector('input[type="checkbox"]')
            if not cb:
                continue
            row_text = row.inner_text().strip()
            if row_text.count('\n') > 1:
                continue
            desc_match = re.match(r'^\d+\s+(.+)$', row_text)
            desc = desc_match.group(1).strip() if desc_match else row_text
            matched_tipo = next((t for t in TIPOS if t.lower() == desc.lower()), None)
            if matched_tipo:
                cb.check()
                selected_tipos.append(matched_tipo)
                print(f'  Checkbox marcado: {matched_tipo}')
                time.sleep(0.3)
        except Exception as e:
            print(f'  Erro ao marcar checkbox: {e}')

    for tipo in TIPOS:
        if tipo not in selected_tipos:
            print(f'  AVISO: "{tipo}" não encontrado no overlay')

    confirmed = False
    for ctx_el in [overlay_frame, page, frame]:
        for sel in ['input[value="Selecionar"]', 'input[value="Confirmar"]', 'input[value="OK"]',
                    'button:has-text("Selecionar")', 'button:has-text("Confirmar")',
                    'a:has-text("Selecionar")', 'a:has-text("Confirmar")']:
            try:
                el = ctx_el.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    print(f'  Confirmado via: {sel}')
                    confirmed = True
                    break
            except:
                pass
        if confirmed:
            break

    if not confirmed:
        print('  AVISO: botão de confirmação não encontrado.')

    time.sleep(1)


def fill_form(ctx, frame, page):
    print('[4] Preenchendo Empresa...')

    frame.fill('#entity\\.empresa\\.cdEmpresaView', EMPRESA_CD)
    frame.press('#entity\\.empresa\\.cdEmpresaView', 'Tab')
    time.sleep(2)

    try:
        frame.press('#entity\\.empresa\\.cdEmpresaView', 'Enter')
        time.sleep(1)
    except: pass

    empresa_name = frame.get_attribute('#entity\\.empresa\\.nmEmpresa', 'value') or ''
    print(f'  Empresa: {EMPRESA_CD} — {empresa_name}')

    print('[5] Preenchendo datas de pagamento...')
    for field_id, val in [('entity.dtPagtoInicio', DATA_INICIO),
                          ('entity.dtPagtoFim', DATA_FIM)]:
        frame.evaluate(f'''
            var el = document.getElementById("{field_id}");
            var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(el, "{val}");
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.dispatchEvent(new Event('blur', {{bubbles: true}}));
        ''')
        time.sleep(0.3)
        cur = frame.evaluate(f'document.getElementById("{field_id}").value')
        print(f'  {field_id} = {cur}')

    print('[6] Selecionando Ordem = Valor Pago...')
    try:
        opts = frame.query_selector('#tpOrdenacao')
        if opts:
            options = frame.evaluate('el => Array.from(el.options).map(o => ({v: o.value, t: o.text}))', opts)
            for opt in options:
                if 'valor' in opt['t'].lower() or 'pago' in opt['t'].lower():
                    frame.select_option('#tpOrdenacao', value=opt['v'])
                    print(f'  Selecionado: {opt["t"]}')
                    break
    except Exception as e:
        print(f'  Aviso Ordem: {e}')

    print('[7] Marcando Processar Parcelas = Contas a Pagar...')
    try:
        frame.check('#flTodasC')
        print('  flTodasC marcado')
    except Exception as e:
        print(f'  Aviso parcelas: {e}')

    select_tipo_baixa(ctx, frame, page)


def click_visualizar_and_save(ctx, frame, page):
    import requests as req_lib

    print('\n[9] Clicando em Visualizar...')

    vis_sel = None
    for sel in ['input[value="Visualizar"]', 'button:has-text("Visualizar")',
                'a:has-text("Visualizar")', 'input[type="submit"]']:
        try:
            if frame.query_selector(sel):
                vis_sel = sel; break
        except: pass

    if not vis_sel:
        for sel in ['button:has-text("Visualizar")', 'input[value="Visualizar"]']:
            try:
                if page.query_selector(sel):
                    vis_sel = sel; break
            except: pass

    print(f'  Botão encontrado: {vis_sel}')

    captured_report_url = []

    def capture_response(response):
        if 'viewReportSPW' in response.url and response.status == 200:
            if response.url not in captured_report_url:
                captured_report_url.append(response.url)
                print(f'  URL do relatório capturada: {response.url[:90]}')

    with ctx.expect_page(timeout=20000) as new_page_info:
        if vis_sel:
            frame.click(vis_sel)
        else:
            frame.press('body', 'Enter')

    report_page = new_page_info.value
    report_page.on('response', capture_response)

    print('[10] Aguardando relatório carregar...')
    report_page.wait_for_load_state('networkidle', timeout=60000)
    time.sleep(5)

    print(f'  URL da aba: {report_page.url}')

    date_str = DATA_INICIO.replace('/', '')
    relatorio_dir = BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{DATA_PASTA}'
    relatorio_dir.mkdir(parents=True, exist_ok=True)
    output = relatorio_dir / f'RELATORIO_CONTAS_PAGAS_{date_str}.pdf'

    if captured_report_url:
        report_url = captured_report_url[0]
    else:
        embedded = re.search(r'url=(/sienge/viewReportSPW[^&"]+)', report_page.url)
        if embedded:
            report_url = 'https://escolengenharia.sienge.com.br' + embedded.group(1)
        else:
            report_url = report_page.url

    print(f'  Baixando PDF de: {report_url[:90]}')

    cookies = ctx.cookies(urls=['https://escolengenharia.sienge.com.br'])
    cookie_header = '; '.join(f"{c['name']}={c['value']}" for c in cookies)
    resp = req_lib.get(report_url, headers={
        'Cookie': cookie_header,
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Referer': 'https://escolengenharia.sienge.com.br/',
    }, timeout=30)

    ct = resp.headers.get('content-type', '')
    print(f'  Content-Type: {ct} | Tamanho: {len(resp.content):,} bytes')

    if resp.content[:4] == b'%PDF' or 'pdf' in ct.lower():
        output.write_bytes(resp.content)
        print(f'\n  Relatório salvo: {output.name}')
    else:
        print(f'  AVISO: resposta não é PDF (Content-Type: {ct}). Verifique a URL do relatório.')

    return report_page


def main():
    global DATA_INICIO, DATA_FIM, EMPRESA_CD, DATA_PASTA
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-inicio', default=DATA_INICIO)
    parser.add_argument('--data-fim', default=DATA_FIM)
    parser.add_argument('--empresa', default=EMPRESA_CD)
    parser.add_argument('--data-pasta', default=DATA_PASTA)
    args = parser.parse_args()
    DATA_INICIO = args.data_inicio
    DATA_FIM = args.data_fim
    EMPRESA_CD = args.empresa
    DATA_PASTA = args.data_pasta

    login, senha = read_credentials()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        ctx = browser.new_context(viewport={'width': 1600, 'height': 900},
                                  accept_downloads=True)
        page = ctx.new_page()

        page = login_sienge(page, login, senha)
        frame = navigate_to_form(page)
        fill_form(ctx, frame, page)

        try:
            click_visualizar_and_save(ctx, frame, page)
        except PWTimeout:
            print('  Nova aba não abriu — salvando página atual...')
            date_str = DATA_INICIO.replace('/', '')
            relatorio_dir = BASE_DIR / 'RELATORIO_CONTAS_PAGAS' / f'RELATORIO_CONTAS_{DATA_PASTA}'
            relatorio_dir.mkdir(parents=True, exist_ok=True)
            output = relatorio_dir / f'RELATORIO_CONTAS_PAGAS_{date_str}.pdf'
            page.pdf(path=str(output), format='A4', landscape=True, print_background=True)
            print(f'  Relatório salvo: {output}')

        time.sleep(5)
        browser.close()
        print('\nConcluído.')


if __name__ == '__main__':
    main()
