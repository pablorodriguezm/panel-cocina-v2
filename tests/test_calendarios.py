from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app import calendarios, config

MADRID = ZoneInfo("Europe/Madrid")


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


def test_holidays_file_has_14_a_year_without_repeats():
    for year, days in calendarios.holidays_file().items():
        dates = [d["fecha"] for d in days]
        assert len(dates) == 14 == len(set(dates)), year
        assert all(str(d).startswith(year) for d in dates)
        assert Counter(d["ambito"] for d in days)["local"] == 2
        assert {d["ambito"] for d in days} <= set(calendarios.AMBITO)


def test_holidays_in_the_window_are_all_day_and_marked():
    start = datetime(2026, 11, 2, tzinfo=MADRID)
    hs = calendarios.holidays(start, datetime(2026, 11, 23, tzinfo=MADRID))
    assert [(h["start"], h["title"]) for h in hs] == [("2026-11-02", "Todos los Santos (traslado)"),
                                                      ("2026-11-09", "Nuestra Señora de la Almudena")]
    assert all(h["all_day"] and h["festivo"] and h["calendario"] == "Festivos" for h in hs)
    assert hs[1]["description"] == "Festivo local de Madrid" and hs[1]["end"] == "2026-11-10"


def test_missing_year_is_reported():
    assert calendarios.missing_holiday_years(datetime(2027, 12, 27, tzinfo=MADRID)) == [2028]
    assert calendarios.missing_holiday_years(datetime(2026, 10, 28, tzinfo=MADRID)) == []


JOLPICA = {"MRData": {"RaceTable": {"Races": [
    {"raceName": "Brazilian Grand Prix", "date": "2026-11-08", "time": "17:00:00Z",
     "Circuit": {"circuitName": "Autódromo José Carlos Pace", "Location": {"locality": "São Paulo", "country": "Brazil"}},
     "FirstPractice": {"date": "2026-11-06", "time": "14:30:00Z"},
     "SprintQualifying": {"date": "2026-11-06", "time": "18:30:00Z"},
     "Sprint": {"date": "2026-11-07", "time": "14:00:00Z"},
     "Qualifying": {"date": "2026-11-07", "time": "18:00:00Z"}},
]}}}


def test_f1_has_every_session_in_local_time():
    evs = calendarios.f1_from_jolpica(JOLPICA, MADRID)
    assert [e["title"] for e in evs] == ["🏎️ Libres 1 · Brazilian GP", "🏎️ Clasificación sprint · Brazilian GP",
                                         "🏎️ Sprint · Brazilian GP", "🏎️ Clasificación · Brazilian GP", "🏎️ Carrera · Brazilian GP"]
    race = evs[-1]
    assert race["start"] == "2026-11-08T18:00+01:00" and race["end"] == "2026-11-08T20:00+01:00"
    assert race["location"] == "Autódromo José Carlos Pace, São Paulo, Brazil" and not race["all_day"]


ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
    "BEGIN:VEVENT\r\nUID:1\r\nSUMMARY:Real Madrid - FC Barcelona\r\nDTSTART:20261101T200000Z\r\n"
    "DTEND:20261101T220000Z\r\nLOCATION:Santiago Bernab\r\n éu\\, Madrid\r\nDESCRIPTION:LaLiga\\nJornada 11\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:2\r\nSUMMARY:Club Brugge - Real Madrid\r\nDTSTART;TZID=Europe/Brussels:20261104T210000\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nUID:3\r\nSUMMARY:Copa: sorteo\r\nDTSTART;VALUE=DATE:20261105\r\nDTEND;VALUE=DATE:20261106\r\nEND:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_ics_parser_handles_utc_tzid_all_day_and_folded_lines():
    evs = calendarios.parse_ics(ICS, MADRID, calendario="Real Madrid", color="#7A5BC2")
    clasico, brujas, sorteo = evs
    assert clasico["start"] == "2026-11-01T21:00+01:00" and clasico["location"] == "Santiago Bernabéu, Madrid"
    assert clasico["description"] == "LaLiga\nJornada 11" and clasico["color"] == "#7A5BC2"
    assert brujas["start"] == "2026-11-04T21:00+01:00" and brujas["end"] == "2026-11-04T23:00+01:00"  # sin DTEND: 2 h
    assert sorteo["all_day"] and sorteo["start"] == "2026-11-05" and sorteo["end"] == "2026-11-06"


def test_the_clasico_shows_once_but_simultaneous_matches_stay():
    ev = lambda title, start: {"title": title, "start": start}  # noqa: E731
    out = calendarios.dedupe_matches([
        ev("Real Madrid - FC Barcelona", "2026-11-01T21:00+01:00"),
        ev("Real Madrid vs Barcelona", "2026-11-01T21:00+01:00"),
        ev("Real Madrid - Real Betis", "2027-05-23T21:00+02:00"),
        ev("FC Barcelona - Sevilla FC", "2027-05-23T21:00+02:00"),
    ])
    assert [e["title"] for e in out] == ["Real Madrid - FC Barcelona", "Real Madrid - Real Betis", "FC Barcelona - Sevilla FC"]


def test_config_can_turn_things_off(cfg):
    assert [t["nombre"] for t in calendarios.teams()] == ["Real Madrid", "Barça"]
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\ncalendarios_extra: {f1: false, equipos: []}\n", encoding="utf-8")
    config.load.cache_clear()
    assert calendarios.teams() == [] and calendarios.cfg()["f1"] is False


@pytest.mark.anyio
async def test_extra_mixes_sources_and_a_failing_one_does_not_hide_the_rest(monkeypatch):
    class Resp:
        def __init__(self, url):
            self.url = url
            self.text = ICS
        def raise_for_status(self):
            if "barcelona" in self.url:
                raise RuntimeError("caído")
        def json(self):
            return JOLPICA

    class Client:
        async def get(self, url, **kw):
            return Resp(url)

    monkeypatch.setattr(calendarios, "window", lambda now: (datetime(2026, 11, 2, tzinfo=MADRID), datetime(2026, 11, 23, tzinfo=MADRID)))
    out = await calendarios.Extra(Client()).get()
    names = Counter(e["calendario"] for e in out["data"])
    assert names == {"Festivos": 2, "Fórmula 1": 5, "Real Madrid": 2}  # el Clásico del 1 de noviembre queda fuera
    assert out["fuentes"]["Barça"]["ok"] is False and "caído" in out["fuentes"]["Barça"]["error"]
    assert out["fuentes"]["Fórmula 1"]["ok"] and out["fuentes"]["festivos"]["ok"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
