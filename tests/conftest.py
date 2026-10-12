import pytest

import ac
import store


@pytest.fixture(autouse=True)
def private_files(tmp_path, monkeypatch):
    """Point every Breeze file at a fresh test folder, never the owner's real ones.

    Both `store` and `ac` hold their own copy of each path, so both are patched. A test that
    patched only one once overwrote the real AC key with test values. The folder is not
    created here; Breeze makes it on first write, as it does at home.
    """
    folder = tmp_path / "breeze-config"
    for module in (ac, store):
        monkeypatch.setattr(module, "CONFIG_DIR", folder)
        monkeypatch.setattr(module, "AC_FILE", folder / "ac.json")
        monkeypatch.setattr(module, "SETTINGS_FILE", folder / "settings.json")
        monkeypatch.setattr(module, "ENERGY_FILE", folder / "energy.json")
        monkeypatch.setattr(module, "CARE_FILE", folder / "care.json")
        monkeypatch.setattr(module, "SCHEDULE_FILE", folder / "schedules.json")
        monkeypatch.setattr(module, "SLEEP_FILE", folder / "sleep.json")
    return folder
