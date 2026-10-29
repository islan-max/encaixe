"""Gera a imagem de compartilhamento (og.png) e o ícone do iPhone (apple-touch-icon.png).

Não faz parte do app: só precisa rodar de novo se a marca mudar.

    uv run --with pillow python scripts/gerar_imagens.py

Usa fontes do Windows (Segoe UI). Em outro sistema, ajuste os caminhos de FONTE_*.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SAIDA = Path(__file__).resolve().parent.parent / "src" / "encaixe" / "static"
FONTE_NEGRITO = "C:/Windows/Fonts/segoeuib.ttf"
FONTE_NORMAL = "C:/Windows/Fonts/segoeui.ttf"
FUNDO, VERDE, VERDE_CLARO, TEXTO, SUAVE = "#111b21", "#0b6b3a", "#25d366", "#e9edef", "#a6b4bc"


def marca(desenho: ImageDraw.ImageDraw, x: int, y: int, lado: int) -> None:
    """O símbolo do Encaixe (o mesmo do favicon.svg): dois blocos que se encaixam."""
    k = lado / 32
    desenho.rounded_rectangle([x, y, x + lado, y + lado], radius=8 * k, fill=VERDE)
    desenho.rounded_rectangle(
        [x + 5 * k, y + 9 * k, x + 18 * k, y + 23 * k], radius=3.5 * k, fill=VERDE_CLARO
    )
    desenho.rounded_rectangle(
        [x + 14 * k, y + 9 * k, x + 27 * k, y + 23 * k],
        radius=3.5 * k,
        fill="#ffffff",
        outline=VERDE,
        width=max(1, round(2 * k)),
    )


def og() -> None:
    img = Image.new("RGB", (1200, 630), FUNDO)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 18, 630], fill=VERDE_CLARO)
    marca(d, 80, 70, 96)
    d.text((196, 88), "Encaixe", font=ImageFont.truetype(FONTE_NEGRITO, 56), fill=TEXTO)
    titulo = ImageFont.truetype(FONTE_NEGRITO, 92)
    d.text((80, 230), "Dá pra encaixar", font=titulo, fill=TEXTO)
    d.text((80, 330), "às 15h?", font=titulo, fill=VERDE_CLARO)
    corpo = ImageFont.truetype(FONTE_NORMAL, 38)
    d.text((80, 480), "A agenda dos autônomos: o cliente marca sozinho,", font=corpo, fill=SUAVE)
    d.text((80, 530), "você lembra com um toque no WhatsApp.", font=corpo, fill=SUAVE)
    img.save(SAIDA / "og.png", optimize=True)


def icone() -> None:
    img = Image.new("RGB", (180, 180), VERDE)
    marca(ImageDraw.Draw(img), 24, 24, 132)
    img.save(SAIDA / "apple-touch-icon.png", optimize=True)


if __name__ == "__main__":
    og()
    icone()
    print("geradas:", SAIDA / "og.png", SAIDA / "apple-touch-icon.png")
