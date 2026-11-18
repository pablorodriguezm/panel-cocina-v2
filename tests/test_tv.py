import httpx
import pytest

from app import config, tv

MD = """## Nacionales

| Canal | M3U8 | Web | Logo | EPG ID | Info |
| - | - | - | - | - | - |
| La 1 | [m3u8 # 1](https://rtve.example/la1/main.m3u8) - [m3u8 # 2](https://ads.example/p.m3u8?ip=[IP]) | [web](https://rtve.example/) | [logo](https://x/l.png) | La1.TV | GEO |
| Cuatro | - | [web](https://mediaset.example/cuatro/) | [logo](https://x/c.png) | Cuatro.TV | EXTA |
| TVG | [m3u8](https://crtvg.example/playlist_dvr.m3u8) - [youtube](https://www.youtube.com/live/x) | [web](https://g/) | [logo](https://x/t.png) | TVGAL.TV | EMB |
"""


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


def test_parse_tdtchannels_keeps_usable_m3u8_only():
    assert tv.parse_tdtchannels(MD) == {"La 1": ["https://rtve.example/la1/main.m3u8"],
                                        "TVG": ["https://crtvg.example/playlist_dvr.m3u8"]}


def test_channels_use_the_list_with_fallback_and_each_kind():
    t = tv.TV(httpx.AsyncClient(), check_public=lambda h: True)
    t.streams = tv.parse_tdtchannels(MD)
    chans = {c["id"]: c for c in t.channels()}
    assert list(chans)[:4] == ["la1", "la2", "antena3", "lasexta"]
    assert chans["la1"]["fuentes"][0] == tv.proxied("https://rtve.example/la1/main.m3u8")
    assert chans["la1"]["fuentes"][-1] == tv.proxied(tv.CANALES[0]["reserva"])  # la de reserva, al final
    assert chans["la2"]["fuentes"] == [tv.proxied(tv.CANALES[1]["reserva"])]   # no está en la lista: solo la reserva
    assert chans["antena3"]["embed"] == "https://www.atresplayer.com/embed/live/antena3/"
    assert chans["laseptima"]["embed"].startswith("https://www.youtube.com/embed/live_stream?channel=")
    assert chans["telecinco"]["tipo"] == "web" and "fuentes" not in chans["telecinco"]
    assert t.permitted("https://rtve.example/la1/main.m3u8") and t.permitted("https://crtvg.example/x/seg.ts")


def test_config_can_choose_the_channels(cfg):
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\ntv:\n  canales:\n"
                   "    - {id: mi, nombre: Mi canal, tipo: hls, urls: ['https://mi.example/a.m3u8']}\n", encoding="utf-8")
    config.load.cache_clear()
    t = tv.TV(httpx.AsyncClient(), check_public=lambda h: True)
    assert [c["id"] for c in t.channels()] == ["mi"]


def test_only_listed_public_hosts_are_permitted():
    t = tv.TV(httpx.AsyncClient(), check_public=lambda h: h != "router.example")
    t.allow("https://cdn.example/a.m3u8")
    t.allow("https://router.example/a.m3u8")
    assert t.permitted("https://cdn.example/otro/seg.ts")
    assert not t.permitted("https://otro.example/a.m3u8")   # no está en ninguna lista
    assert not t.permitted("https://router.example/a.m3u8")  # apunta a la red de casa
    assert not t.permitted("file:///etc/passwd") and not t.permitted("ftp://cdn.example/x")
    assert tv._is_public("localhost") is False


def test_rewrite_sends_everything_through_the_proxy():
    allowed = []
    out = tv.rewrite('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:6,\nseg1.ts\n'
                     "https://otro-cdn.example/seg2.ts\n", "https://cdn.example/live/index.m3u8", allowed.append)
    assert f'URI="{tv.proxied("https://cdn.example/live/key.bin")}"' in out
    assert f'URI="{tv.proxied("https://cdn.example/live/init.mp4")}"' in out
    assert tv.proxied("https://cdn.example/live/seg1.ts") in out and tv.proxied("https://otro-cdn.example/seg2.ts") in out
    assert "https://otro-cdn.example/seg2.ts" in allowed and out.startswith("#EXTM3U\n")


def transport(routes):
    def handler(request):
        return routes[str(request.url)]()
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_fetch_rewrites_playlists_streams_segments_and_checks_redirects():
    routes = {
        "https://cdn.example/a.m3u8": lambda: httpx.Response(302, headers={"location": "https://edge.example/a.m3u8"}),
        "https://edge.example/a.m3u8": lambda: httpx.Response(200, text="#EXTM3U\n#EXTINF:6,\ns.ts\n",
                                                               headers={"content-type": "application/vnd.apple.mpegurl"}),
        "https://edge.example/s.ts": lambda: httpx.Response(200, content=b"\x47" * 188, headers={"content-type": "video/mp2t"}),
        "https://cdn.example/b.m3u8": lambda: httpx.Response(302, headers={"location": "http://router.example/admin"}),
    }
    t = tv.TV(httpx.AsyncClient(transport=transport(routes)), check_public=lambda h: h != "router.example")
    t.allow("https://cdn.example/a.m3u8")
    body, ctype = await t.fetch("https://cdn.example/a.m3u8")
    assert ctype == "application/vnd.apple.mpegurl" and tv.proxied("https://edge.example/s.ts") in body
    assert t.permitted("https://edge.example/s.ts")
    stream, ctype = await t.fetch("https://edge.example/s.ts")
    assert ctype == "video/mp2t" and b"".join([c async for c in stream.aiter_bytes()]) == b"\x47" * 188
    with pytest.raises(PermissionError):
        await t.fetch("https://cdn.example/b.m3u8")


@pytest.mark.anyio
async def test_list_failure_keeps_the_fallback_channels():
    def boom(request):
        raise httpx.ConnectError("sin red")
    t = tv.TV(httpx.AsyncClient(transport=httpx.MockTransport(boom)), check_public=lambda h: True)
    await t.refresh()
    assert "TDTChannels" in t.list_error
    assert next(c for c in t.channels() if c["id"] == "la1")["fuentes"] == [tv.proxied(tv.CANALES[0]["reserva"])]


def test_proxy_endpoint_refuses_unlisted_addresses(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, reminders, menu, copias
    for mod, name in ((reminders, "r.json"), (menu, "menu.json"), (copias, "copias.json")):
        monkeypatch.setattr(mod, "DATA_PATH", tmp_path / name)
    with TestClient(main.app) as c:
        assert c.get("/api/tv/hls", params={"u": "http://192.168.1.202:8123/api/states"}).status_code == 403
        assert c.get("/api/tv/hls", params={"u": "https://example.com/x.m3u8"}).status_code == 403


@pytest.fixture
def anyio_backend():
    return "asyncio"
