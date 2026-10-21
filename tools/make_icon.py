"""Erzeugt das App-Symbol: assets/icon.png (1024 px) und assets/icon.ico (Windows).

Aufruf im Projektordner:  python tools/make_icon.py

Die ICO-Datei enthält mehrere Größen als PNG-Daten (von Windows seit Vista
unterstützt). Für macOS erzeugt PyInstaller aus icon.png automatisch eine
.icns-Datei (dafür muss Pillow installiert sein).
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPolygonF

ROOT = Path(__file__).resolve().parents[1]
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # Abgerundetes dunkles Quadrat
    margin = s * 0.04
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(margin, margin, s - 2 * margin, s - 2 * margin), s * 0.2, s * 0.2)
    gradient = QLinearGradient(0, 0, 0, s)
    gradient.setColorAt(0, QColor("#2b2d33"))
    gradient.setColorAt(1, QColor("#17181b"))
    p.fillPath(bg, gradient)

    # Blauer Kreis
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2f6fd6"))
    r = s * 0.31
    p.drawEllipse(QPointF(s / 2, s / 2), r, r)

    # Weißes Play-Dreieck (optisch leicht nach rechts versetzt)
    t = s * 0.17
    cx = s / 2 + t * 0.18
    triangle = QPolygonF([
        QPointF(cx - t * 0.55, s / 2 - t),
        QPointF(cx - t * 0.55, s / 2 + t),
        QPointF(cx + t, s / 2),
    ])
    p.setBrush(QColor("#ffffff"))
    p.drawPolygon(triangle)
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(path: Path) -> None:
    images = [png_bytes(render(size)) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, data in zip(ICO_SIZES, images):
        dim = 0 if size >= 256 else size  # 0 bedeutet 256 px
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    path.write_bytes(header + entries + payload)


def main() -> int:
    QGuiApplication(sys.argv)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    render(1024).save(str(assets / "icon.png"))
    write_ico(assets / "icon.ico")
    print(f"Geschrieben: {assets / 'icon.png'}, {assets / 'icon.ico'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
