# Receipt Photobooth — Simulador PC

## Setup rapido

```bash
pip install -r requirements.txt
python photobooth_pc.py
```

## Controles

- **ESPACO** = tira foto + imprime
- **Q** ou **ESC** = sair

## Impressora

Antes de rodar, descubra o vendor_id e product_id da sua impressora:

**Mac/Linux:**
```bash
lsusb
```
Vai aparecer algo tipo: `ID 0416:5011` — o primeiro eh vendor_id, o segundo product_id.

**Windows:**
Abra o Gerenciador de Dispositivos > Controladores USB > sua impressora > Propriedades > Detalhes > ID do Hardware.

Coloque os valores no `config.json`.

## Modo teste (sem impressora)

No `config.json`, mude:
```json
"modo_teste": true
```
As fotos serao salvas na pasta `testes/` em vez de imprimir.

## Permissoes USB (Mac/Linux)

Se der erro de permissao na impressora, rode com sudo:
```bash
sudo python photobooth_pc.py
```

Ou crie uma regra udev (Linux):
```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5011", MODE="0666"' | sudo tee /etc/udev/rules.d/99-thermal.rules
sudo udevadm control --reload-rules
```
