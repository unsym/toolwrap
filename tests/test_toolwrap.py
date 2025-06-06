import sys
import stat
from pathlib import Path

import pytest

import toolwrap


def test_find_python_executable_python(monkeypatch, tmp_path):
    """Version string must locate python executable (docs lines 82-92)."""
    called = {}

    def fake_which(name):
        called['name'] = name
        if name == f"python{sys.version_info.major}.{sys.version_info.minor}":
            return "/usr/bin/python"
        return None

    monkeypatch.setattr(toolwrap.shutil, "which", fake_which)
    path = toolwrap.find_python_executable(f"{sys.version_info.major}.{sys.version_info.minor}")
    assert path == Path("/usr/bin/python")
    assert called['name'].startswith("python")


def test_find_python_executable_py(monkeypatch):
    """Fallback to py launcher when pythonX.Y not found (docs lines 82-92)."""

    def fake_which(name):
        if name == "py":
            return "/usr/bin/py"
        return None

    def fake_run(cmd, cwd=None, env=None, dry_run=False):
        assert cmd[0] == "/usr/bin/py"
        return True, "/custom/python", ""

    monkeypatch.setattr(toolwrap.shutil, "which", fake_which)
    monkeypatch.setattr(toolwrap, "run_command", fake_run)
    orig_exists = Path.exists

    def fake_exists(path):
        if str(path) == "/custom/python":
            return True
        return orig_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    path = toolwrap.find_python_executable("3.8")
    assert path == Path("/custom/python")


def test_parse_requirements(tmp_path):
    """Requirements parsing supports pip format (docs lines 67-80)."""
    req = tmp_path / "req.txt"
    other = tmp_path / "other.txt"
    other.write_text("baz<=2\n")
    req.write_text("""# comment
foo[extra]==1.2
git+https://example.com/repo.git#egg=bar
-r other.txt
""")
    packages = toolwrap.parse_requirements(req)
    assert packages == {"foo", "bar", "baz"}


def test_find_third_party_imports(tmp_path):
    """Standard library imports ignored; third-party detected (docs lines 192-194)."""
    script = tmp_path / "script.py"
    script.write_text(
        "import json\nfrom importlib import metadata\nimport requests\n"
    )
    imports = toolwrap.find_third_party_imports([script])
    assert imports == {"requests"}


def test_check_duplicate_wrappers(tmp_path):
    """Detect duplicate wrapper names (docs line 206)."""
    g1 = tmp_path / "g1"
    g2 = tmp_path / "g2"
    g1.mkdir()
    g2.mkdir()
    (g1 / "dup.py").write_text("print('a')")
    (g2 / "dup.py").write_text("print('b')")
    collisions = toolwrap.check_duplicate_wrappers([g1, g2])
    assert collisions == {"dup": ["g1", "g2"]}


def test_create_bash_wrapper(tmp_path):
    """Wrapper content and permissions (docs lines 200-205)."""
    wrapper = tmp_path / "run.sh"
    venv = tmp_path / "venv"
    script = tmp_path / "s.py"
    venv.mkdir()
    script.write_text("print('hello')")
    assert toolwrap.create_bash_wrapper(wrapper, venv, script)
    text = wrapper.read_text()
    assert text.startswith("#!/usr/bin/env bash")
    assert "exec python" in text
    mode = wrapper.stat().st_mode
    assert mode & stat.S_IXUSR
    assert mode & stat.S_IRUSR


def test_install_dependencies_records_pip_upgrade(monkeypatch, tmp_path):
    """Successful install_dependencies records pip upgrade in summary."""
    venv = tmp_path / "venv"
    bin_dir = venv / ("Scripts" if toolwrap.platform.system() == "Windows" else "bin")
    bin_dir.mkdir(parents=True)
    pip_path = bin_dir / ("pip.exe" if toolwrap.platform.system() == "Windows" else "pip")
    pip_path.write_text("pip")

    req = tmp_path / "req.txt"
    req.write_text("requests\n")

    calls = []

    def fake_run(cmd, cwd=None, env=None, dry_run=False):
        calls.append(cmd)
        return True, "", ""

    monkeypatch.setattr(toolwrap, "run_command", fake_run)

    summary = {"pip_upgraded": []}
    assert toolwrap.install_dependencies(venv, req, False, summary, "grp")
    assert summary["pip_upgraded"] == ["grp"]

