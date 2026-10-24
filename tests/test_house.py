import pytest

from app import config, house

CFG = """
ubicacion: {latitud: 0, longitud: 0}
casa:
  calefaccion:
    termostato: climate.salon
    presets: {schedule: Programa, away: Fuera}
    valvulas: [{entidad: climate.dormitorio, nombre: Dormitorio}]
  aire:
    modos: [off, heat, cool]
    equipos: [{entidad: climate.aire, nombre: Aire}]
  temperaturas: [{entidad: sensor.cocina, nombre: Cocina}]
  musica: {entidad: media_player.echo, nombre: Cocina}
"""


def climate(entity, state="heat", **attrs):
    base = {"hvac_modes": ["off", "heat", "cool", "dry"], "preset_modes": ["schedule", "away", "boost"],
            "min_temp": 7, "max_temp": 30, "target_temp_step": 0.5, "current_temperature": 21.3, "temperature": 21}
    return {"entity_id": entity, "state": state, "attributes": {**base, **attrs}}


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(CFG, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield
    config.load.cache_clear()


def test_build_keeps_only_allowed_modes_and_presets():
    states = {"climate.salon": climate("climate.salon"), "climate.dormitorio": climate("climate.dormitorio"),
              "climate.aire": climate("climate.aire"), "sensor.cocina": {"entity_id": "sensor.cocina", "state": "22.8", "attributes": {}},
              "media_player.echo": {"entity_id": "media_player.echo", "state": "playing",
                                    "attributes": {"media_title": "Purple Rain", "media_artist": "Prince", "volume_level": 0.34}}}
    out = house.build(states)
    assert [p["id"] for p in out["calefaccion"]["termostato"]["presets"]] == ["schedule", "away"]  # boost no está en config
    assert out["calefaccion"]["termostato"]["presets"][0]["nombre"] == "Programa"
    assert [m["id"] for m in out["aire"][0]["modos"]] == ["off", "heat", "cool"]  # dry no está en config
    assert out["aire"][0]["presets"] == []
    assert out["temperaturas"] == [{"nombre": "Cocina", "temp": 22.8}]
    assert out["musica"]["titulo"] == "Purple Rain" and out["musica"]["volumen"] == 0.34


def test_setpoint_is_clamped_and_rounded_to_step():
    st = {"climate.salon": climate("climate.salon")}
    assert house.command("consigna", {"entidad": "climate.salon", "grados": 21.3}, st)[2]["temperature"] == 21.5
    assert house.command("consigna", {"entidad": "climate.salon", "grados": 99}, st)[2]["temperature"] == 30


def test_rejects_entities_and_modes_outside_config():
    st = {"climate.salon": climate("climate.salon"), "climate.otro": climate("climate.otro"), "climate.aire": climate("climate.aire")}
    with pytest.raises(ValueError):
        house.command("consigna", {"entidad": "climate.otro", "grados": 20}, st)
    with pytest.raises(ValueError):
        house.command("preset", {"entidad": "climate.salon", "preset": "boost"}, st)  # la entidad lo tiene, config no
    with pytest.raises(ValueError):
        house.command("modo", {"entidad": "climate.aire", "modo": "dry"}, st)
    with pytest.raises(ValueError):
        house.command("consigna", {"entidad": "climate.salon", "grados": 20}, {"climate.salon": climate("climate.salon", state="unavailable")})


def test_music_commands():
    assert house.command("musica", {"accion": "play_pause"}, {}) == ("media_player", "media_play_pause", {"entity_id": "media_player.echo"})
    assert house.command("musica", {"accion": "volumen", "nivel": 1.7}, {})[2]["volume_level"] == 1.0
    with pytest.raises(ValueError):
        house.command("musica", {"accion": "turn_off"}, {})
