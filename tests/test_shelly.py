from datetime import datetime

import pytest

from app import calefaccion, config, shelly
from app.energy import HourPrice

URL = "https://shelly.example/v2/users/pp-ltu/TOKEN-SECRETO"
PRICES = [HourPrice(datetime(2026, 11, 9, h), v) for h, v in [(21, 0.20), (22, 0.12)]]


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setenv("SHELLY_TARIFA_URL", URL)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


class Client:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def post(self, url, json, timeout):
        self.calls.append((url, json))
        if self.fail:
            raise RuntimeError(f"no responde {url}")
        return type("R", (), {"raise_for_status": lambda self: None})()


async def prices():
    return PRICES


def test_price_for_the_current_hour_with_taxes(cfg):
    hour, price = shelly.price_for(PRICES, datetime(2026, 11, 9, 21, 40))
    assert hour == datetime(2026, 11, 9, 21) and price == round(calefaccion.electricity_with_taxes(0.20), 5)
    assert shelly.price_for(PRICES, datetime(2026, 11, 9, 23, 5)) is None
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\nshelly_tarifa: {con_impuestos: false}\n", encoding="utf-8")
    config.load.cache_clear()
    assert shelly.price_for(PRICES, datetime(2026, 11, 9, 21, 40))[1] == 0.2


@pytest.mark.anyio
async def test_sends_once_per_hour():
    c = Client()
    s = shelly.Sender(c, prices)
    await s.tick(datetime(2026, 11, 9, 21, 0, 30))
    await s.tick(datetime(2026, 11, 9, 21, 30))
    await s.tick(datetime(2026, 11, 9, 22, 0, 10))
    assert [j["price"] for _, j in c.calls] == [f"{calefaccion.electricity_with_taxes(0.20):.5f}",
                                               f"{calefaccion.electricity_with_taxes(0.12):.5f}"]
    assert c.calls[0][0] == URL
    assert s.status["error"] is None and s.status["ultimo_envio"]["hora"] == "2026-11-09T22:00"


@pytest.mark.anyio
async def test_failure_is_retried_later_and_hides_the_token(monkeypatch):
    c = Client(fail=True)
    s = shelly.Sender(c, prices)
    clock = [1000.0]
    monkeypatch.setattr(shelly.time, "time", lambda: clock[0])
    await s.tick(datetime(2026, 11, 9, 21, 1))
    await s.tick(datetime(2026, 11, 9, 21, 2))  # al minuto no reintenta
    assert len(c.calls) == 1
    assert "TOKEN-SECRETO" not in s.status["error"] and "SHELLY_TARIFA_URL" in s.status["error"]
    clock[0] += shelly.RETRY_S
    c.fail = False
    await s.tick(datetime(2026, 11, 9, 21, 7))  # a los 5 minutos, sí
    assert len(c.calls) == 2 and s.status["error"] is None


@pytest.mark.anyio
async def test_without_price_or_url_nothing_is_sent(monkeypatch):
    c = Client()
    s = shelly.Sender(c, prices)
    await s.tick(datetime(2026, 11, 9, 23, 0))
    assert c.calls == [] and "Sin precio" in s.status["error"]
    monkeypatch.delenv("SHELLY_TARIFA_URL")
    s2 = shelly.Sender(c, prices)
    await s2.tick(datetime(2026, 11, 9, 21, 0))
    assert c.calls == [] and s2.status["activo"] is False


@pytest.fixture
def anyio_backend():
    return "asyncio"
