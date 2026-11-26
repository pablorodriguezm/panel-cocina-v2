import pytest


@pytest.fixture(autouse=True)
def tv_key_path(tmp_path, monkeypatch):
    """La clave de las firmas de la TV y los temporizadores, en una carpeta temporal y no en /data."""
    from app import cocina, tv
    monkeypatch.setattr(tv, "KEY_PATH", tmp_path / "tv-clave.bin")
    monkeypatch.setattr(cocina, "DATA_PATH", tmp_path / "cocina.json")
