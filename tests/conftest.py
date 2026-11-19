import pytest


@pytest.fixture(autouse=True)
def tv_key_path(tmp_path, monkeypatch):
    """La clave de las firmas de la TV, en una carpeta temporal y no en /data."""
    from app import tv
    monkeypatch.setattr(tv, "KEY_PATH", tmp_path / "tv-clave.bin")
