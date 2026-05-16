#!/bin/bash
# =============================================================
#   CONFIGURA INICIALIZACAO AUTOMATICA DO PHOTOBOOTH
# =============================================================
# Execute uma vez no Raspberry Pi:
#   chmod +x autostart_rpi.sh
#   ./autostart_rpi.sh
#
# Apos rodar, reinicie o RPi. O photobooth vai abrir sozinho.

set -e

USUARIO="${SUDO_USER:-$USER}"
PASTA="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "============================================="
echo "  CONFIGURANDO AUTOSTART DO PHOTOBOOTH"
echo "============================================="
echo "  Usuario: $USUARIO"
echo "  Pasta:   $PASTA"
echo "============================================="
echo ""

# ── 1. Configura sudo sem senha para o photobooth ──
echo "[1/3] Configurando permissao de hardware sem senha..."
SUDOERS_LINE="$USUARIO ALL=(ALL) NOPASSWD: /usr/bin/python3 $PASTA/photobooth_pc.py"
echo "$SUDOERS_LINE" | sudo tee /etc/sudoers.d/photobooth > /dev/null
sudo chmod 440 /etc/sudoers.d/photobooth
echo "   OK"

# ── 2. Cria o script de inicializacao ───────
echo "[2/3] Criando script de inicializacao..."

cat > "$PASTA/start_photobooth.sh" << EOF
#!/bin/bash
export DISPLAY=:0

# Aguarda o desktop e perifericos carregarem
sleep 5

# Desativa screensaver e economia de energia
xset s off
xset -dpms
xset s noblank

cd "$PASTA"

# Loop: reinicia automaticamente se travar ou cair a luz
while true; do
    echo "\$(date): Iniciando photobooth..."
    sudo /usr/bin/python3 "$PASTA/photobooth_pc.py"
    echo "\$(date): Encerrado. Reiniciando em 3s..."
    sleep 3
done
EOF

chmod +x "$PASTA/start_photobooth.sh"
echo "   OK"

# ── 3. Registra no autostart do LXDE ────────
echo "[3/3] Registrando no autostart do desktop..."
mkdir -p "/home/$USUARIO/.config/autostart"

cat > "/home/$USUARIO/.config/autostart/photobooth.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Photobooth
Exec=$PASTA/start_photobooth.sh
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

echo "   OK"

echo ""
echo "============================================="
echo "  PRONTO! Reinicie para ativar:"
echo "    sudo reboot"
echo ""
echo "  Para desativar o autostart:"
echo "    rm ~/.config/autostart/photobooth.desktop"
echo "============================================="
