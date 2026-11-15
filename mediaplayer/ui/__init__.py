"""Oberfläche. Die Klassen werden erst bei Bedarf geladen, damit der
Startbildschirm (``ui.splash``) erscheint, bevor Qt Multimedia und numpy
geladen sind."""

__all__ = ["KeyConfigDialog", "MainWindow"]


def __getattr__(name: str):
    if name == "MainWindow":
        from .main_window import MainWindow

        return MainWindow
    if name == "KeyConfigDialog":
        from .key_config_dialog import KeyConfigDialog

        return KeyConfigDialog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
