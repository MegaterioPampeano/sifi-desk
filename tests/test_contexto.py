"""Contexto, memoria y compactación (F2 del roadmap)."""
import os
import sys

import pytest

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
sys.path.insert(0, CORE)

from service import charlas, contexto, memoria, sandbox  # noqa: E402


def sesion(n=20, texto="hola", tarjetas=True, resumen=None):
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "texto": f"{texto} {i}"})
        msgs.append({"role": "assistant", "texto": f"respuesta {i}",
                     "herramientas": ([{"nombre": "ejecutar", "args": {"cmd": "ls"},
                                        "resultado": "SALIDA-DE-TOOL", "ok": True}]
                                      if tarjetas else None)})
    s = {"id": "c-test", "mensajes": msgs, "resumen": resumen}
    return s


# ------------------------------------------------------------------ contexto
def test_las_salidas_de_tools_vuelven_al_contexto():
    salida = contexto.turnos_para_llm(sesion(3))
    texto = "\n".join(m["content"] for m in salida)
    assert "SALIDA-DE-TOOL" in texto
    assert "ejecutar(" in texto


def test_resumen_va_primero():
    salida = contexto.turnos_para_llm(sesion(2, resumen="se eligió la ventana 1513-1812"))
    assert salida[0]["role"] == "user"
    assert "1513-1812" in salida[0]["content"]


def test_presupuesto_deja_los_ultimos():
    grande = sesion(40, texto="x" * 2000)
    salida = contexto.turnos_para_llm(grande, presupuesto=5000)
    assert salida, "no debería quedar vacío"
    assert "respuesta 39" in salida[-1]["content"]
    assert contexto.tokens_de(salida) <= 5000 * 1.2


def test_necesita_compactar():
    chica = sesion(2)
    assert not contexto.necesita_compactar(chica, presupuesto=100000)
    grande = sesion(60, texto="y" * 4000)
    assert contexto.necesita_compactar(grande, presupuesto=20000)


# ---------------------------------------------------------------- compactación
def test_compactar_guarda_resumen_y_recorta(tmp_path):
    data_dir = str(tmp_path)
    s = charlas.crear(data_dir)
    for i in range(12):
        charlas.agregar(data_dir, s["id"], "user", f"pedido {i}")
        charlas.agregar(data_dir, s["id"], "assistant", f"hecho {i}")
    info = charlas.compactar(data_dir, s["id"], lambda material: "RESUMEN: " + str(len(material)),
                             vivos=4)
    assert info and info["turnos_resumidos"] == 20 and info["turnos_vivos"] == 4
    g = charlas.obtener(data_dir, s["id"])
    assert g["resumen"].startswith("RESUMEN:")
    assert len(g["mensajes"]) == 4
    assert g["mensajes"][-1]["texto"] == "hecho 11"


def test_compactar_no_rompe_si_el_resumidor_falla(tmp_path):
    data_dir = str(tmp_path)
    s = charlas.crear(data_dir)
    for i in range(8):
        charlas.agregar(data_dir, s["id"], "user", f"p {i}")
        charlas.agregar(data_dir, s["id"], "assistant", f"r {i}")

    def rompe(_):
        raise RuntimeError("modelo caído")

    assert charlas.compactar(data_dir, s["id"], rompe) is None
    assert len(charlas.obtener(data_dir, s["id"])["mensajes"]) == 16


def test_historial_para_llm_incluye_tarjetas(tmp_path):
    data_dir = str(tmp_path)
    s = charlas.crear(data_dir)
    charlas.agregar(data_dir, s["id"], "user", "corré ls")
    charlas.agregar(data_dir, s["id"], "assistant", "listo",
                    herramientas=[{"nombre": "ejecutar", "args": {"cmd": "ls"},
                                   "resultado": "archivo.txt", "ok": True}])
    hist = charlas.historial_para_llm(charlas.obtener(data_dir, s["id"]))
    assert "archivo.txt" in "\n".join(m["content"] for m in hist)


# -------------------------------------------------------------------- memoria
def test_memoria_ida_y_vuelta():
    memoria.asegurar()
    memoria.escribir("hot", "probando memoria hot", agregar=False)
    assert "probando memoria hot" in memoria.leer("hot")
    memoria.escribir("largo", "linea de largo plazo")
    assert "linea de largo plazo" in memoria.leer("largo")
    assert any("largo plazo" in f["texto"].lower() or "largo plazo" in f["texto"]
               for f in memoria.buscar("largo plazo"))
    bloque = memoria.bloque_sistema()
    assert "EN QUÉ ESTOY AHORA" in bloque and "MEMORIA DE LARGO PLAZO" in bloque


def test_memoria_rechaza_nombres_raros():
    with pytest.raises(ValueError):
        memoria.leer("../../etc/passwd")


# --------------------------------------------------------------------- editar
def test_editar_reemplaza_una_vez():
    sandbox.escribir("_edit_test.txt", "alfa beta alfa")
    r = sandbox.editar("_edit_test.txt", "beta", "gamma")
    assert "1 reemplazo" in r
    assert open(os.path.join(sandbox.TRABAJO, "_edit_test.txt")).read() == "alfa gamma alfa"
    with pytest.raises(sandbox.Denegado):
        sandbox.editar("_edit_test.txt", "alfa", "omega")  # ambiguo
    r2 = sandbox.editar("_edit_test.txt", "alfa", "omega", todas=True)
    assert "2 reemplazo" in r2
    os.unlink(os.path.join(sandbox.TRABAJO, "_edit_test.txt"))


def test_editar_fuera_de_la_carpeta_no_se_puede():
    with pytest.raises(sandbox.Denegado):
        sandbox.editar("/mnt/datos/proyectos/sifi-desk/README.md", "a", "b")
