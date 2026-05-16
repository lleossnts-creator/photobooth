#!/usr/bin/env python3
"""
=============================================================
  RECEIPT PHOTOBOOTH — RASPBERRY PI 4
  Camera Module 3 + Impressora Termica USB ESC/POS
=============================================================

  COMO USAR:
    1. Execute ./install_rpi.sh para instalar dependencias
    2. Conecte a impressora termica via USB
    3. Conecte o Camera Module 3 no conector CSI
    4. python3 photobooth_pc.py
    5. Aperte ESPACO pra tirar foto e imprimir
    6. Aperte Q ou ESC pra sair

  BOTAO FISICO (GPIO):
    - Quando tiver o botao, veja a secao "GPIO BUTTON" no codigo
    - Por padrao usa apenas o teclado (ESPACO)
"""

import json
import os
import sys
import time
import threading
from datetime import datetime

import cv2
import numpy as np
from PIL import Image, ImageOps, ImageEnhance

# ─────────────────────────────────────────────
# GPIO BUTTON (descomente quando tiver o botao fisico)
# ─────────────────────────────────────────────
from gpiozero import Button
BOTAO_GPIO_PINO = 23
botao_gpio = Button(BOTAO_GPIO_PINO, pull_up=True, bounce_time=0.1)


# ─────────────────────────────────────────────
# Controle da fita de LED WS2812B
# ─────────────────────────────────────────────
class LEDController:
    """Controla fita WS2812B via neopixel. Roda patterns em thread separada."""

    def __init__(self, config):
        import board
        import neopixel

        cfg = config.get("leds", {})
        self.qtd        = cfg.get("quantidade", 30)
        self.pattern    = cfg.get("pattern", "rainbow")
        self.cor_pattern = tuple(cfg.get("cor_pattern", [255, 0, 128]))
        self.cor_foto   = tuple(cfg.get("cor_foto", [255, 255, 255]))
        self.velocidade = cfg.get("velocidade", 0.05)
        brilho          = cfg.get("brilho", 0.5)

        self.pixels = neopixel.NeoPixel(
            board.D18, self.qtd,
            brightness=brilho,
            auto_write=False
        )

        self._modo     = "pattern"
        self._rodando  = True
        self._offset   = 0
        self._brilho_v = 0
        self._brilho_d = 1

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("OK Fita LED inicializada!")

    # ── Modos públicos ────────────────────────
    def modo_foto(self):
        """Interrompe o pattern e acende cor sólida para a foto."""
        self._modo = "foto"
        self.pixels.fill(self.cor_foto)
        self.pixels.show()

    def modo_pattern(self):
        """Volta ao pattern aesthetic."""
        self._modo = "pattern"

    def apagar(self):
        """Apaga todos os LEDs."""
        self._modo = "foto"  # mantem fora do pattern
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    def flash(self):
        """Flash branco rápido no momento da captura."""
        self.pixels.fill((255, 255, 255))
        self.pixels.show()
        time.sleep(0.15)
        self.pixels.fill(self.cor_foto)
        self.pixels.show()

    def parar(self):
        self._rodando = False
        self.pixels.fill((0, 0, 0))
        self.pixels.show()

    # ── Loop de pattern em background ────────
    def _loop(self):
        while self._rodando:
            if self._modo != "pattern":
                time.sleep(0.05)
                continue

            if self.pattern == "rainbow":
                self._rainbow()
                self._offset = (self._offset + 1) % 256

            elif self.pattern == "breathing":
                self._breathing()
                self._brilho_v += self._brilho_d * 4
                if self._brilho_v >= 255:
                    self._brilho_v = 255
                    self._brilho_d = -1
                elif self._brilho_v <= 0:
                    self._brilho_v = 0
                    self._brilho_d = 1

            elif self.pattern == "chase":
                self._chase()
                self._offset = (self._offset + 1) % self.qtd

            elif self.pattern == "solid":
                self.pixels.fill(self.cor_pattern)
                self.pixels.show()
                time.sleep(0.2)
                continue

            time.sleep(self.velocidade)

    # ── Patterns ──────────────────────────────
    def _wheel(self, pos):
        pos = pos % 256
        if pos < 85:
            return (pos * 3, 255 - pos * 3, 0)
        elif pos < 170:
            pos -= 85
            return (255 - pos * 3, 0, pos * 3)
        else:
            pos -= 170
            return (0, pos * 3, 255 - pos * 3)

    def _rainbow(self):
        for i in range(self.qtd):
            self.pixels[i] = self._wheel((i * 256 // self.qtd + self._offset) % 256)
        self.pixels.show()

    def _breathing(self):
        r, g, b = self.cor_pattern
        f = self._brilho_v / 255
        self.pixels.fill((int(r * f), int(g * f), int(b * f)))
        self.pixels.show()

    def _chase(self):
        self.pixels.fill((0, 0, 0))
        for k in range(3):
            self.pixels[(self._offset + k) % self.qtd] = self.cor_pattern
        self.pixels.show()


def inicializar_leds(config):
    """Retorna LEDController ou None se desativado/sem biblioteca."""
    if not config.get("leds", {}).get("ativar", False):
        return None
    try:
        return LEDController(config)
    except ImportError:
        print("AVISO: neopixel/board nao encontrado — LEDs desativados.")
        print("   Instale com: pip3 install rpi_ws281x adafruit-circuitpython-neopixel")
        return None
    except Exception as e:
        print(f"AVISO: LED falhou ({e}) — continuando sem LED.")
        return None


# ─────────────────────────────────────────────
# Abstracao de Camera (Camera Module 3 ou webcam USB)
# ─────────────────────────────────────────────
class Camera:
    """Suporta Camera Module 3 via picamera2 (Linux) ou webcam USB (fallback/Windows)."""

    def __init__(self, largura=1280, altura=960):
        self.largura = largura
        self.altura = altura
        self.tipo = None
        self.picam2 = None
        self.cap = None
        self._inicializar()

    def _inicializar(self):
        # No Linux tenta picamera2 primeiro (Camera Module 3)
        if sys.platform != "win32":
            try:
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                cfg = self.picam2.create_preview_configuration(
                    main={"size": (self.largura, self.altura)}
                )
                self.picam2.configure(cfg)
                self.picam2.start()
                time.sleep(2)  # aguarda estabilizar exposicao automatica
                self.tipo = "picamera2"
                print("✅ Camera Module 3 inicializada via picamera2!")
                return
            except ImportError:
                print("⚠️  picamera2 nao encontrado. Tentando webcam USB...")
            except Exception as e:
                print(f"⚠️  picamera2 falhou ({e}). Tentando webcam USB...")

        # Fallback: webcam USB (tambem funciona no Windows)
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            raise RuntimeError(
                "Camera nao encontrada!\n"
                "   Verifique:\n"
                "   - Camera Module 3 conectada no conector CSI\n"
                "   - Camera habilitada: sudo raspi-config > Interface Options > Camera\n"
                "   - picamera2 instalado: sudo apt install python3-picamera2\n"
                "   Ou para webcam USB: verifique a conexao USB"
            )
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.largura)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.altura)
        self.tipo = "opencv"
        print("✅ Webcam USB inicializada!")

    def read(self):
        """Retorna (True, frame_bgr) ou (False, None)."""
        if self.tipo == "picamera2":
            try:
                # Captura como PIL Image (sempre RGB correto) e converte para BGR
                img_pil = self.picam2.capture_image("main")
                frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
                return True, frame
            except Exception:
                return False, None
        else:
            return self.cap.read()

    def release(self):
        if self.tipo == "picamera2" and self.picam2:
            self.picam2.stop()
            self.picam2.close()
        elif self.cap:
            self.cap.release()


# ─────────────────────────────────────────────
# Carrega config.json
# ─────────────────────────────────────────────
def carregar_config():
    pasta = os.path.dirname(os.path.abspath(__file__))
    caminho = os.path.join(pasta, "config.json")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print("ERRO: config.json nao encontrado!")
        print(f"   Procurei em: {caminho}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERRO: config.json com erro: {e}")
        sys.exit(1)


# ─────────────────────────────────────────────
# Conecta na impressora USB (ESC/POS)
# ─────────────────────────────────────────────
def conectar_impressora(config):
    """Conecta na impressora termica via USB (ESC/POS)."""
    try:
        from escpos.printer import Usb
        vendor = int(config["impressora"]["vendor_id"], 16)
        product = int(config["impressora"]["product_id"], 16)
        impressora = Usb(vendor, product)
        print(f"OK Impressora conectada! (vendor={hex(vendor)}, product={hex(product)})")
        return impressora
    except Exception as e:
        print(f"AVISO: Impressora nao conectada: {e}")
        print("   Dicas para Raspberry Pi:")
        print("   - Execute: lsusb  (para ver o vendor_id e product_id corretos)")
        print("   - Verifique se as regras udev foram instaladas: ./install_rpi.sh")
        print("   - O usuario deve estar no grupo 'plugdev': sudo usermod -a -G plugdev $USER")
        print("   Continuando em MODO TESTE (salva imagem em vez de imprimir)")
        return None


# ─────────────────────────────────────────────
# Ajuste automatico de brilho e contraste
# ─────────────────────────────────────────────
def auto_ajuste(img_pil, config):
    """Normaliza brilho e contraste automaticamente para diferentes pessoas/iluminacoes."""
    cfg = config.get("ajuste_auto", {})
    if not cfg.get("ativar", True):
        return img_pil

    # Auto contraste: estica o histograma ignorando os X% mais escuros e mais claros
    if cfg.get("auto_contraste", True):
        cutoff = cfg.get("cutoff", 1)
        img_pil = ImageOps.autocontrast(img_pil, cutoff=cutoff)

    # Ajuste de brilho
    brilho = cfg.get("brilho", 1.0)
    if brilho != 1.0:
        img_pil = ImageEnhance.Brightness(img_pil).enhance(brilho)

    # Ajuste de saturacao (cores mais ou menos vibrantes)
    saturacao = cfg.get("saturacao", 1.0)
    if saturacao != 1.0:
        img_pil = ImageEnhance.Color(img_pil).enhance(saturacao)

    return img_pil


# ─────────────────────────────────────────────
# Prepara a foto (recorte + moldura)
# ─────────────────────────────────────────────
def preparar_foto(frame_bgr, config):
    """Recebe frame OpenCV (BGR), retorna PIL Image pronta."""
    foto_w = config["foto"]["largura"]
    foto_h = config["foto"]["altura"]
    moldura = config["foto"]["moldura"]
    borda = config["foto"]["espessura_moldura"] if moldura else 0

    # OpenCV BGR -> PIL RGB
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(frame_rgb)

    # Recorta proporcao
    target_ratio = foto_w / foto_h
    src_ratio = img.width / img.height

    if src_ratio > target_ratio:
        new_w = int(img.height * target_ratio)
        offset = (img.width - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, img.height))
    else:
        new_h = int(img.width / target_ratio)
        offset = (img.height - new_h) // 2
        img = img.crop((0, offset, img.width, offset + new_h))

    img = img.resize((foto_w, foto_h), Image.LANCZOS)

    # Ajuste automatico de brilho e contraste
    img = auto_ajuste(img, config)

    # Moldura
    if borda > 0:
        framed = Image.new("RGB", (foto_w + borda * 2, foto_h + borda * 2), "black")
        framed.paste(img, (borda, borda))
        return framed

    return img


# ─────────────────────────────────────────────
# Prepara a logo
# ─────────────────────────────────────────────
def preparar_logo(config):
    if not config["logo"]["ativar"]:
        return None

    pasta = os.path.dirname(os.path.abspath(__file__))
    caminho = os.path.join(pasta, config["logo"]["arquivo"])

    if not os.path.exists(caminho):
        print(f"AVISO: Logo nao encontrada: {caminho}")
        return None

    img = Image.open(caminho).convert("RGBA")
    prop = config["logo"]["largura"] / img.width
    img = img.resize((config["logo"]["largura"], int(img.height * prop)), Image.LANCZOS)

    fundo = Image.new("RGB", img.size, "white")
    if img.mode == "RGBA":
        fundo.paste(img, mask=img.split()[3])
    else:
        fundo.paste(img)
    return fundo


def alimentar(impressora, n):
    for _ in range(n):
        impressora.text("\n")


def aplicar_texto(impressora, cfg):
    """Aplica configuracoes ESC/POS nativas e imprime o texto."""
    tam = cfg.get("tamanho", "normal").lower()
    fonte = cfg.get("fonte", "a").lower()

    # Font C (indice 2) nao esta no perfil padrao — envia comando raw ESC M 2
    if fonte == "c":
        impressora._raw(b"\x1b\x4d\x02")
        impressora.set(
            align=cfg.get("alinhamento", "center"),
            bold=cfg.get("negrito", False),
            double_width=tam in ("grande", "largo"),
            double_height=tam in ("grande", "alto"),
        )
    else:
        impressora.set(
            align=cfg.get("alinhamento", "center"),
            bold=cfg.get("negrito", False),
            font=fonte,
            double_width=tam in ("grande", "largo"),
            double_height=tam in ("grande", "alto"),
        )

    impressora.textln(cfg["conteudo"])
    # Reset: volta Font A
    impressora._raw(b"\x1b\x4d\x00")
    impressora.set(align="left", bold=False, double_width=False, double_height=False)


# ─────────────────────────────────────────────
# Imprime via ESC/POS
# ─────────────────────────────────────────────
def imprimir(impressora, foto_pil, config):
    """Envia texto nativo ESC/POS + imagens pra impressora."""
    espacos = config.get("espacamentos", {})
    logo = preparar_logo(config)
    cfg_acima = config.get("texto_acima", {})
    cfg_abaixo = config.get("texto_abaixo", {})
    cfg_rodape = config.get("rodape", {})

    try:
        # 1. Logo
        if logo:
            impressora.set(align="center")
            impressora.image(logo)
            alimentar(impressora, espacos.get("apos_logo", 1))

        # 2. Texto acima
        if cfg_acima.get("conteudo"):
            aplicar_texto(impressora, cfg_acima)
            alimentar(impressora, espacos.get("apos_texto_acima", 1))

        # 3. Foto
        impressora.set(align="center")
        impressora.image(foto_pil)
        alimentar(impressora, espacos.get("apos_foto", 1))

        # 4. Texto abaixo
        if cfg_abaixo.get("conteudo"):
            aplicar_texto(impressora, cfg_abaixo)
            alimentar(impressora, espacos.get("apos_texto_abaixo", 1))

        # 5. Rodape
        if cfg_rodape.get("conteudo"):
            aplicar_texto(impressora, cfg_rodape)

        # 6. Corte
        alimentar(impressora, espacos.get("margem_inferior", 3))
        impressora.cut()

        print("OK Impresso!")
        return True

    except Exception as e:
        print(f"ERRO na impressao: {e}")
        return False


# ─────────────────────────────────────────────
# Salva como teste (quando sem impressora)
# ─────────────────────────────────────────────
def salvar_teste(foto_pil, config):
    pasta = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(pasta, "testes"), exist_ok=True)
    nome = f"teste_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    foto_pil.save(os.path.join(pasta, "testes", f"{nome}.png"))

    cfg_acima = config.get("texto_acima", {})
    cfg_abaixo = config.get("texto_abaixo", {})
    cfg_rodape = config.get("rodape", {})

    log = [
        "=== SIMULACAO ===",
        "",
        f"[TEXTO] {cfg_acima.get('conteudo', '')}  (negrito={cfg_acima.get('negrito')}, tam={cfg_acima.get('tamanho')})",
        f"[FOTO]  {foto_pil.size[0]}x{foto_pil.size[1]}px",
        f"[TEXTO] {cfg_abaixo.get('conteudo', '')}",
        f"[RODAPE] {cfg_rodape.get('conteudo', '')}",
        "",
        "=== FIM ===",
    ]

    with open(os.path.join(pasta, "testes", f"{nome}.txt"), "w") as f:
        f.write("\n".join(log))

    print(f"TESTE salvo em testes/{nome}.png")


# ─────────────────────────────────────────────
# Countdown na janela do OpenCV
# ─────────────────────────────────────────────
def mostrar_countdown(camera, segundos, window_name, leds=None):
    """Mostra countdown sobreposto no preview. Sincroniza com LEDs se disponivel."""
    for i in range(segundos, 0, -1):
        if leds:
            leds.modo_foto()  # acende no inicio de cada numero

        t_start = time.time()
        while time.time() - t_start < 0.8:
            ret, frame = camera.read()
            if not ret:
                continue
            frame = cv2.flip(frame, 1)  # Espelho

            # Overlay escuro
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (frame.shape[1], frame.shape[0]), (0, 0, 0), -1)
            frame = cv2.addWeighted(frame, 0.4, overlay, 0.6, 0)

            # Numero grande no centro
            text = str(i)
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 8
            thickness = 16
            (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
            x = (frame.shape[1] - tw) // 2
            y = (frame.shape[0] + th) // 2
            cv2.putText(frame, text, (x, y), font, scale, (0, 200, 255), thickness, cv2.LINE_AA)

            cv2.imshow(window_name, frame)
            cv2.waitKey(1)

        # Apaga por 0.2s antes do proximo numero
        if leds:
            leds.apagar()
            time.sleep(0.2)

        print(f"   {i}...")

    # Flash branco na tela e nos LEDs
    ret, frame = camera.read()
    if ret:
        flash = np.ones_like(frame) * 255
        cv2.imshow(window_name, flash.astype(np.uint8))
        cv2.waitKey(100)

    if leds:
        leds.flash()

    print("   CLICK!")


# ─────────────────────────────────────────────
# Verifica se botao foi pressionado (teclado ou GPIO)
# ─────────────────────────────────────────────
def verificar_botao_pressionado(key):
    """Retorna True se ESPACO (teclado) ou botao GPIO foi pressionado."""
    if key == ord(" "):
        return True
    if botao_gpio and botao_gpio.is_pressed:
        return True
    return False


# ─────────────────────────────────────────────
# Loop principal
# ─────────────────────────────────────────────
def main():
    print()
    print("=" * 45)
    print("   RECEIPT PHOTOBOOTH - RASPBERRY PI 4")
    print("=" * 45)
    print("   ESPACO = tirar foto e imprimir")
    print("   Q / ESC = sair")
    print("=" * 45)
    print()

    config = carregar_config()
    print(f"Evento: {config.get('evento', {}).get('nome', '-')}")
    print(f"   Impressora: {'58mm' if config['impressora']['largura_pixels'] == 384 else '80mm'}")
    print(f"   Texto acima: \"{config.get('texto_acima', {}).get('conteudo', '')}\"")
    print(f"   Texto abaixo: \"{config.get('texto_abaixo', {}).get('conteudo', '')}\"")
    print(f"   Rodape: \"{config.get('rodape', {}).get('conteudo', '')}\"")
    print(f"   Foto: {config['foto']['largura']}x{config['foto']['altura']}px")
    print(f"   Countdown: {config.get('countdown', {}).get('segundos', 3)}s")
    print(f"   Modo teste: {'SIM' if config['modo_teste'] else 'NAO'}")
    print()

    # Inicializa LEDs
    leds = inicializar_leds(config)

    # Tenta conectar impressora
    impressora_inicial = None
    if not config["modo_teste"]:
        impressora_inicial = conectar_impressora(config)
    else:
        print("MODO TESTE ativo - nao vai imprimir, salva imagem")

    print()

    # Inicializa camera
    print("Inicializando camera...")
    try:
        camera = Camera(largura=1280, altura=960)
    except RuntimeError as e:
        print(f"ERRO: {e}")
        sys.exit(1)

    window_name = "Photobooth - ESPACO para foto | Q para sair"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 800, 600)

    print()
    print("-" * 45)
    print("  Aperte ESPACO pra tirar foto!")
    print("-" * 45)
    print()

    em_execucao = False

    while True:
        ret, frame = camera.read()
        if not ret:
            continue

        # Espelho (mais natural para preview)
        display = cv2.flip(frame, 1)

        # Instrucao na tela
        if not em_execucao:
            cv2.putText(
                display,
                "Aperte ESPACO",
                (20, display.shape[0] - 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 200, 255),
                2,
                cv2.LINE_AA,
            )

        cv2.imshow(window_name, display)
        key = cv2.waitKey(1) & 0xFF

        # Q ou ESC = sair
        if key in (ord("q"), 27):
            break

        # ESPACO ou botao GPIO = foto
        if verificar_botao_pressionado(key) and not em_execucao:
            em_execucao = True

            print("\n" + "=" * 45)
            print("ESPACO! Iniciando...")
            print("=" * 45)

            # Countdown
            segundos = config.get("countdown", {}).get("segundos", 3)
            print(f"Countdown: {segundos}s...")
            mostrar_countdown(camera, segundos, window_name, leds)

            # Captura frame real (sem espelho, resolucao total)
            ret, foto_frame = camera.read()
            if not ret:
                print("ERRO ao capturar foto")
                em_execucao = False
                continue

            # Prepara a foto
            foto_pil = preparar_foto(foto_frame, config)
            print(f"OK Foto capturada ({foto_pil.size[0]}x{foto_pil.size[1]}px)")

            # Mostra foto capturada por 1.5s
            foto_display = cv2.cvtColor(np.array(foto_pil), cv2.COLOR_RGB2BGR)
            h_disp = 500
            w_disp = int(h_disp * foto_pil.size[0] / foto_pil.size[1])
            foto_display = cv2.resize(foto_display, (w_disp, h_disp))
            cv2.imshow(window_name, foto_display)
            cv2.waitKey(1500)

            # Imprime ou salva
            if not config["modo_teste"]:
                print("Enviando pra impressora...")
                imp = conectar_impressora(config)
                if imp:
                    imprimir(imp, foto_pil, config)
                    try:
                        imp.close()
                    except Exception:
                        pass
                else:
                    salvar_teste(foto_pil, config)
            else:
                salvar_teste(foto_pil, config)

            # Volta o pattern dos LEDs
            if leds:
                leds.modo_pattern()

            print("\nPronto pro proximo! Aperte ESPACO...\n")
            em_execucao = False

    # Limpeza
    camera.release()
    cv2.destroyAllWindows()
    if leds:
        leds.parar()
    print("\nPhotobooth encerrado!")


if __name__ == "__main__":
    main()
