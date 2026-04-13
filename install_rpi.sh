#!/bin/bash
# =============================================================
#   INSTALACAO DO PHOTOBOOTH NO RASPBERRY PI 4
# =============================================================
#
# Execute uma vez apos clonar/copiar o projeto:
#   chmod +x install_rpi.sh
#   ./install_rpi.sh
#
# Apos instalar, REINICIE ou faca logout/login para
# que as permissoes de grupo entrem em vigor.

set -e

USUARIO="${SUDO_USER:-$USER}"
PASTA="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "============================================="
echo "  INSTALANDO PHOTOBOOTH — RASPBERRY PI 4"
echo "============================================="
echo "  Usuario: $USUARIO"
echo "  Pasta:   $PASTA"
echo "============================================="
echo ""

# ── 1. Atualiza o sistema ────────────────────────
echo "[1/6] Atualizando lista de pacotes..."
sudo apt-get update -q

# ── 2. Instala dependencias do sistema ──────────
echo "[2/6] Instalando dependencias do sistema..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-opencv \
    python3-picamera2 \
    python3-pil \
    python3-numpy \
    libusb-1.0-0 \
    libusb-dev \
    udev

# ── 3. Instala dependencias Python ──────────────
echo "[3/6] Instalando dependencias Python..."

# Detecta se precisa de --break-system-packages (Bookworm+)
PIP_FLAGS=""
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
    PIP_FLAGS="--break-system-packages"
fi

pip3 install $PIP_FLAGS python-escpos pyusb

# ── 4. Regras udev para impressora USB ──────────
echo "[4/6] Instalando regras udev para impressora USB..."

# Le vendor_id e product_id do config.json
VENDOR_RAW=$(python3 -c "
import json, sys
try:
    with open('$PASTA/config.json') as f:
        c = json.load(f)
    v = c['impressora']['vendor_id'].replace('0x','').lower()
    p = c['impressora']['product_id'].replace('0x','').lower()
    print(v, p)
except Exception as e:
    print('0416 5011')  # fallback padrao
")
VENDOR_ID=$(echo $VENDOR_RAW | cut -d' ' -f1)
PRODUCT_ID=$(echo $VENDOR_RAW | cut -d' ' -f2)

echo "   Impressora detectada: vendor=$VENDOR_ID product=$PRODUCT_ID"
echo "   (Confirme com: lsusb)"

# Cria regra udev especifica para a impressora
sudo tee /etc/udev/rules.d/50-thermal-printer.rules > /dev/null <<EOF
# Impressora termica ESC/POS — acesso sem sudo
# Gerado por install_rpi.sh
SUBSYSTEM=="usb", ATTRS{idVendor}=="$VENDOR_ID", ATTRS{idProduct}=="$PRODUCT_ID", MODE="0666", GROUP="plugdev"
# Regra generica para outras impressoras termicas (opcional)
# SUBSYSTEM=="usb", DRIVERS=="usb", ATTRS{bInterfaceClass}=="07", MODE="0666", GROUP="plugdev"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

# ── 5. Permissoes de grupo ───────────────────────
echo "[5/6] Adicionando $USUARIO aos grupos necessarios..."
sudo usermod -a -G video,plugdev "$USUARIO"

# ── 6. Habilita camera no raspi-config ──────────
echo "[6/6] Verificando status da camera..."
# No RPi OS moderno (Bullseye+) a camera e habilitada automaticamente
# mas verifica se libcamera esta disponivel
if ! python3 -c "from picamera2 import Picamera2" 2>/dev/null; then
    echo ""
    echo "   ATENCAO: picamera2 nao foi carregado corretamente."
    echo "   Verifique se a camera esta habilitada:"
    echo "   sudo raspi-config > Interface Options > Camera"
    echo "   Ou edite /boot/firmware/config.txt e adicione: camera_auto_detect=1"
fi

# ── Resumo ───────────────────────────────────────
echo ""
echo "============================================="
echo "  INSTALACAO CONCLUIDA!"
echo "============================================="
echo ""
echo "  IMPORTANTE: Reinicie o Raspberry Pi para"
echo "  aplicar as permissoes de grupo:"
echo ""
echo "    sudo reboot"
echo ""
echo "  Depois de reiniciar, execute:"
echo "    cd $PASTA"
echo "    python3 photobooth_pc.py"
echo ""
echo "  Para verificar a impressora USB:"
echo "    lsusb"
echo ""
echo "  Para testar a camera:"
echo "    libcamera-hello --timeout 3000"
echo "============================================="
