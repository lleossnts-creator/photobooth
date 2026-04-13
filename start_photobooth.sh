#!/bin/bash
# =============================================================
#   INICIA O PHOTOBOOTH
# =============================================================
# Use este script para iniciar o photobooth manualmente
# ou configure-o para iniciar automaticamente com o boot.
#
# Para iniciar automaticamente no boot com o desktop:
#   mkdir -p ~/.config/autostart
#   cp photobooth.desktop ~/.config/autostart/
#   (edite o caminho no arquivo .desktop)

PASTA="$(cd "$(dirname "$0")" && pwd)"

# Aguarda o desktop carregar (importante no autostart)
sleep 3

# Garante que o DISPLAY esta configurado (necessario para janela OpenCV)
export DISPLAY="${DISPLAY:-:0}"

echo "Iniciando photobooth em: $PASTA"
cd "$PASTA"
exec python3 photobooth_pc.py
