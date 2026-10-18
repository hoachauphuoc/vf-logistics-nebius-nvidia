"""
entrypoint.sh starts gunicorn on FLASK_APP_MODULE, and on vf_logistics.app:app when it is unset, so
vf-app (which never sets it) runs exactly what it ran before. Only vf-app-faulttest sets it.
"""

from __future__ import annotations

from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parent.parent / "entrypoint.sh"


def test_the_wsgi_module_comes_from_the_environment_with_the_old_default():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert '"${FLASK_APP_MODULE:-vf_logistics.app:app}" &' in text


def test_the_fixed_target_is_gone():
    lines = [line.strip() for line in ENTRYPOINT.read_text(encoding="utf-8").splitlines()]
    assert "vf_logistics.app:app &" not in lines
