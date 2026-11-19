import json
from datetime import datetime

import httpx
import pytest
from urllib.parse import quote

from app import avisos, iptv, tv

USER, PASS = "pablo", "s3cr€t/x"  # con caracteres que se codifican en la URL
QPASS = quote(PASS, safe="")
SERVER = "http://iptv.example:8080"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("IPTV_SERVIDOR", "iptv.example:8080/")
    monkeypatch.setenv("IPTV_USUARIO", USER)
    monkeypatch.setenv("IPTV_CLAVE", PASS)


def api_routes(request):
    q = request.url.params
    if request.url.path == "/player_api.php":
        assert q["username"] == USER and q["password"] == PASS
        action = q.get("action")
        if action is None:
            return httpx.Response(200, json={"user_info": {"auth": 1, "status": "Active", "exp_date": "1798761600",
                                                           "max_connections": "1", "allowed_output_formats": ["m3u8", "ts"]}})
        if action == "get_live_categories":
            return httpx.Response(200, json=[{"category_id": "1", "category_name": "España"},
                                             {"category_id": "2", "category_name": "Deportes"}])
        if action == "get_live_streams":
            return httpx.Response(200, json=[
                {"stream_id": 101, "name": "La 1 HD", "category_id": "1", "stream_icon": "https://logos.example/la1.png"},
                {"stream_id": 202, "name": "Deportes 1", "category_id": "2", "stream_icon": "http://logos.example/d1.png"},
                {"stream_id": "x", "name": "Roto"},
            ])
    path = request.url.raw_path.decode()
    if path.endswith("/101.m3u8"):
        # Como muchos servidores Xtream: la emisión redirige a otro servidor con la clave en la ruta
        return httpx.Response(302, headers={"location": f"http://edge.example/live/{USER}/{QPASS}/101/index.m3u8"})
    if path.startswith("/live/") and path.endswith("/index.m3u8"):
        return httpx.Response(200, text="#EXTM3U\n#EXTINF:6,\nseg-1.ts\n#EXTINF:6,\nhttps://cdn.example/libre/seg-2.ts\n",
                              headers={"content-type": "application/vnd.apple.mpegurl"})
    if path.endswith("seg-1.ts"):
        return httpx.Response(200, content=b"\x47" * 188, headers={"content-type": "video/mp2t"})
    return httpx.Response(404)


def make(handler=api_routes):
    t = tv.TV(httpx.AsyncClient(transport=httpx.MockTransport(handler)), check_public=lambda h: True)
    return t, iptv.IPTV(t.client, t)


def test_not_configured_without_the_three_variables(monkeypatch):
    monkeypatch.delenv("IPTV_CLAVE")
    assert iptv.credentials() is None
    _, lista = make()
    assert not lista.configured and lista.stream_url(101) is None


@pytest.mark.anyio
async def test_lists_live_channels_without_any_secret():
    _, lista = make()
    await lista.refresh()
    out = lista.listing()
    assert [g["nombre"] for g in out["grupos"]] == ["España", "Deportes"]
    assert out["canales"] == [{"id": 101, "n": "La 1 HD", "g": "1", "logo": "https://logos.example/la1.png"},
                              {"id": 202, "n": "Deportes 1", "g": "2"}]  # el logo http no se puede enseñar
    assert out["cuenta"]["caduca"] == "2027-01-01" and out["cuenta"]["conexiones"] == "1"
    text = json.dumps(out, ensure_ascii=False)
    assert PASS not in text and "s3cr" not in text and SERVER not in text


@pytest.mark.anyio
async def test_stream_goes_through_opaque_keys_and_never_shows_the_password():
    t, lista = make()
    await lista.refresh()
    assert lista.stream_url(999) is None  # solo canales de la lista
    url = lista.stream_url(101)
    assert url.startswith(SERVER + "/live/pablo/s3cr%E2%82%ACt%2Fx/")
    body, ctype = await t.fetch(url)
    assert ctype == "application/vnd.apple.mpegurl"
    assert PASS not in body and QPASS not in body and "s3cr" not in body
    lines = [l for l in body.splitlines() if l and not l.startswith("#")]
    assert lines[0].startswith("/api/tv/hls?k=")               # el segmento con la clave en la ruta: ficha
    assert lines[1] == t.link("https://cdn.example/libre/seg-2.ts")  # sin secreto: dirección firmada normal
    assert "s=" in lines[1]
    token = lines[0].split("k=")[1]
    seg = t.unhide(token)
    assert seg == f"http://edge.example/live/{USER}/{QPASS}/101/seg-1.ts" and t.public(seg)
    # La ficha va cifrada (no se ve la clave) y no se puede retocar
    assert "s3cr" not in token and t.unhide(token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]) is None
    stream, _ = await t.fetch(seg)
    assert b"".join([c async for c in stream.aiter_bytes()]) == b"\x47" * 188
    assert t.unhide("0" * 32) is None


@pytest.mark.anyio
async def test_errors_never_carry_the_credentials():
    def bad(request):
        return httpx.Response(500, request=request)
    _, lista = make(bad)
    await lista.refresh()
    assert lista.error.startswith("Mi lista:") and "500" in lista.error
    assert PASS not in lista.error and "s3cr" not in lista.error and USER not in lista.error

    def refused(request):
        return httpx.Response(200, json={"user_info": {"auth": 0}})
    _, lista = make(refused)
    await lista.refresh()
    assert "usuario o la clave" in lista.error


def test_alerts_for_a_broken_or_expiring_list(tmp_path, monkeypatch):
    from app import config
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    now = datetime(2026, 12, 25, 12)
    base = dict(sources={}, extra={}, lists=[], shelly={})
    soon = avisos.build(now, **base, iptv={"configurada": True, "error": None, "caduca": "2027-01-01"})
    assert soon == [{"id": "iptv", "texto": "TV: la suscripción de «Mi lista» caduca en 7 días (2027-01-01)."}]
    assert avisos.build(now, **base, iptv={"configurada": True, "error": None, "caduca": "2027-03-01"}) == []
    broken = avisos.build(now, **base, iptv={"configurada": True, "error": "Mi lista: sin red", "caduca": None})
    assert broken[0]["texto"] == "TV: Mi lista: sin red"
    assert avisos.build(now, **base, iptv={"configurada": False}) == []
    config.load.cache_clear()


def test_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, reminders, menu, copias, config
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    for mod, name in ((reminders, "r.json"), (menu, "menu.json"), (copias, "copias.json")):
        monkeypatch.setattr(mod, "DATA_PATH", tmp_path / name)
    with TestClient(main.app) as c:
        assert c.get("/api/tv/iptv/101").status_code == 404     # canal que no está (aún) en la lista
        assert c.get("/api/tv/hls", params={"k": "nada"}).status_code == 403
        assert c.get("/api/tv/hls").status_code == 400
    monkeypatch.delenv("IPTV_SERVIDOR")
    with TestClient(main.app) as c:
        assert c.get("/api/tv").json()["mi_lista"] is False
        assert c.get("/api/tv/iptv").status_code == 404
    config.load.cache_clear()


@pytest.fixture
def anyio_backend():
    return "asyncio"
