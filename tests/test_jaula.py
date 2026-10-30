"""Pruebas del aislamiento de kernel (bwrap) — F1.b del roadmap.

Si el host no permite namespaces sin privilegios, se saltean: la app sigue andando con
la política sola.
"""
import os
import subprocess
import sys

import pytest

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
sys.path.insert(0, CORE)

from service import jaula, politica, sandbox  # noqa: E402

pytestmark = pytest.mark.skipif(not jaula.disponible(forzar=True),
                                reason="bwrap no disponible en este host")


def correr(cmd, timeout=60):
    return sandbox.correr(cmd, timeout=timeout)


def test_escribe_en_su_carpeta():
    r = correr("touch _test_jaula && test -f _test_jaula && rm _test_jaula && echo ok")
    assert r["ok"] and "ok" in r["salida"], r["salida"]
    assert r.get("jaula") is True


def test_rootfs_minimo():
    r = correr("ls /")
    assert "usr" in r["salida"]
    assert "home" in r["salida"]
    # /home existe como directorio vacío del namespace, no con el home real adentro.
    # Se mira directo por bwrap porque la política prefiere no nombrar /home.
    # bwrap crea los directorios padre de los binds (site-packages vive bajo /home),
    # así que /home/mariano existe como cáscara vacía: lo que importa es que adentro
    # no haya nada del home real.
    # Lo único que existe del home real es la cáscara de directorios padre hasta
    # site-packages (~/.local/lib). Nada de .ssh, .openclaw, .config, Descargas, etc.
    argv = jaula.envolver(["/bin/bash", "-c", "ls -A /home/mariano"], "/tmp",
                          sandbox._entorno())
    out = subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout
    assert set(out.split()) <= {".local"}, out


def test_no_ve_ssh_ni_root():
    for ruta in ("/root", "/home/mariano/.ssh", "/mnt/datos/proyectos/cohete_cfd"):
        with pytest.raises(sandbox.Denegado):
            correr(f"ls {ruta}")


def test_shadow_no_legible():
    # la política lo corta antes; se prueba el kernel por fuera de la política
    env = sandbox._entorno()
    argv = jaula.envolver(["/bin/cat", "/etc/shadow"], "/tmp", env)
    res = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert res.returncode != 0
    assert "root:" not in res.stdout


def test_python_y_datos_andan():
    r = correr("python3 -c 'import Bio; print(\"bio\", Bio.__version__)'")
    assert r["ok"] and "bio" in r["salida"]
    r2 = correr("ls /mnt/datos/biotech | head -1")
    assert r2["ok"] and r2["salida"].strip()


def test_programa_lectura_pero_no_escritura():
    r = correr("ls /mnt/datos/proyectos/sifi-desk/core/service/politica.py")
    assert r["ok"]
    with pytest.raises(sandbox.Denegado):
        correr("touch /mnt/datos/proyectos/sifi-desk/_x")
