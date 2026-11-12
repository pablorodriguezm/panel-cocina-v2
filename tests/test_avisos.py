import time
from datetime import datetime

import pytest

from app import avisos, config

OK = {"data": {}, "stale": False, "error": None}


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield
    config.load.cache_clear()


def build(now=datetime(2026, 11, 12, 10), **kw):
    args = {"sources": {"weather": OK, "prices": OK, "calendar": OK}, "extra": {}, "lists": [], "shelly": {"activo": False, "error": None}}
    return avisos.build(now, **{**args, **kw})


def test_nothing_to_report_when_all_is_well():
    assert build(lists=[{"nombre": "Compra", "updated": time.time() - 3600}, {"nombre": "Casa", "updated": None}],
                 extra={"Fórmula 1": {"ok": True, "error": None}}, shelly={"activo": True, "error": None}) == []


def test_each_problem_gives_one_alert():
    out = build(now=datetime(2027, 1, 10, 10),
                sources={"weather": OK, "prices": {"data": None, "stale": False, "error": "REE sin PVPC"}, "calendar": OK},
                extra={"Barça": {"ok": False, "error": "404"}, "festivos": {"ok": True, "error": None}},
                lists=[{"nombre": "Compra", "updated": time.time() - 3 * 86400}],
                shelly={"activo": True, "error": "Client error '401'\nmás detalle"})
    assert [a["id"] for a in out] == ["gas", "calendario:Barça", "prices", "lista:Compra", "shelly"]
    texts = " ".join(a["texto"] for a in out)
    assert "trimestre nuevo" in texts and "REE sin PVPC" in texts and "hace 3 días" in texts and "más detalle" not in texts


def test_shelly_error_is_ignored_when_not_configured():
    assert build(shelly={"activo": False, "error": "algo"}) == []
