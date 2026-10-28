#!/usr/bin/env python3
"""Ventana nativa para siFi Desk: GTK3 + WebKitGTK sobre la interfaz local.

Muestra la misma UI que el navegador, pero como una aplicación más: ventana propia,
título propio, sin barra de direcciones ni pestañas. No agrega dependencias nuevas en
Ubuntu de escritorio (git y webkit2gtk-4.1 ya vienen con el sistema).

    sifi_desk_window.py http://127.0.0.1:8790/?token=...
"""
from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2  # noqa: E402

TITULO = "siFi Desk"


class Ventana(Gtk.Window):
    def __init__(self, url: str) -> None:
        super().__init__(title=TITULO)
        self.set_default_size(1280, 840)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.web = WebKit2.WebView()
        self.web.load_uri(url)
        self.add(self.web)

        self.web.connect("load-failed", self._fallo)
        self.connect("destroy", Gtk.main_quit)

    def _fallo(self, _web, _evento, uri, error):
        dialogo = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE, text="No pude abrir la interfaz",
        )
        dialogo.format_secondary_text(f"{uri}\n{error.message}")
        dialogo.run()
        dialogo.destroy()
        Gtk.main_quit()
        return True


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    Ventana(sys.argv[1]).show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
