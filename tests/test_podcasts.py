import json
from urllib.parse import parse_qs

import httpx
import pytest

from app import avisos, podcasts

EMAIL, CLAVE = "pablo@example.com", "clave-secreta"

# Páginas como las de overcast.fm (mismas clases y atributos que su web: feedcell, episodecell, extendedepisodecell,
# usernewepisode, #audioplayer con data-item-id, data-sync-version, data-start-time…)
HOME = """<html><body><h2>Para seguir</h2>
<a class="episodecell" href="/+AbCd123">
  <img class="art" src="https://public.overcast-fm.cdn/art/atp.jpg">
  <div class="cellcontent"><div class="titlestack">
    <div class="caption2 singleline">Accidental Tech Podcast</div>
    <div class="title singleline">612: Un capítulo &amp; otro</div>
    <div class="caption2 singleline">26 nov &bull; quedan 45 min</div>
  </div></div></a>
<h2>Podcasts</h2>
<a class="feedcell" href="/itunes617416468/accidental-tech-podcast">
  <img class="art" src="https://public.overcast-fm.cdn/art/atp.jpg">
  <div class="titlestack"><div class="title singleline">Accidental Tech Podcast</div></div></a>
<a class="feedcell" href="/p12345-AbCdEf">
  <img class="art" src="https://public.overcast-fm.cdn/art/otro.jpg">
  <div class="titlestack"><div class="title singleline">Otro podcast</div></div></a>
<a class="feedcell" href="https://evil.example/">Fuera</a>
</body></html>"""

FEED = """<html><body>
<a class="extendedepisodecell usernewepisode" href="/+New999"><div class="titlestack">
  <div class="title singleline">613: El nuevo</div><div class="caption2 singleline">27 nov &bull; 1 h 30 min</div></div></a>
<a class="extendedepisodecell" href="/+AbCd123"><div class="titlestack">
  <div class="title singleline">612: Un capítulo &amp; otro</div><div class="caption2 singleline">20 nov</div></div></a>
</body></html>"""

EPISODE = """<html><body>
<img class="art fullart" src="https://public.overcast-fm.cdn/art/atp.jpg">
<h2>612: Un capítulo &amp; otro</h2><h3><a href="/itunes617416468">Accidental Tech Podcast</a></h3>
<audio id="audioplayer" preload="none" data-item-id="4242" data-logged-in="1" data-saved-for-user="1"
       data-speed-id="1500" data-sync-version="7" data-start-time="1234" data-share-url="https://overcast.fm/+AbCd123">
  <source src="https://cdn.example/atp612.mp3#t=1234" type="audio/mpeg"></audio>
</body></html>"""

LOGIN = '<form method="post"><input type="hidden" name="then" value="podcasts"/><input name="password" type="password"/></form>'


class FakeOvercast:
    def __init__(self):
        self.progress = []
        self.version = 7
        self.logins = 0
        self.valid_session = "s1"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        logged = request.headers.get("cookie", "").find(f"o={self.valid_session}") >= 0
        if path == "/login" and request.method == "POST":
            form = parse_qs(request.content.decode())
            if form.get("email") == [EMAIL] and form.get("password") == [CLAVE]:
                self.logins += 1
                return httpx.Response(302, headers={"location": "/podcasts", "set-cookie": f"o={self.valid_session}; Path=/"})
            return httpx.Response(200, text=LOGIN)
        if path == "/login":
            return httpx.Response(200, text=LOGIN)
        if not logged:
            return httpx.Response(302, headers={"location": "/login"})
        if path == "/podcasts":
            return httpx.Response(200, text=HOME)
        if path.startswith("/itunes617416468"):
            return httpx.Response(200, text=FEED)
        if path == "/+AbCd123":
            return httpx.Response(200, text=EPISODE)
        if path == "/podcasts/set_progress/4242":
            form = parse_qs(request.content.decode())
            self.progress.append({k: v[0] for k, v in form.items()})
            self.version += 1
            return httpx.Response(200, text=str(self.version))
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    from app import config
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("OVERCAST_EMAIL", EMAIL)
    monkeypatch.setenv("OVERCAST_CLAVE", CLAVE)


def make(tmp_path, fake=None):
    fake = fake or FakeOvercast()
    return podcasts.Overcast(tmp_path / "overcast.json", transport=httpx.MockTransport(fake)), fake


def test_parsing_their_pages():
    home = podcasts.parse_home(HOME)
    assert home["en_curso"] == [{"id": "AbCd123", "titulo": "612: Un capítulo & otro", "podcast": "Accidental Tech Podcast",
                                 "info": "26 nov • quedan 45 min", "arte": "https://public.overcast-fm.cdn/art/atp.jpg"}]
    assert [f["ruta"] for f in home["podcasts"]] == ["/itunes617416468/accidental-tech-podcast", "/p12345-AbCdEf"]
    feed = podcasts.parse_feed(FEED)
    assert feed[0] == {"id": "New999", "titulo": "613: El nuevo", "info": "27 nov • 1 h 30 min", "nuevo": True}
    assert feed[1]["nuevo"] is False
    e = podcasts.parse_episode(EPISODE)
    assert e["item_id"] == "4242" and e["audio"] == "https://cdn.example/atp612.mp3" and e["inicio"] == 1234
    assert e["version"] == 7 and e["velocidad_id"] == 1500 and e["titulo"] == "612: Un capítulo & otro"
    assert e["podcast"] == "Accidental Tech Podcast"
    with pytest.raises(ValueError):
        podcasts.parse_episode("<html>sin reproductor</html>")


@pytest.mark.anyio
async def test_logs_in_reads_the_library_and_keeps_the_session(tmp_path):
    oc, fake = make(tmp_path)
    lib = await oc.library()
    assert lib["error"] is None and lib["en_curso"][0]["id"] == "AbCd123" and len(lib["podcasts"]) == 2
    assert fake.logins == 1
    saved = json.loads((tmp_path / "overcast.json").read_text())
    assert saved == {"cookies": {"o": "s1"}} and CLAVE not in json.dumps(saved)   # la cookie, nunca la contraseña
    oc2, _ = make(tmp_path, fake)                       # tras un reinicio, con la cookie guardada: sin login
    await oc2.library()
    assert fake.logins == 1
    fake.valid_session = "s2"                           # la sesión caduca: vuelve a entrar una vez
    oc2.home_at = 0
    assert (await oc2.library())["error"] is None and fake.logins == 2


@pytest.mark.anyio
async def test_episode_and_progress_like_their_web_player(tmp_path):
    oc, fake = make(tmp_path)
    ep = await oc.episode("AbCd123")
    assert ep == {"id": "AbCd123", "titulo": "612: Un capítulo & otro", "podcast": "Accidental Tech Podcast",
                  "arte": "https://public.overcast-fm.cdn/art/atp.jpg", "audio": "https://cdn.example/atp612.mp3",
                  "inicio": 1234, "velocidad_id": 1500}
    assert await oc.progress("AbCd123", 1300.7) == 8
    assert await oc.progress("AbCd123", 1360) == 9
    assert fake.progress == [{"p": "1300", "speed": "1500", "v": "7"}, {"p": "1360", "speed": "1500", "v": "8"}]
    await oc.progress("AbCd123", 0, finished=True)
    assert fake.progress[-1]["p"] == str(0x7FFFFFFF)    # terminado, como su reproductor
    with pytest.raises(KeyError):
        await oc.progress("Otro1234", 10)


@pytest.mark.anyio
async def test_bad_password_and_unknown_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("OVERCAST_CLAVE", "mala")
    oc, _ = make(tmp_path)
    lib = await oc.library()
    assert "correo o la contraseña" in lib["error"] and "mala" not in lib["error"]
    out = avisos.build(__import__("datetime").datetime(2026, 11, 26, 12), sources={}, extra={}, lists=[], shelly={},
                       podcasts=oc.status())
    assert out[0]["id"] == "podcasts"
    with pytest.raises(ValueError):
        await oc.feed("/../account/delete")
    with pytest.raises(ValueError):
        await oc.feed("https://evil.example/")
    with pytest.raises(ValueError):
        await oc.episode("../login")


def test_not_configured_without_both_variables(monkeypatch):
    monkeypatch.delenv("OVERCAST_CLAVE")
    assert podcasts.credentials() is None


def test_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, menu, reminders, copias
    for mod, name in ((reminders, "r.json"), (menu, "menu.json"), (copias, "copias.json")):
        monkeypatch.setattr(mod, "DATA_PATH", tmp_path / name)
    fake = FakeOvercast()
    real = podcasts.Overcast
    monkeypatch.setattr(podcasts, "Overcast", lambda: real(tmp_path / "overcast.json", transport=httpx.MockTransport(fake)))
    with TestClient(main.app) as c:
        assert c.get("/api/tv").json()["podcasts"] is True
        assert c.get("/api/podcasts").json()["en_curso"][0]["id"] == "AbCd123"
        assert c.get("/api/podcasts/podcast", params={"ruta": "/itunes617416468/accidental-tech-podcast"}).json()["capitulos"][0]["id"] == "New999"
        assert c.get("/api/podcasts/podcast", params={"ruta": "/account"}).status_code == 400
        assert c.post("/api/podcasts/progreso", json={"id": "AbCd123", "segundos": 5}).status_code == 404  # sin abrir
        assert c.get("/api/podcasts/episodio/AbCd123").json()["inicio"] == 1234
        assert c.post("/api/podcasts/progreso", json={"id": "AbCd123", "segundos": 1400}).json() == {"ok": True, "version": 8}
        body = json.dumps(c.get("/api/podcasts").json())
        assert CLAVE not in body and "s1" not in body
    monkeypatch.delenv("OVERCAST_EMAIL")
    monkeypatch.setattr(podcasts, "Overcast", real)
    with TestClient(main.app) as c:
        assert c.get("/api/tv").json()["podcasts"] is False
        assert c.get("/api/podcasts").status_code == 404


@pytest.fixture
def anyio_backend():
    return "asyncio"
