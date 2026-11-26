from datetime import datetime

import pytest

from app import avisos, cocina, config

TZ = None


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0, zona: Europe/Madrid}\n"
                 "consumo:\n  aparatos:\n    - {entidad: sensor.shelly_cocina_power, nombre: Cocina}\n"
                 "casa:\n  musica: {entidad: media_player.echo_dot_cocina, nombre: Echo}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


class Clock:
    def __init__(self, when: str):
        self.t = datetime.fromisoformat(when).timestamp()

    def __call__(self):
        return self.t

    def advance(self, minutes: float):
        self.t += minutes * 60


class FakeHA:
    def __init__(self):
        self.watts = 0.0
        self.calls = []
        self.fail = False

    async def state(self, entity):
        return {"state": str(self.watts)}

    async def call(self, domain, service, data):
        if self.fail:
            raise RuntimeError("401 Unauthorized")
        self.calls.append((domain, service, data))


def kitchen(tmp_path, when="2026-11-26T13:00:00+01:00"):
    clock, ha = Clock(when), FakeHA()
    return cocina.Kitchen(ha, tmp_path / "cocina.json", clock=clock), clock, ha


async def run_for(k, clock, minutes, step=0.5):
    for _ in range(int(minutes / step)):
        await k.step()
        clock.advance(step)


def test_defaults_come_from_the_rest_of_the_config():
    assert cocina.power_entity() == "sensor.shelly_cocina_power"
    assert cocina.announce_target() == {"servicio": "notify.alexa_media", "objetivo": "media_player.echo_dot_cocina", "tipo": "announce"}


def test_timers_finish_are_announced_and_survive_a_restart(tmp_path):
    k, clock, ha = kitchen(tmp_path)
    t = k.add_timer(5, "Pasta")
    k.add_timer(0.5)
    assert [x["nombre"] for x in k.view()["temporizadores"]] == ["30 segundos", "Pasta"]  # el que acaba antes, primero
    again = cocina.Kitchen(ha, tmp_path / "cocina.json", clock=clock)
    assert [x["id"] for x in again.timers] == [x["id"] for x in k.timers]
    clock.advance(5)
    import asyncio
    asyncio.run(k.step())
    assert all(x["acabado"] for x in k.timers)
    assert sorted(c[2]["message"] for c in ha.calls) == ["El temporizador 30 segundos ha terminado.",
                                                         "El temporizador Pasta ha terminado."]
    assert ha.calls[0][:2] == ("notify", "alexa_media") and ha.calls[0][2]["target"] == ["media_player.echo_dot_cocina"]
    k.add_time(t["id"], 1)                               # «+1 min» al que suena: un minuto desde ahora
    assert not k._find(t["id"])["acabado"] and k.view()["temporizadores"][-1]["restante_s"] == 60
    k.remove_timer(t["id"])
    clock.advance(16)
    k.tick_timers()
    assert k.timers == []                                # el acabado y sin parar desaparece solo


def test_timer_limits(tmp_path):
    k, _, _ = kitchen(tmp_path)
    for bad in (0, -1, 13 * 60):
        with pytest.raises(ValueError):
            k.add_timer(bad)
    for _ in range(cocina.MAX_TIMERS):
        k.add_timer(1)
    with pytest.raises(ValueError):
        k.add_timer(1)
    with pytest.raises(KeyError):
        k.remove_timer("nada")


@pytest.mark.anyio
async def test_oven_cycling_counts_as_on_and_warns_at_one_and_two_hours(tmp_path):
    k, clock, ha = kitchen(tmp_path)
    # El horno: 2000 W un minuto de cada tres (media ≈ 670 W)
    async def oven(minutes):
        for i in range(int(minutes * 2)):
            ha.watts = 2000 if (i // 2) % 3 == 0 else 0
            await k.step()
            clock.advance(0.5)
    await oven(9)
    assert k.view()["fogon"]["encendido"] is False        # aún sin 10 minutos de media
    await oven(2)
    assert k.view()["fogon"]["encendido"] is True and k.level == ""
    await oven(50)                                         # 61 min encendido
    assert k.level == "aviso" and len(ha.calls) == 1 and "1 hora" in ha.calls[0][2]["message"]
    k.mark_seen()
    assert k.view()["fogon"]["visto"] is True
    await oven(60)                                         # 2 h
    assert k.level == "fuerte" and len(ha.calls) == 2 and k.view()["fogon"]["visto"] is False
    ha.watts = 0
    await run_for(k, clock, 11)                            # se apaga
    assert k.view()["fogon"]["encendido"] is False and k.level == ""


@pytest.mark.anyio
async def test_a_kettle_does_not_count(tmp_path):
    k, clock, ha = kitchen(tmp_path)
    ha.watts = 2000
    await run_for(k, clock, 1)                             # dos minutos a tope…
    ha.watts = 20
    await run_for(k, clock, 120)                           # …y luego la nevera del circuito
    assert k.view()["fogon"]["encendido"] is False and ha.calls == []


@pytest.mark.anyio
async def test_at_night_it_warns_after_fifteen_minutes(tmp_path):
    k, clock, ha = kitchen(tmp_path, "2026-11-27T01:00:00+01:00")
    ha.watts = 1500
    await run_for(k, clock, 16)
    assert k.level == "fuerte" and len(ha.calls) == 1


@pytest.mark.anyio
async def test_a_running_timer_holds_the_warning_until_it_ends(tmp_path):
    k, clock, ha = kitchen(tmp_path)
    k.add_timer(150, "Cocido")
    ha.watts = 1500
    await run_for(k, clock, 130)
    assert k.view()["fogon"]["pausado_por_temporizador"] and k.level == "" and ha.calls == []
    await run_for(k, clock, 21)                            # termina el temporizador
    assert k.level == "fuerte"
    assert [c[2]["message"] for c in ha.calls][:1] == ["El temporizador Cocido ha terminado."] and len(ha.calls) == 2


@pytest.mark.anyio
async def test_echo_failures_are_reported_but_do_not_stop_the_warnings(tmp_path, cfg):
    k, clock, ha = kitchen(tmp_path)
    ha.fail = True
    ha.watts = 1500
    await run_for(k, clock, 62)
    assert k.level == "aviso" and "401" in k.health()["error_anuncio"]
    out = avisos.build(datetime(2026, 11, 26, 14), sources={}, extra={}, lists=[], shelly={}, kitchen=k.health())
    assert any(a["id"] == "cocina:echo" for a in out)
    cfg.write_text(cfg.read_text() + "cocina: {anuncios: false}\n", encoding="utf-8")
    config.load.cache_clear()
    ha.fail = False
    k.add_timer(0.5)
    await run_for(k, clock, 1)
    assert ha.calls == []                                  # sin anuncios si se desactivan


def test_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, menu, reminders, copias
    for mod, name in ((reminders, "r.json"), (menu, "menu.json"), (copias, "copias.json")):
        monkeypatch.setattr(mod, "DATA_PATH", tmp_path / name)
    with TestClient(main.app) as c:
        v = c.post("/api/cocina/temporizadores", json={"minutos": 10, "nombre": "Arroz"}).json()
        t = v["temporizadores"][0]
        assert t["nombre"] == "Arroz" and 590 <= t["restante_s"] <= 600
        assert c.post(f"/api/cocina/temporizadores/{t['id']}/sumar", json={"minutos": 2}).json()["temporizadores"][0]["restante_s"] > 700
        assert c.post("/api/cocina/temporizadores", json={"minutos": "x"}).status_code == 400
        assert c.delete("/api/cocina/temporizadores/nada").status_code == 404
        assert c.delete(f"/api/cocina/temporizadores/{t['id']}").json()["temporizadores"] == []
        assert c.post("/api/cocina/fogon/visto").status_code == 200
        assert "cocina" in c.get("/api/salud").json()


@pytest.fixture
def anyio_backend():
    return "asyncio"
