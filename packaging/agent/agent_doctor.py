"""Chequeo del agente (dsh) que `sifi doctor` anexa al final.

Decisión de empaquetado (M10, ver `packaging/agent/README.md`): el agente **no**
se embebe con su runtime. Se embarca el código del agente (perfil de dsh, bundle
`sifi-tools`, persona y las 7 tools) y se declaran **Node 22+ y dsh como
prerrequisito**, porque el árbol de dsh pesa 884 MB (621 paquetes) y el runtime
de Node otros 123-205 MB: el `.deb` pasaría de 62 MB a ~300 MB (contra D2).

Este módulo no importa nada del core y no falla nunca por sí mismo: informa. La
única salida "dura" es `1` cuando el agente **está incluido** en el bundle y su
runtime no sirve, que es exactamente lo que `sifi doctor` debe hacer visible.

Se usa desde `packaging/pyinstaller/sifid_entry.py` (rama `sifi`) y también se
puede correr suelto:  python3 packaging/agent/agent_doctor.py [<bundle>]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

DSH_PIN = "0.2.1-rc.2"
NODE_MIN = (22, 0)
CHECK_TIMEOUT = 40


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], env: dict | None = None, cwd: str | None = None):
    """(rc, salida) sin explotar si el binario no existe."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=CHECK_TIMEOUT,
            env=env, cwd=cwd,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "no existe"
    except subprocess.TimeoutExpired:
        return 124, f"timeout ({CHECK_TIMEOUT}s)"
    except OSError as exc:  # pragma: no cover - defensivo
        return 126, str(exc)


def _node_version(exe: str) -> tuple[int, ...] | None:
    rc, out = _run([exe, "-v"])
    if rc != 0:
        return None
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else None


def _find_node() -> str | None:
    for cand in (os.environ.get("SIFI_NODE"), "node", "nodejs"):
        if not cand:
            continue
        path = shutil.which(cand) or (cand if os.path.isabs(cand) and os.path.exists(cand) else None)
        if path:
            return path
    return None


def agent_root(bundle_root: str | None) -> str | None:
    """Carpeta `agent/` del bundle (código que viaja en el instalable)."""
    if not bundle_root:
        return None
    cand = os.path.join(bundle_root, "agent")
    return cand if os.path.isdir(cand) else None


def agent_home(bundle_root: str | None) -> str:
    """DSH_HOME del producto, en orden: env → home instalado → el del bundle.

    El bundle vive en `/opt/sifi-desk` (root), así que el `npm ci` del harness va
    a `~/.sifi/agent` (`install.sh`). Si el usuario igual instaló ahí adentro, se
    usa el del bundle.
    """
    env = os.environ.get("SIFI_AGENT_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    user_home = os.path.join(os.path.expanduser("~"), ".sifi", "agent")
    if os.path.isdir(os.path.join(user_home, "dsh")):
        return user_home
    if bundle_root and os.path.isdir(os.path.join(bundle_root, "agent", "dsh")):
        return os.path.join(bundle_root, "agent")
    return user_home


def _find_dsh(home: str) -> str | None:
    env = os.environ.get("SIFI_DSH")
    if env and os.path.exists(env):
        return env
    local = os.path.join(home, "dsh", "node_modules", ".bin", "dsh")
    if os.path.exists(local):
        return local
    return shutil.which("dsh")


def _install_hint(root: str) -> str:
    """`install.sh` del bundle, o el del repo cuando se corre desde fuente."""
    local = os.path.join(root, "install.sh")
    if os.path.exists(local):
        return local
    return os.path.join(os.path.dirname(root), "packaging", "agent", "install.sh")


def _harness_installed(home: str) -> bool:
    dsh = os.path.join(home, "dsh")
    for rel in (
        "node_modules/@deepseek-ai/dsh-tools",
        "node_modules/@deepseek-ai/dsh-base",
        "node_modules/sifi-tools",
    ):
        if not os.path.isdir(os.path.join(dsh, rel)):
            return False
    return True


# --------------------------------------------------------------------------- #
# reporte
# --------------------------------------------------------------------------- #
def report(bundle_root: str | None, out=print) -> int:
    """Imprime el bloque del agente. Devuelve 0 (ok/omitido) o 1 (roto)."""
    root = agent_root(bundle_root)
    if not root:
        out("· agente: no incluido en este bundle (build --cli-only o sin agent/)")
        return 0

    files = ["dsh/profiles/sifi/package.json", "dsh/bundles/sifi-tools/index.mjs",
             "src/tools.mjs", "prompts/system.md"]
    missing = [f for f in files if not os.path.exists(os.path.join(root, f))]
    if missing:
        out(f"✗ agente: bundle incompleto, falta {', '.join(missing)}")
        return 1

    home = agent_home(bundle_root)
    problems: list[str] = []

    node = _find_node()
    if not node:
        out("✗ agente: falta Node.js 22+ (runtime de dsh, no va embebido)")
        out("    Debian/Ubuntu: instalá nodejs>=22 (nodesource) · o exportá SIFI_NODE=<ruta>")
        problems.append("node")
    else:
        ver = _node_version(node)
        if not ver or ver[:2] < NODE_MIN:
            out(f"✗ agente: Node {'.'.join(map(str, ver or (0,)))} en {node}; hace falta >= "
                f"{NODE_MIN[0]}.{NODE_MIN[1]}")
            problems.append("node")
        else:
            out(f"✓ agente: node {'v' + '.'.join(map(str, ver))} ({node})")

    dsh = _find_dsh(home)
    if not dsh:
        out(f"✗ agente: falta el harness dsh {DSH_PIN} (npm i -g @deepseek-ai/dsh@{DSH_PIN}"
            f" o corré {_install_hint(root)})")
        problems.append("dsh")
    else:
        rc, txt = _run([dsh, "--version"])
        got = txt.strip().splitlines()[0] if txt.strip() else "?"
        if rc != 0:
            out(f"✗ agente: `{dsh} --version` falló: {txt.strip()[:200]}")
            problems.append("dsh")
        elif got != DSH_PIN:
            out(f"! agente: dsh {got} != pin {DSH_PIN} ({dsh}) — el bundle sifi-tools "
                f"declara engines.dsh y puede saltearse con warning")
        else:
            out(f"✓ agente: dsh {got} ({dsh})")

    if _harness_installed(home):
        out(f"✓ agente: harness instalado en {home}")
    else:
        out(f"✗ agente: harness sin instalar en {home} (falta node_modules de dsh)")
        out(f"    corré:  {_install_hint(root)}")
        problems.append("harness")

    # La prueba que vale: que el perfil monte de verdad desde ESTE bundle.
    if not problems:
        env = dict(os.environ)
        env["DSH_HOME"] = os.path.join(home, "dsh")
        env.pop("DEEPSEEK_API_KEY", None)
        rc, txt = _run([dsh, "--profile", "sifi", "--dump-config"], env=env,
                       cwd=env["DSH_HOME"])
        if rc != 0:
            out("✗ agente: el perfil `sifi` no monta:")
            for line in txt.strip().splitlines()[:6]:
                out("    " + line)
            problems.append("profile")
        else:
            n_tools = len(re.findall(r"^- id: sifi-tools", txt, re.M))
            out(f"✓ agente: perfil `sifi` monta · bundle sifi-tools ×{max(n_tools, 1)} · "
                f"7 tools · DSH_HOME={env['DSH_HOME']}")

    if problems:
        out(f"    → el instalable trae el agente pero no puede correr ({', '.join(problems)})")
        return 1
    return 0


def default_root() -> str | None:
    """Raíz del repo (`packaging/agent/` → repo): para correr desde fuente."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = args[0] if args else None
    return report(root or default_root())


if __name__ == "__main__":
    sys.exit(main())
