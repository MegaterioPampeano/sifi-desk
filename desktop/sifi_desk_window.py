#!/usr/bin/env python3
"""Ventana nativa para siFi Desk: GTK3 + WebKitGTK sobre la interfaz local.

Muestra la misma UI que el navegador, pero como una aplicación más: ventana propia,
título propio, sin barra de direcciones ni pestañas. No agrega dependencias nuevas en
Ubuntu de escritorio (git y webkit2gtk-4.1 ya vienen con el sistema).

    sifi_desk_window.py http://127.0.0.1:8790/?token=...
"""
from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gtk, WebKit2  # noqa: E402

TITULO = "siFi Desk"


class Ventana(Gtk.Window):
    def __init__(self, url: str) -> None:
        super().__init__(title=TITULO)
        # en la tele (1360x768) una ventana fija se sale de pantalla: nos adaptamos
        pantalla = Gdk.Screen.get_default()
        ancho = int(pantalla.get_width() * 0.96) if pantalla else 1280
        alto = int(pantalla.get_height() * 0.92) if pantalla else 840
        self.set_default_size(min(1320, ancho), min(900, alto))
        self.set_position(Gtk.WindowPosition.CENTER)

        # sin caché de documentos: la UI se actualiza con el programa y un reinicio
        # tiene que traer el JS nuevo, no el que quedó en disco
        try:
            WebKit2.WebContext.get_default().set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        except Exception:
            pass

        self.base_url = url
        self.web = WebKit2.WebView()
        self.web.load_uri(url)
        self.add(self.web)

        self.web.connect("load-failed", self._fallo)
        # Los links con target="_blank" (papers de Novedades) no hacen nada en WebKitGTK:
        # hay que decidir explícitamente si se abren adentro o en el navegador del sistema.
        self.web.connect("decide-policy", self._politica)
        if os.environ.get("SIFI_UI_DEBUG"):
            # consola del WebView al stdout: sirve para depurar la interfaz sin
            # abrir las herramientas de desarrollo (el nombre del signal cambió
            # entre versiones de WebKitGTK)
            for _sig in ("console-message", "write-console-message"):
                try:
                    self.web.connect(_sig, self._consola)
                    break
                except TypeError:
                    continue
        self.connect("destroy", Gtk.main_quit)

    def _consola(self, _web, _fuente, linea, mensaje):
        print(f"[ui] {mensaje} ({linea})", flush=True)
        return False

    def _politica(self, _web, decision, tipo):
        if tipo == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            nav = decision.get_navigation_action()
            uri = nav.get_request().get_uri() if nav else ""
            if uri:
                decision.ignore()
                self._externo(uri)
                return True
        if tipo == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            nav = decision.get_navigation_action()
            uri = nav.get_request().get_uri() if nav else ""
            # sólo dejamos navegar dentro de la app; el resto va al navegador
            if uri and not uri.startswith(self.base_url.split("?")[0]):
                decision.ignore()
                self._externo(uri)
                return True
        return False

    def _externo(self, uri: str) -> None:
        try:
            ok = Gtk.show_uri_on_window(self, uri, Gtk.get_current_event_time())
            print(f"[ui] abrir externo {uri}: {ok}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[ui] no pude abrir {uri}: {exc}", flush=True)

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
