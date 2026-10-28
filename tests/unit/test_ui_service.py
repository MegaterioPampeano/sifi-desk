"""La UI servida por `sifid`: estática pública + API con token + cableado."""
import os

from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service.app import create_app  # noqa: E402


def test_ui_estatica_y_api_con_token(tmp_path):
    app = create_app(data_dir=str(tmp_path / "d"), panels_root=str(tmp_path / "p"),
                     start_worker=False, token="tok-ui", require_auth=True,
                     ui_dir=os.path.join(ROOT, "ui"))
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        html = c.get("/").text
        assert "Si-Fi" in html or "siFi" in html
        assert "tok-ui" not in html, "el token no puede publicarse en el HTML estático"
        assert c.get("/assets/js/api.js").status_code == 200
        assert c.get("/assets/js/news.js").status_code == 200
        assert c.get("/panels").status_code == 401
        assert c.get("/panels", headers={"x-sifi-token": "tok-ui"}).status_code == 200


def test_cliente_ui_anuncia_token_y_descarga():
    js = open(os.path.join(ROOT, "ui/assets/js/api.js"), encoding="utf-8").read()
    assert "x-sifi-token" in js
    assert "SIFID_TOKEN" in js or "__SIFI_CONFIG__" in js
    assert "/report?fmt=" in js
    assert "/news?" in js
