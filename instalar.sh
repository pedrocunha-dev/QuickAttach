#!/usr/bin/env bash
# Instala dependências e cria atalho de desktop para o QuickAttach.

set -e

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
APP_PY="$SCRIPT_DIR/app.py"
PYTHON="$(which python3)"

echo "=== QuickAttach — Instalação ==="
echo "Diretório dos scripts : $SCRIPT_DIR"
echo "Python                : $PYTHON ($($PYTHON --version))"
echo ""

# ── 1. Dependências Python ───────────────────────────────────────────────────
echo "[1/3] Instalando dependências Python..."
"$PYTHON" -m pip install --quiet --upgrade pymupdf playwright requests pdfplumber
echo "      OK"

# ── 2. Browser Playwright ────────────────────────────────────────────────────
echo "[2/3] Instalando Chromium (Playwright)..."
"$PYTHON" -m playwright install chromium
echo "      OK"

# ── 3. Atalho .desktop ───────────────────────────────────────────────────────
echo "[3/3] Criando atalho de desktop..."

DESKTOP_CONTENT="[Desktop Entry]
Name=QuickAttach
Comment=Anexo de comprovantes no SIENGE — Condomínio Solar Sinatra
Exec=$PYTHON $APP_PY
Path=$SCRIPT_DIR
Type=Application
Terminal=false
Categories=Office;Finance;
StartupNotify=true"

# Atalho no Desktop do utilizador
DESKTOP_FILE="$HOME/Desktop/QuickAttach.desktop"
echo "$DESKTOP_CONTENT" > "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"
echo "      Desktop   : $DESKTOP_FILE"

# Entrada no menu de aplicações
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
echo "$DESKTOP_CONTENT" > "$APPS_DIR/quickattach.desktop"
echo "      Aplicações: $APPS_DIR/quickattach.desktop"

echo ""
echo "=== Instalação concluída. ==="
echo "    Abra o QuickAttach pelo ícone no Desktop ou pelo menu de aplicações."
