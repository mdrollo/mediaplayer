"""Wiederverwendbare UI-Bausteine für die großen, touch-tauglichen Listen."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QListWidget,
    QScroller,
    QScrollerProperties,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

# Zusätzliche Datenrollen für TwoLineDelegate.
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
BOLD_ROLE = Qt.ItemDataRole.UserRole + 2
PATH_ROLE = Qt.ItemDataRole.UserRole + 3
IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 4
DIMMED_ROLE = Qt.ItemDataRole.UserRole + 5  # z. B. Datei nicht mehr vorhanden

_SELECTED_BG = QColor("#2f6fd6")
_SEPARATOR = QColor("#2a2c31")
_TEXT = QColor("#f2f2f2")
_TEXT_DISABLED = QColor("#6b6f78")
_SUBTEXT = QColor("#b8bcc4")
_SUBTEXT_SELECTED = QColor("#e3eaff")


def enable_touch_scrolling(view: QAbstractItemView) -> None:
    """Mit dem Finger scrollen (mit Schwung); Antippen wählt weiterhin aus."""
    view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    QScroller.grabGesture(view.viewport(), QScroller.ScrollerGestureType.TouchGesture)
    scroller = QScroller.scroller(view.viewport())
    props = scroller.scrollerProperties()
    # Kein "Gummiband"-Überschwingen am Listenanfang und -ende.
    off = QScrollerProperties.OvershootPolicy.OvershootAlwaysOff
    props.setScrollMetric(QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy, off)
    props.setScrollMetric(QScrollerProperties.ScrollMetric.VerticalOvershootPolicy, off)
    scroller.setScrollerProperties(props)


class TwoLineDelegate(QStyledItemDelegate):
    """Zeichnet Einträge mit Symbol, großem Titel und kleiner Zusatzzeile."""

    def __init__(self, parent=None, title_px: int = 30, subtitle_px: int = 20, icon_px: int = 44):
        super().__init__(parent)
        self.title_px = title_px
        self.subtitle_px = subtitle_px
        self.icon_px = icon_px
        self.padding = 14

    def _fonts(self, option: QStyleOptionViewItem, bold: bool) -> tuple[QFont, QFont]:
        title = QFont(option.font)
        title.setPixelSize(self.title_px)
        title.setBold(bold)
        subtitle = QFont(option.font)
        subtitle.setPixelSize(self.subtitle_px)
        return title, subtitle

    def sizeHint(self, option, index) -> QSize:
        title_font, subtitle_font = self._fonts(option, bool(index.data(BOLD_ROLE)))
        height = QFontMetrics(title_font).height()
        if index.data(SUBTITLE_ROLE):
            height += 4 + QFontMetrics(subtitle_font).height()
        height = max(height, self.icon_px if index.data(Qt.ItemDataRole.DecorationRole) else 0)
        return QSize(option.rect.width(), height + 2 * self.padding)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled) and not index.data(DIMMED_ROLE)

        if selected:
            painter.fillRect(rect, _SELECTED_BG)
        painter.setPen(_SEPARATOR)
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        x = rect.left() + self.padding
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon_rect = QRect(x, rect.center().y() - self.icon_px // 2, self.icon_px, self.icon_px)
            mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, mode)
            x += self.icon_px + self.padding

        width = rect.right() - self.padding - x
        title_font, subtitle_font = self._fonts(option, bool(index.data(BOLD_ROLE)))
        title_metrics = QFontMetrics(title_font)
        subtitle = index.data(SUBTITLE_ROLE) or ""
        text_height = title_metrics.height()
        if subtitle:
            text_height += 4 + QFontMetrics(subtitle_font).height()
        y = rect.center().y() - text_height // 2

        painter.setFont(title_font)
        painter.setPen(_TEXT if enabled or selected else _TEXT_DISABLED)
        title = title_metrics.elidedText(str(index.data() or ""), Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRect(x, y, width, title_metrics.height()), Qt.AlignmentFlag.AlignVCenter, title)

        if subtitle:
            sub_metrics = QFontMetrics(subtitle_font)
            painter.setFont(subtitle_font)
            painter.setPen(_SUBTEXT_SELECTED if selected else (_SUBTEXT if enabled else _TEXT_DISABLED))
            text = sub_metrics.elidedText(subtitle, Qt.TextElideMode.ElideMiddle, width)
            sub_y = y + title_metrics.height() + 4
            painter.drawText(QRect(x, sub_y, width, sub_metrics.height()), Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class BigListWidget(QListWidget):
    """Große Liste mit TwoLineDelegate und Touch-Scrollen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bigList")
        self.setItemDelegate(TwoLineDelegate(self))
        self.setUniformItemSizes(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scrolling(self)


def size_dialog(dialog: QDialog, parent: QWidget | None, fraction: float, fullscreen_like_parent: bool) -> None:
    """Dialog passend zum Hauptfenster dimensionieren.

    Ist das Hauptfenster im Vollbild und ``fullscreen_like_parent`` gesetzt,
    öffnet sich der Dialog ebenfalls im Vollbild; sonst nimmt er ``fraction``
    der Fläche ein.
    """
    window = parent.window() if parent is not None else None
    if window is not None and fullscreen_like_parent and window.isFullScreen():
        dialog.setWindowState(Qt.WindowState.WindowFullScreen)
        return
    screen = (window.screen() if window is not None else dialog.screen()).availableGeometry()
    area = window.geometry() if window is not None else screen
    width = max(900, int(area.width() * fraction))
    height = max(650, int(area.height() * fraction))
    dialog.resize(min(width, screen.width()), min(height, screen.height()))
    if window is not None:
        geo = dialog.frameGeometry()
        geo.moveCenter(window.frameGeometry().center())
        dialog.move(geo.topLeft())
