import sys
import stat
import subprocess
import platform
from pathlib import Path
import logging

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
        if Path(path).as_posix() == "/custom/python":
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


def test_parse_requirements_cycle(tmp_path):
    """Circular -r references do not cause infinite recursion."""
    a = tmp_path / "A.txt"
    b = tmp_path / "B.txt"
    a.write_text("pkg_a\n-r B.txt\n")
    b.write_text("pkg_b\n-r A.txt\n")
    packages = toolwrap.parse_requirements(a)
    assert packages == {"pkg_a", "pkg_b"}


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


@pytest.mark.skipif(platform.system() == "Windows", reason="POSIX-specific test")
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


def test_create_cmd_wrapper_generation(tmp_path, monkeypatch):
    """Windows wrapper generation adds .cmd extension."""
    monkeypatch.setattr(toolwrap.platform, "system", lambda: "Windows")
    wrapper = tmp_path / "run"
    venv = tmp_path / "venv"
    script = tmp_path / "s.py"
    (venv / "Scripts").mkdir(parents=True)
    script.write_text("print('hi')")
    assert toolwrap.create_wrapper(wrapper, venv, script)
    cmd_file = wrapper.with_suffix(".cmd")
    text = cmd_file.read_text()
    assert "%~dp0" in text
    assert "activate.bat" in text
    assert cmd_file.exists()


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific execution test")
def test_cmd_wrapper_execution(tmp_path, monkeypatch):
    """Generated .cmd wrapper runs target script after activating venv."""
    wrapper = tmp_path / "tool"
    venv = tmp_path / "venv"
    scripts = venv / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "activate.bat").write_text("@echo off\nset TESTVAR=1\n")
    script = tmp_path / "s.py"
    script.write_text("import os; print('VAR=' + os.getenv('TESTVAR',''))")
    monkeypatch.setattr(toolwrap.platform, "system", lambda: "Windows")
    assert toolwrap.create_wrapper(wrapper, venv, script)
    cmd_path = wrapper.with_suffix(".cmd")
    result = subprocess.run(["cmd", "/c", str(cmd_path)], capture_output=True, text=True)
    assert "VAR=1" in result.stdout


def _setup_basic(monkeypatch):
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "create_bash_wrapper", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    def fake_create(py, path, dry_run):
        path.mkdir(parents=True, exist_ok=True)
        bin_dir = path / ("Scripts" if toolwrap.platform.system() == "Windows" else "bin")
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / ("python.exe" if toolwrap.platform.system() == "Windows" else "python")).write_text("")
        (bin_dir / ("pip.exe" if toolwrap.platform.system() == "Windows" else "pip")).write_text("")
        return True
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)


def test_recreate_all_removes_all(tmp_path, monkeypatch):
    source = tmp_path / "src"
    bin_dir = tmp_path / "bin"
    venv_root = bin_dir / ".venv"
    source.mkdir()
    bin_dir.mkdir()
    venv_root.mkdir()
    (source / "g1").mkdir()
    (source / "g1" / "script.py").write_text("print('hi')")
    obsolete = venv_root / "old"
    obsolete.mkdir(parents=True)

    _setup_basic(monkeypatch)

    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source), "--bin", str(bin_dir),
                               "--venv-root", str(venv_root), "--recreate-all"])
    toolwrap.main()

    assert not obsolete.exists()


def test_recreate_all_include_groups(tmp_path, monkeypatch):
    source = tmp_path / "src"
    bin_dir = tmp_path / "bin"
    venv_root = bin_dir / ".venv"
    for p in [source, bin_dir, venv_root]:
        p.mkdir(parents=True, exist_ok=True)
    for name in ["g1", "g2"]:
        grp = source / name
        grp.mkdir()
        (grp / "s.py").write_text("print('x')")
        (venv_root / name).mkdir()
    untouched = venv_root / "untouched"
    untouched.mkdir()

    _setup_basic(monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source), "--bin", str(bin_dir),
        "--venv-root", str(venv_root), "--recreate-all", "--include-groups", "g1"
    ])
    toolwrap.main()

    assert (venv_root / "g1").is_dir()
    assert (venv_root / "g2").is_dir()
    assert untouched.is_dir()


def test_path_is_relative_helper():
    """Piecewise path comparison works without Path.is_relative_to."""
    from pathlib import Path

    assert toolwrap._path_is_relative_to(Path("/usr/lib/foo.py"), Path("/usr/lib"))
    assert not toolwrap._path_is_relative_to(Path("/usr/lib64/foo.py"), Path("/usr/lib"))


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


def test_is_standard_library():
    assert toolwrap.is_standard_library("json")
    assert not toolwrap.is_standard_library("some_nonexistent_pkg")

def test_run_command(tmp_path):
    success, out, err = toolwrap.run_command([sys.executable, "-c", "print('x')"])
    assert success and out.strip() == "x"
    success, _, _ = toolwrap.run_command([sys.executable, "-c", "import sys; sys.exit(1)"])
    assert not success
    success, out, err = toolwrap.run_command([sys.executable, "-c", "print('y')"], dry_run=True)
    assert success and out == "" and err == ""

def test_create_virtualenv_invokes_run(monkeypatch, tmp_path):
    calls = []
    def fake_run(cmd, cwd=None, env=None, dry_run=False):
        calls.append(cmd)
        return True, "", ""
    monkeypatch.setattr(toolwrap, "run_command", fake_run)
    py_exec = Path("/py")
    assert toolwrap.create_virtualenv(py_exec, tmp_path / "v", False)
    assert calls[0][:3] == [str(py_exec), "-m", "venv"]

def test_create_virtualenv_dry_run(monkeypatch, tmp_path):
    called = False
    def fake_run(*a, **k):
        nonlocal called
        called = True
        return True, "", ""
    monkeypatch.setattr(toolwrap, "run_command", fake_run)
    assert toolwrap.create_virtualenv(Path("/py"), tmp_path / "v", True)
    assert not called

def test_python_version_file(monkeypatch, tmp_path):
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    grp = src / "g"; grp.mkdir(parents=True)
    (grp / "script.py").write_text("print('a')")
    (grp / "python_version.txt").write_text("3.9")
    calls = []
    def fake_find(version):
        calls.append(version)
        if version == "3.9":
            return Path("/custom/python")
        return Path(sys.executable)
    def fake_create(py, path, dry):
        assert py == Path("/custom/python")
        path.mkdir(parents=True, exist_ok=True)
        bin_p = path / ("Scripts" if platform.system() == "Windows" else "bin")
        bin_p.mkdir(parents=True)
        (bin_p / ("python.exe" if platform.system() == "Windows" else "python")).write_text("")
        (bin_p / ("pip.exe" if platform.system() == "Windows" else "pip")).write_text("")
        return True
    monkeypatch.setattr(toolwrap, "find_python_executable", fake_find)
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "create_bash_wrapper", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root)])
    toolwrap.main()
    assert (venv_root / "g").is_dir()
    assert "3.9" in calls

def test_python_version_fallback(monkeypatch, tmp_path):
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    grp = src / "g"; grp.mkdir(parents=True)
    (grp / "script.py").write_text("print('b')")
    (grp / "python_version.txt").write_text("9.9")
    calls = []
    def fake_find(version):
        calls.append(version)
        if version == "9.9":
            return None
        if version == "3.8":
            return Path("/fallback")
        return Path(sys.executable)
    def fake_create(py, path, dry):
        assert py == Path("/fallback")
        path.mkdir(parents=True, exist_ok=True)
        bin_p = path / ("Scripts" if platform.system() == "Windows" else "bin")
        bin_p.mkdir(parents=True)
        (bin_p / ("python.exe" if platform.system() == "Windows" else "python")).write_text("")
        (bin_p / ("pip.exe" if platform.system() == "Windows" else "pip")).write_text("")
        return True
    monkeypatch.setattr(toolwrap, "find_python_executable", fake_find)
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "create_bash_wrapper", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root), "--python-version", "3.8"])
    toolwrap.main()
    assert calls[0] == "3.8" and calls[1] == "9.9"

def test_main_dry_run(monkeypatch, tmp_path):
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    grp = src / "g"; grp.mkdir(parents=True)
    (grp / "script.py").write_text("print('c')")
    created = []
    def fake_create(py, path, dry):
        created.append(dry)
        return True
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "create_bash_wrapper", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root), "--dry-run"])
    toolwrap.main()
    assert created == [True]
    assert not (venv_root / "g").exists()
    assert not (bin_dir / "script").exists()

def test_missing_requirements_append(monkeypatch, tmp_path):
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    grp = src / "g"; grp.mkdir(parents=True)
    (grp / "script.py").write_text("import numpy\n")
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "create_bash_wrapper", lambda *a, **k: True)
    def fake_create(py, path, dry):
        path.mkdir(parents=True, exist_ok=True)
        bin_p = path / ("Scripts" if platform.system() == "Windows" else "bin")
        bin_p.mkdir(parents=True)
        (bin_p / ("python.exe" if platform.system() == "Windows" else "python")).write_text("")
        (bin_p / ("pip.exe" if platform.system() == "Windows" else "pip")).write_text("")
        return True
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root), "--missing-requirements", "append"])
    toolwrap.main()
    req = grp / "requirements.txt"
    assert "numpy" in req.read_text().lower()

def test_include_groups_selective(monkeypatch, tmp_path):
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    for name in ["g1", "g2"]:
        d = src / name; d.mkdir(parents=True)
        (d / "script.py").write_text("print('x')")
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "create_bash_wrapper", lambda *a, **k: True)
    def fake_create(py, path, dry):
        path.mkdir(parents=True, exist_ok=True)
        bin_p = path / ("Scripts" if platform.system() == "Windows" else "bin")
        bin_p.mkdir(parents=True)
        (bin_p / ("python.exe" if platform.system() == "Windows" else "python")).write_text("")
        (bin_p / ("pip.exe" if platform.system() == "Windows" else "pip")).write_text("")
        return True
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root), "--include-groups", "g1,missing"])
    toolwrap.main()
    assert (venv_root / "g1").is_dir()
    assert not (venv_root / "g2").exists()
    assert not (venv_root / "missing").exists()


def _fake_create_venv(path: Path):
    """Helper to create minimal venv structure for tests."""
    bin_dir = path / ("Scripts" if platform.system() == "Windows" else "bin")
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / ("python.exe" if platform.system() == "Windows" else "python")).write_text("")
    (bin_dir / ("pip.exe" if platform.system() == "Windows" else "pip")).write_text("")


def test_verbose_sets_debug_logging(monkeypatch, tmp_path):
    source = tmp_path / "src"; bin_dir = tmp_path / "bin"
    source.mkdir(); bin_dir.mkdir()

    recorded = {}

    def mock_basic(level=None, **kwargs):
        recorded['level'] = level

    monkeypatch.setattr(logging, "basicConfig", mock_basic)
    orig_iterdir = Path.iterdir

    def fake_iterdir(self):
        if self == source:
            return iter([])
        return orig_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(toolwrap, "check_duplicate_wrappers", lambda g: {})
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source), "--bin", str(bin_dir), "--verbose"])

    with pytest.raises(toolwrap.ToolwrapError):
        toolwrap.main()

    assert recorded.get('level') == logging.DEBUG


def test_verbose_defaults_to_info(monkeypatch, tmp_path):
    source = tmp_path / "src"; bin_dir = tmp_path / "bin"
    source.mkdir(); bin_dir.mkdir()

    recorded = {}

    def mock_basic(level=None, **kwargs):
        recorded['level'] = level

    monkeypatch.setattr(logging, "basicConfig", mock_basic)
    orig_iterdir = Path.iterdir

    def fake_iterdir(self):
        if self == source:
            return iter([])
        return orig_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setattr(toolwrap, "check_duplicate_wrappers", lambda g: {})
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source), "--bin", str(bin_dir)])

    with pytest.raises(toolwrap.ToolwrapError):
        toolwrap.main()

    assert recorded.get('level') == logging.INFO


def test_custom_directories(monkeypatch, tmp_path):
    source_dir = tmp_path / "src"
    bin_dir = tmp_path / "custom_bin"
    venv_root = tmp_path / "custom_venv"
    grp = source_dir / "g1"
    for p in [source_dir, bin_dir, venv_root, grp]:
        p.mkdir(parents=True, exist_ok=True)
    script = grp / "tool.py"
    script.write_text("print('hi')")

    venv_paths = []

    def fake_create(py, path, dry):
        venv_paths.append(path)
        _fake_create_venv(path)
        return True

    wrappers = []

    def fake_wrapper(wp, vp, tp, dr=False):
        wrappers.append(wp)
        return True

    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "create_wrapper", fake_wrapper)
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir),
        "--bin", str(bin_dir), "--venv-root", str(venv_root)
    ])

    toolwrap.main()

    assert venv_paths and venv_paths[0] == venv_root / "g1"
    assert wrappers and wrappers[0] == bin_dir / "tool"


def _setup_req_env(tmp_path, monkeypatch, content="existing\n"):
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    grp = src / "grp"; grp.mkdir(parents=True)
    script = grp / "s.py"; script.write_text("import missing_pkg\n")
    req = grp / "requirements.txt"
    req.write_text(content)
    def fake_create(*a, **k):
        _fake_create_venv(a[1])
        return True

    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "create_wrapper", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(toolwrap, "find_third_party_imports", lambda f: {"missing_pkg"})
    return src, bin_dir, venv_root, req


def test_missing_requirements_suggest(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    src, bin_dir, venv_root, req = _setup_req_env(tmp_path, monkeypatch)
    initial = req.read_text()
    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(src), "--bin", str(bin_dir),
        "--venv-root", str(venv_root), "--missing-requirements", "suggest"
    ])

    toolwrap.main()

    assert req.read_text() == initial
    assert any("[SUGGEST]" in r.message for r in caplog.records)


def test_missing_requirements_default(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    src, bin_dir, venv_root, req = _setup_req_env(tmp_path, monkeypatch)
    initial = req.read_text()
    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root)
    ])

    toolwrap.main()

    assert req.read_text() == initial
    assert not any("missing packages" in r.message for r in caplog.records)


def test_skip_group_no_py(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    empty_grp = src / "empty"; empty_grp.mkdir(parents=True)

    called = False

    def fake_create(*a, **k):
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)
    monkeypatch.setattr(toolwrap, "create_wrapper", fake_create)
    monkeypatch.setattr(toolwrap, "install_dependencies", fake_create)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root)])

    toolwrap.main()

    assert not called
    assert any("Skipping group" in r.message for r in caplog.records)


def test_duplicate_wrappers_in_main(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    src = tmp_path / "src"; bin_dir = tmp_path / "bin"; venv_root = bin_dir / ".venv"
    g1 = src / "g1"; g2 = src / "g2"
    for g in [g1, g2]:
        g.mkdir(parents=True)
        (g / "dup.py").write_text("print('x')")

    monkeypatch.setattr(toolwrap, "install_dependencies", lambda *a, **k: True)

    def fake_create(py, path, dry):
        _fake_create_venv(path)
        return True

    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create)

    created_wrappers = []

    def fake_wrapper(wp, vp, tp, dr=False):
        created_wrappers.append(wp)
        return True

    monkeypatch.setattr(toolwrap, "create_wrapper", fake_wrapper)
    monkeypatch.setattr(toolwrap, "find_python_executable", lambda v: Path(sys.executable))
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(src), "--bin", str(bin_dir), "--venv-root", str(venv_root)])

    toolwrap.main()

    assert not created_wrappers
    assert any("Duplicate wrapper names detected" in r.message for r in caplog.records)
