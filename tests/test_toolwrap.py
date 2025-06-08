import sys
import stat
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Optional # Added for type hints
import logging # Added for logging in mock

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


def test_custom_source_and_bin_dirs(tmp_path, monkeypatch):
    """Test toolwrap with custom source and bin directories."""
    from unittest.mock import Mock

    # 1. Setup distinct source and bin directories
    source_dir = tmp_path / "custom_src"
    bin_dir = tmp_path / "custom_bin"
    source_dir.mkdir()
    bin_dir.mkdir()

    # 2. Create a simple tool group and script
    group_a_path = source_dir / "group_a"
    group_a_path.mkdir()
    (group_a_path / "tool1.py").write_text("print('hello from tool1')")

    # 3. Mock toolwrap functions
    def fake_create_virtualenv(python_exec, venv_path, dry_run):
        """Simulate venv creation including bin/python and bin/pip."""
        if not dry_run:
            venv_path.mkdir(parents=True, exist_ok=True)
            # Determine bin directory based on platform toolwrap uses
            bin_dir_name = "Scripts" if platform.system() == "Windows" else "bin"
            venv_bin_dir = venv_path / bin_dir_name
            venv_bin_dir.mkdir(parents=True, exist_ok=True)
            # Create dummy executables
            python_exe_name = "python.exe" if platform.system() == "Windows" else "python"
            pip_exe_name = "pip.exe" if platform.system() == "Windows" else "pip"
            (venv_bin_dir / python_exe_name).write_text("#!/usr/bin/env python\n")
            (venv_bin_dir / pip_exe_name).write_text("#!/usr/bin/env python\n")
        return True

    mock_create_venv = Mock(wraps=fake_create_virtualenv)
    mock_install_deps = Mock(return_value=True)
    mock_create_wrapper = Mock(return_value=True)
    mock_find_python = Mock(return_value=Path(sys.executable))
    mock_setup_logging = Mock()
    mock_rmtree = Mock()

    monkeypatch.setattr(toolwrap, "create_virtualenv", mock_create_venv)
    monkeypatch.setattr(toolwrap, "install_dependencies", mock_install_deps)
    monkeypatch.setattr(toolwrap, "create_wrapper", mock_create_wrapper)
    monkeypatch.setattr(toolwrap, "find_python_executable", mock_find_python)
    monkeypatch.setattr(toolwrap, "setup_logging", mock_setup_logging)
    monkeypatch.setattr(toolwrap.shutil, "rmtree", mock_rmtree) # Prevent issues

    # 4. Patch sys.argv
    monkeypatch.setattr(sys, "argv", [
        "toolwrap",
        "--source", str(source_dir),
        "--bin", str(bin_dir)
    ])

    # 5. Execute toolwrap.main()
    toolwrap.main()

    # 6. Assertions
    # Assert create_wrapper called correctly
    expected_wrapper_path = bin_dir / "tool1"
    mock_create_wrapper.assert_called_once()
    # The first arg to create_wrapper is the wrapper path
    actual_wrapper_path_arg = mock_create_wrapper.call_args[0][0]
    assert actual_wrapper_path_arg == expected_wrapper_path

    # Assert create_virtualenv called correctly
    expected_venv_path = bin_dir / ".venv" / "group_a"
    mock_create_venv.assert_called_once()
    # The second arg to create_virtualenv is the venv_path
    actual_venv_path_arg = mock_create_venv.call_args[0][1]
    assert actual_venv_path_arg == expected_venv_path

    # Assert find_python_executable was called (it's called per group)
    mock_find_python.assert_called()


    # Assert setup_logging called correctly
    # toolwrap.main() calls setup_logging with the full log file path.
    # LOG_FILENAME is 'toolwrap_envs.log' in toolwrap.py (not directly accessible here without import)
    # We assume LOG_FILENAME is 'toolwrap_envs.log' as per its usage in toolwrap.py
    expected_log_file_path = bin_dir / ".venv" / "toolwrap_envs.log"
    mock_setup_logging.assert_called_once()
    # The first arg to setup_logging is the log_file path
    actual_log_file_arg = mock_setup_logging.call_args[0][0]
    assert actual_log_file_arg == expected_log_file_path

    # Assert that the log file's parent directory was at least attempted to be created
    # toolwrap.setup_logging itself creates the log_dir.
    # We can check if Path.mkdir was called on the expected log directory.
    # This requires a more complex mock for Path.mkdir or checking if the dir exists.
    # For now, the call to setup_logging with the correct path is a good indicator.
    # We can also assert that (bin_dir / ".venv" / "toolwrap_envs.log").exists()
    # if we don't fully mock setup_logging or Path.write_text.
    # Given setup_logging is mocked, we rely on its argument.

    # Verify rmtree was not called unnecessarily (it's for --recreate flags)
    mock_rmtree.assert_not_called()


def test_custom_venv_root_dir(tmp_path, monkeypatch):
    """Test toolwrap with a custom --venv-root directory."""
    from unittest.mock import Mock

    # 1. Setup directories
    source_dir = tmp_path / "src"
    bin_dir = tmp_path / "bin"  # Wrappers still go here by default
    custom_venv_root = tmp_path / "custom_venvs"

    source_dir.mkdir()
    bin_dir.mkdir()
    custom_venv_root.mkdir()

    # 2. Create a simple tool group and script
    group_b_path = source_dir / "group_b"
    group_b_path.mkdir()
    (group_b_path / "tool2.py").write_text("print('hello from tool2')")

    # 3. Mock toolwrap functions (reuse fake_create_virtualenv from previous test)
    def fake_create_virtualenv(python_exec, venv_path, dry_run):
        if not dry_run:
            venv_path.mkdir(parents=True, exist_ok=True)
            bin_dir_name = "Scripts" if platform.system() == "Windows" else "bin"
            venv_bin_dir = venv_path / bin_dir_name
            venv_bin_dir.mkdir(parents=True, exist_ok=True)
            python_exe_name = "python.exe" if platform.system() == "Windows" else "python"
            pip_exe_name = "pip.exe" if platform.system() == "Windows" else "pip"
            (venv_bin_dir / python_exe_name).write_text("#!/usr/bin/env python\n")
            (venv_bin_dir / pip_exe_name).write_text("#!/usr/bin/env python\n")
        return True

    mock_create_venv = Mock(wraps=fake_create_virtualenv)
    mock_install_deps = Mock(return_value=True)
    mock_create_wrapper = Mock(return_value=True)
    mock_find_python = Mock(return_value=Path(sys.executable))
    mock_setup_logging = Mock()
    mock_rmtree = Mock()

    monkeypatch.setattr(toolwrap, "create_virtualenv", mock_create_venv)
    monkeypatch.setattr(toolwrap, "install_dependencies", mock_install_deps)
    monkeypatch.setattr(toolwrap, "create_wrapper", mock_create_wrapper)
    monkeypatch.setattr(toolwrap, "find_python_executable", mock_find_python)
    monkeypatch.setattr(toolwrap, "setup_logging", mock_setup_logging)
    monkeypatch.setattr(toolwrap.shutil, "rmtree", mock_rmtree)

    # 4. Patch sys.argv
    monkeypatch.setattr(sys, "argv", [
        "toolwrap",
        "--source", str(source_dir),
        "--bin", str(bin_dir),
        "--venv-root", str(custom_venv_root)
    ])

    # 5. Execute toolwrap.main()
    toolwrap.main()

    # 6. Assertions
    # Assert create_virtualenv called correctly
    expected_venv_path = custom_venv_root / "group_b"
    mock_create_venv.assert_called_once()
    actual_venv_path_arg = mock_create_venv.call_args[0][1] # venv_path is the 2nd arg
    assert actual_venv_path_arg == expected_venv_path

    # Assert create_wrapper called correctly
    expected_wrapper_path = bin_dir / "tool2" # Wrappers are still in bin_dir
    mock_create_wrapper.assert_called_once()
    actual_wrapper_path_arg = mock_create_wrapper.call_args[0][0]
    assert actual_wrapper_path_arg == expected_wrapper_path

    # Assert find_python_executable was called
    mock_find_python.assert_called()

    # Assert setup_logging called correctly
    # LOG_FILENAME is 'toolwrap_envs.log'
    expected_log_file_path = custom_venv_root / "toolwrap_envs.log"
    mock_setup_logging.assert_called_once()
    actual_log_file_arg = mock_setup_logging.call_args[0][0] # log_file is the 1st arg
    assert actual_log_file_arg == expected_log_file_path

    # Verify rmtree was not called
    mock_rmtree.assert_not_called()


# --- Tests for --python-version fallback and python_version.txt interaction ---

# Helper mock for create_virtualenv to capture python_executable
def fake_create_virtualenv_capture_py(python_executable, venv_path, dry_run, captured_args_dict):
    captured_args_dict.setdefault('create_virtualenv_calls', []).append(
        {'python': python_executable, 'path': venv_path}
    )
    if not dry_run:
        venv_path.mkdir(parents=True, exist_ok=True)
        venv_bin = venv_path / ("Scripts" if platform.system() == "Windows" else "bin")
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / ("python.exe" if platform.system() == "Windows" else "python")).touch()
        (venv_bin / ("pip.exe" if platform.system() == "Windows" else "pip")).touch()
    return True


def test_fallback_python_version_used(tmp_path, monkeypatch):
    """Fallback --python-version is used if python_version.txt is missing."""
    from unittest.mock import Mock

    source_dir = tmp_path / "src"
    bin_dir = tmp_path / "bin"
    source_dir.mkdir()
    bin_dir.mkdir()

    group_c_path = source_dir / "group_c"
    group_c_path.mkdir()
    (group_c_path / "tool3.py").write_text("print('tool3')")
    # No python_version.txt in group_c

    captured_args = {}

    def mock_find_python(version_str):
        captured_args.setdefault('find_python_calls', []).append(version_str)
        if version_str == "fallback_py_version":
            return Path("/path/to/fallback_python")
        # Provides a default for initial fallback_python_executable resolution if needed,
        # and for groups without python_version.txt if --python-version is not set.
        return Path(sys.executable)


    monkeypatch.setattr(toolwrap, "find_python_executable", mock_find_python)
    monkeypatch.setattr(toolwrap, "create_virtualenv",
                        lambda p, v, dr: fake_create_virtualenv_capture_py(p, v, dr, captured_args))
    monkeypatch.setattr(toolwrap, "install_dependencies", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "create_wrapper", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "setup_logging", Mock())
    monkeypatch.setattr(toolwrap.shutil, "rmtree", Mock())

    monkeypatch.setattr(sys, "argv", [
        "toolwrap",
        "--source", str(source_dir),
        "--bin", str(bin_dir),
        "--python-version", "fallback_py_version"
    ])

    toolwrap.main()

    assert "fallback_py_version" in captured_args['find_python_calls']
    assert len(captured_args['create_virtualenv_calls']) == 1
    call_info = captured_args['create_virtualenv_calls'][0]
    assert call_info['python'] == Path("/path/to/fallback_python")
    assert call_info['path'] == bin_dir / ".venv" / "group_c"


def test_group_python_version_overrides_fallback(tmp_path, monkeypatch):
    """python_version.txt overrides the global --python-version."""
    from unittest.mock import Mock

    source_dir = tmp_path / "src"
    bin_dir = tmp_path / "bin"
    source_dir.mkdir()
    bin_dir.mkdir()

    group_d_path = source_dir / "group_d"
    group_d_path.mkdir()
    (group_d_path / "tool4.py").write_text("print('tool4')")
    (group_d_path / "python_version.txt").write_text("group_py_version")

    captured_args = {}

    def mock_find_python(version_str):
        captured_args.setdefault('find_python_calls', []).append(version_str)
        if version_str == "group_py_version":
            return Path("/path/to/group_python")
        if version_str == "fallback_py_version":
            return Path("/path/to/fallback_python")
        return Path(sys.executable)

    monkeypatch.setattr(toolwrap, "find_python_executable", mock_find_python)
    monkeypatch.setattr(toolwrap, "create_virtualenv",
                        lambda p, v, dr: fake_create_virtualenv_capture_py(p, v, dr, captured_args))
    monkeypatch.setattr(toolwrap, "install_dependencies", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "create_wrapper", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "setup_logging", Mock())
    monkeypatch.setattr(toolwrap.shutil, "rmtree", Mock())

    monkeypatch.setattr(sys, "argv", [
        "toolwrap",
        "--source", str(source_dir),
        "--bin", str(bin_dir),
        "--python-version", "fallback_py_version"
    ])

    toolwrap.main()

    # find_python_executable is called for fallback, then for group
    assert "fallback_py_version" in captured_args['find_python_calls']
    assert "group_py_version" in captured_args['find_python_calls']

    assert len(captured_args['create_virtualenv_calls']) == 1
    call_info = captured_args['create_virtualenv_calls'][0]
    assert call_info['python'] == Path("/path/to/group_python")
    assert call_info['path'] == bin_dir / ".venv" / "group_d"


def test_fallback_python_version_on_invalid_group_config(tmp_path, monkeypatch, caplog):
    """Fallback is used if python_version.txt specifies an unavailable version."""
    from unittest.mock import Mock
    import logging

    source_dir = tmp_path / "src"
    bin_dir = tmp_path / "bin"
    source_dir.mkdir()
    bin_dir.mkdir()

    group_e_path = source_dir / "group_e"
    group_e_path.mkdir()
    (group_e_path / "tool5.py").write_text("print('tool5')")
    (group_e_path / "python_version.txt").write_text("invalid_group_py_version")

    captured_args = {}

    # Order of calls to find_python_executable:
    # 1. For "fallback_py_version" (to resolve args.python_version)
    # 2. For "invalid_group_py_version" (when processing group_e's python_version.txt)
    # (If find_python_executable for "invalid_group_py_version" returns None,
    #  toolwrap uses the already resolved fallback_python_executable)
    def mock_find_python(version_str):
        captured_args.setdefault('find_python_calls', []).append(version_str)
        if version_str == "invalid_group_py_version":
            return None  # Simulate this version not being found
        if version_str == "fallback_py_version":
            return Path("/path/to/fallback_python")
        return Path(sys.executable) # For default system python if needed

    monkeypatch.setattr(toolwrap, "find_python_executable", mock_find_python)
    monkeypatch.setattr(toolwrap, "create_virtualenv",
                        lambda p, v, dr: fake_create_virtualenv_capture_py(p, v, dr, captured_args))
    monkeypatch.setattr(toolwrap, "install_dependencies", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "create_wrapper", Mock(return_value=True))

    # Let setup_logging run to capture log messages, but mock its internals if they cause side effects
    # For this test, we only need caplog, so a simple Mock for setup_logging is fine.
    monkeypatch.setattr(toolwrap, "setup_logging", Mock())
    monkeypatch.setattr(toolwrap.shutil, "rmtree", Mock())

    monkeypatch.setattr(sys, "argv", [
        "toolwrap",
        "--source", str(source_dir),
        "--bin", str(bin_dir),
        "--python-version", "fallback_py_version"
    ])

    with caplog.at_level(logging.WARNING):
        toolwrap.main()

    assert "invalid_group_py_version" in captured_args['find_python_calls']
    assert "fallback_py_version" in captured_args['find_python_calls']

    # Check the order of calls
    # First call is to resolve --python-version for fallback_python_executable
    # Second call is for the group-specific version
    assert captured_args['find_python_calls'].index("fallback_py_version") < captured_args['find_python_calls'].index("invalid_group_py_version")


    assert len(captured_args['create_virtualenv_calls']) == 1
    call_info = captured_args['create_virtualenv_calls'][0]
    assert call_info['python'] == Path("/path/to/fallback_python") # Should use fallback
    assert call_info['path'] == bin_dir / ".venv" / "group_e"

    assert any("Requested Python 'invalid_group_py_version' not found. Using fallback." in message for message in caplog.messages)


# --- Tests for --missing-requirements ---

def basic_fake_create_venv(python_executable, venv_path, dry_run):
    """Basic venv mock sufficient for --missing-requirements tests."""
    if not dry_run:
        venv_path.mkdir(parents=True, exist_ok=True)
        venv_bin = venv_path / ("Scripts" if platform.system() == "Windows" else "bin")
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / ("python.exe" if platform.system() == "Windows" else "python")).touch()
        (venv_bin / ("pip.exe" if platform.system() == "Windows" else "pip")).touch()
    return True

COMMON_SETUP_ARGS = {
    "source_dir_name": "src_reqs",
    "group_name": "req_group",
    "script_name": "script_with_imports.py",
    "reqs_name": "requirements.txt"
}

def _setup_req_test_env(tmp_path, monkeypatch, initial_reqs_content=None, script_content=None, mock_imports=None):
    from unittest.mock import Mock

    source_dir = tmp_path / COMMON_SETUP_ARGS["source_dir_name"]
    bin_dir = tmp_path / "bin" # Default bin directory
    group_dir = source_dir / COMMON_SETUP_ARGS["group_name"]

    source_dir.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    group_dir.mkdir(exist_ok=True)

    script_file = group_dir / COMMON_SETUP_ARGS["script_name"]
    if script_content:
        script_file.write_text(script_content)
    else:
        script_file.write_text("import os\nimport my_missing_package\nimport my_existing_package")

    req_file = group_dir / COMMON_SETUP_ARGS["reqs_name"]
    if initial_reqs_content is not None:
        req_file.write_text(initial_reqs_content)

    # Mocks
    monkeypatch.setattr(toolwrap, "create_virtualenv", basic_fake_create_venv)
    monkeypatch.setattr(toolwrap, "install_dependencies", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "create_wrapper", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "find_python_executable", Mock(return_value=Path(sys.executable)))
    monkeypatch.setattr(toolwrap, "setup_logging", Mock())
    monkeypatch.setattr(toolwrap.shutil, "rmtree", Mock())

    if mock_imports is not None:
        monkeypatch.setattr(toolwrap, "find_third_party_imports", Mock(return_value=mock_imports))

    return source_dir, bin_dir, req_file


def test_missing_requirements_suggest(tmp_path, monkeypatch, caplog): # Changed capsys to caplog
    mock_imports = {'my_missing_package', 'my_existing_package'}
    source_dir, bin_dir, req_file = _setup_req_test_env(
        tmp_path, monkeypatch,
        initial_reqs_content="my_existing_package\n",
        mock_imports=mock_imports
    )

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir),
        "--missing-requirements", "suggest"
    ])
    toolwrap.main()

    # Check caplog for the suggestion message, as it's logged as a warning
    assert any(
        "[SUGGEST] Group 'req_group' missing packages:" in record.message and  # Corrected string
        "my_missing_package" in record.message and
        record.levelname == "WARNING"
        for record in caplog.records
    )
    assert req_file.read_text() == "my_existing_package\n"


def test_missing_requirements_append(tmp_path, monkeypatch):
    mock_imports = {'my_missing_package', 'my_existing_package'}
    source_dir, bin_dir, req_file = _setup_req_test_env(
        tmp_path, monkeypatch,
        initial_reqs_content="my_existing_package\n",
        mock_imports=mock_imports
    )

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir),
        "--missing-requirements", "append"
    ])
    toolwrap.main()

    content = req_file.read_text()
    assert "my_existing_package" in content
    assert "my_missing_package" in content


def test_missing_requirements_omitted(tmp_path, monkeypatch, capsys):
    mock_imports = {'my_missing_package', 'my_existing_package'}
    source_dir, bin_dir, req_file = _setup_req_test_env(
        tmp_path, monkeypatch,
        initial_reqs_content="my_existing_package\n",
        mock_imports=mock_imports
    )
    initial_content = req_file.read_text()

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir)
    ])
    toolwrap.main()

    captured = capsys.readouterr()
    assert "Missing requirements for group req_group:" not in captured.out # No suggestion by default
    assert req_file.read_text() == initial_content


def test_missing_requirements_no_file_append(tmp_path, monkeypatch):
    mock_imports = {'my_new_package'}
    source_dir, bin_dir, req_file = _setup_req_test_env(
        tmp_path, monkeypatch,
        initial_reqs_content=None, # No requirements.txt
        script_content="import my_new_package",
        mock_imports=mock_imports
    )
    if req_file.exists(): # Ensure it really doesn't exist
        req_file.unlink()

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir),
        "--missing-requirements", "append"
    ])
    toolwrap.main()

    assert req_file.exists()
    content = req_file.read_text()
    assert "my_new_package" in content


# --- Tests for detailed python_version.txt handling ---

PVTXT_SETUP_ARGS = {
    "source_dir_name": "src_pvtxt",
    "bin_dir_name": "bin_pvtxt", # Using a distinct bin_dir for these tests
    "script_name": "script.py"
}

def _setup_pvtxt_test_env(tmp_path, monkeypatch, group_name, pvtxt_content):
    from unittest.mock import Mock

    source_dir = tmp_path / PVTXT_SETUP_ARGS["source_dir_name"]
    bin_dir = tmp_path / PVTXT_SETUP_ARGS["bin_dir_name"]
    group_dir = source_dir / group_name

    source_dir.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True)
    group_dir.mkdir(exist_ok=True)

    (group_dir / PVTXT_SETUP_ARGS["script_name"]).write_text("print('hello')")

    if pvtxt_content is not None:
        (group_dir / "python_version.txt").write_text(pvtxt_content)

    captured_args = {'find_python_executable_calls': [], 'create_virtualenv_calls': []}

    current_major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"

    def fake_find_python_executable_for_pvtxt(version_str):
        captured_args['find_python_executable_calls'].append(version_str)
        if version_str == "group_specific_valid":
            return Path("/path/to/group_specific_python")
        if version_str == "unfindable_version" or version_str == "completely_made_up_version_format":
            return None
        if version_str == current_major_minor: # For fallback to current Python
             return Path(sys.executable)
        return Path(sys.executable) # General fallback for the mock

    def fake_create_venv_for_pvtxt(python_executable, venv_path, dry_run):
        captured_args['create_virtualenv_calls'].append({'python': python_executable, 'path': venv_path})
        venv_path.mkdir(parents=True, exist_ok=True)
        venv_bin = venv_path / ("Scripts" if platform.system() == "Windows" else "bin")
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / ("python.exe" if platform.system() == "Windows" else "python")).touch()
        (venv_bin / ("pip.exe" if platform.system() == "Windows" else "pip")).touch()
        return True

    monkeypatch.setattr(toolwrap, "find_python_executable", fake_find_python_executable_for_pvtxt)
    monkeypatch.setattr(toolwrap, "create_virtualenv", fake_create_venv_for_pvtxt)
    monkeypatch.setattr(toolwrap, "install_dependencies", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "create_wrapper", Mock(return_value=True))
    monkeypatch.setattr(toolwrap, "setup_logging", Mock())
    monkeypatch.setattr(toolwrap.shutil, "rmtree", Mock())

    return source_dir, bin_dir, captured_args


def test_python_version_txt_valid_and_used(tmp_path, monkeypatch):
    source_dir, bin_dir, captured_args = _setup_pvtxt_test_env(
        tmp_path, monkeypatch, "pv_group1", "group_specific_valid\n"
    )
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source_dir), "--bin", str(bin_dir)])
    toolwrap.main()

    assert "group_specific_valid" in captured_args['find_python_executable_calls']
    assert len(captured_args['create_virtualenv_calls']) == 1
    venv_call = captured_args['create_virtualenv_calls'][0]
    assert venv_call['python'] == Path("/path/to/group_specific_python")
    assert venv_call['path'].name == "pv_group1"

def test_python_version_txt_unfindable_falls_back_to_default(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    source_dir, bin_dir, captured_args = _setup_pvtxt_test_env(
        tmp_path, monkeypatch, "pv_group2", "unfindable_version\n"
    )
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source_dir), "--bin", str(bin_dir)])
    toolwrap.main()

    assert "unfindable_version" in captured_args['find_python_executable_calls']
    # Expect call for current python version due to fallback
    current_py_version_short = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert current_py_version_short in captured_args['find_python_executable_calls']

    assert len(captured_args['create_virtualenv_calls']) == 1
    venv_call = captured_args['create_virtualenv_calls'][0]
    assert venv_call['python'] == Path(sys.executable) # Falls back to current
    assert venv_call['path'].name == "pv_group2"
    assert any("Requested Python 'unfindable_version' not found." in record.message for record in caplog.records)

def test_python_version_txt_made_up_format_falls_back_to_default(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    source_dir, bin_dir, captured_args = _setup_pvtxt_test_env(
        tmp_path, monkeypatch, "pv_group3", "completely_made_up_version_format\n"
    )
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source_dir), "--bin", str(bin_dir)])
    toolwrap.main()

    assert "completely_made_up_version_format" in captured_args['find_python_executable_calls']
    current_py_version_short = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert current_py_version_short in captured_args['find_python_executable_calls']

    assert len(captured_args['create_virtualenv_calls']) == 1
    venv_call = captured_args['create_virtualenv_calls'][0]
    assert venv_call['python'] == Path(sys.executable)
    assert venv_call['path'].name == "pv_group3"
    assert any("Requested Python 'completely_made_up_version_format' not found." in record.message for record in caplog.records)

def test_python_version_txt_empty_falls_back_to_default(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    source_dir, bin_dir, captured_args = _setup_pvtxt_test_env(
        tmp_path, monkeypatch, "pv_group4", "" # Empty content
    )
    monkeypatch.setattr(sys, "argv", ["toolwrap", "--source", str(source_dir), "--bin", str(bin_dir)])
    toolwrap.main()

    # find_python_executable should not be called with an empty string.
    # It should be called for the default Python version string.
    assert "" not in captured_args['find_python_executable_calls']
    current_py_version_short = f"{sys.version_info.major}.{sys.version_info.minor}"
    # This assertion checks that the fallback mechanism (which uses current_py_version_short) was invoked.
    # It's called once for initializing fallback_python_executable, and if pvtxt is empty, that fallback is used.
    assert captured_args['find_python_executable_calls'].count(current_py_version_short) >= 1

    assert len(captured_args['create_virtualenv_calls']) == 1
    venv_call = captured_args['create_virtualenv_calls'][0]
    assert venv_call['python'] == Path(sys.executable)
    assert venv_call['path'].name == "pv_group4"
    assert any("python_version.txt is empty. Using fallback Python." in record.message for record in caplog.records)


# --- Tests for --verbose ---

def _setup_verbose_test_env(tmp_path, monkeypatch):
    from unittest.mock import Mock

    source_dir = tmp_path / "src_verbose"
    bin_dir = tmp_path / "bin_verbose" # Used to determine log path
    source_dir.mkdir()
    bin_dir.mkdir() # Must exist for log path resolution in main()

    # Mock logging.basicConfig to capture its arguments
    mock_basic_config = Mock()
    monkeypatch.setattr(logging, "basicConfig", mock_basic_config)

    # Minimal mocks for main() to run up to setup_logging
    # Prevent group processing by making iterdir return empty
    monkeypatch.setattr(Path, "iterdir", lambda self: iter([]) if self == source_dir else 실제_iterdir_backup(self) )

    # Backup and restore Path.iterdir if it's too broad
    # A more targeted way: mock what main uses to get groups
    # main uses: all_subdirs = [d for d in source_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
    # So, mocking source_dir.iterdir to yield no directories is fine.
    def fake_iterdir(path_instance):
        if path_instance == source_dir:
            return iter([]) # No groups
        # For other Path.iterdir calls (e.g. inside Path.exists), use original. This is tricky.
        # A simpler approach is to mock the functions that use the groups.
        # Let's mock check_duplicate_wrappers and the main loop's content.
        # For now, the above iterdir mock on source_dir might be okay if no other iterdir is critical before group loop.
        # Actually, toolwrap.main itself calls source_dir.iterdir().
        # So we need to be more specific or mock downstream functions.

    # Let's refine the iterdir mock for source_dir specifically
    original_path_iterdir = Path.iterdir
    def specific_iterdir(path_instance):
        if path_instance == source_dir:
            return iter([])
        return original_path_iterdir(path_instance)
    monkeypatch.setattr(Path, 'iterdir', specific_iterdir)


    # Mocks for functions called after setup_logging that might raise errors if groups are empty or not processed
    monkeypatch.setattr(toolwrap, "check_duplicate_wrappers", Mock(return_value={}))
    monkeypatch.setattr(toolwrap, "find_python_executable", Mock(return_value=Path(sys.executable)))
    # The main loop over groups will not run if source_dir.iterdir() is empty for groups.
    # If it did, we'd mock: create_virtualenv, install_dependencies, create_wrapper

    return source_dir, bin_dir, mock_basic_config

def test_verbose_sets_debug_logging(tmp_path, monkeypatch):
    """--verbose sets logging level to DEBUG."""
    source_dir, bin_dir, mock_basic_config = _setup_verbose_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir), "--verbose"
    ])

    try:
        toolwrap.main()
    except SystemExit: # main calls sys.exit(0) on success
        pass
    except toolwrap.ToolwrapError as e: # Catch if it tries to process non-existent groups
        if "No valid group folders found" in str(e): # Expected if iterdir mock isn't perfect
            pass
        else: raise

    mock_basic_config.assert_called_once()
    call_kwargs = mock_basic_config.call_args.kwargs
    assert call_kwargs.get("level") == logging.DEBUG

def test_no_verbose_sets_info_logging(tmp_path, monkeypatch):
    """Default logging level is INFO when --verbose is not used."""
    source_dir, bin_dir, mock_basic_config = _setup_verbose_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir)
    ])

    try:
        toolwrap.main()
    except SystemExit:
        pass
    except toolwrap.ToolwrapError as e:
        if "No valid group folders found" in str(e):
            pass
        else: raise

    mock_basic_config.assert_called_once()
    call_kwargs = mock_basic_config.call_args.kwargs
    assert call_kwargs.get("level") == logging.INFO


# --- Tests for --include-groups ---

def basic_fake_create_venv_for_include(python_executable, venv_path, dry_run):
    """Simulates venv creation for --include-groups tests."""
    if not dry_run: # In these tests, dry_run will be False
        venv_path.mkdir(parents=True, exist_ok=True)
        venv_bin = venv_path / ("Scripts" if platform.system() == "Windows" else "bin")
        venv_bin.mkdir(parents=True, exist_ok=True)
        (venv_bin / ("python.exe" if platform.system() == "Windows" else "python")).touch()
        (venv_bin / ("pip.exe" if platform.system() == "Windows" else "pip")).touch()
    return True

def _setup_include_groups_test_env(tmp_path, monkeypatch, group_names_scripts=None):
    from unittest.mock import Mock

    source_dir = tmp_path / "src_include_groups"
    # Default bin_dir for these tests: source_dir / "bin"
    # Default venv_root for these tests: source_dir / "bin" / ".venv"
    bin_dir = source_dir / "bin"

    source_dir.mkdir()
    bin_dir.mkdir() # toolwrap.main creates it, but good to have for default venv_root calc

    if group_names_scripts is None:
        group_names_scripts = {
            "group_A": "tool_a.py",
            "group_B": "tool_b.py",
            "group_C": "tool_c.py"
        }

    for group_name, script_name in group_names_scripts.items():
        group_path = source_dir / group_name
        group_path.mkdir()
        (group_path / script_name).write_text(f"print('{script_name} content')")

    mock_create_venv = Mock(side_effect=basic_fake_create_venv_for_include)
    mock_install_deps = Mock(return_value=True)
    mock_create_wrapper = Mock(return_value=True)
    mock_find_py_exe = Mock(return_value=Path(sys.executable))
    mock_setup_logging = Mock() # Mock setup_logging for these tests too
    mock_rmtree = Mock()

    monkeypatch.setattr(toolwrap, "create_virtualenv", mock_create_venv)
    monkeypatch.setattr(toolwrap, "install_dependencies", mock_install_deps)
    monkeypatch.setattr(toolwrap, "create_wrapper", mock_create_wrapper)
    monkeypatch.setattr(toolwrap, "find_python_executable", mock_find_py_exe)
    monkeypatch.setattr(toolwrap, "setup_logging", mock_setup_logging)
    monkeypatch.setattr(toolwrap.shutil, "rmtree", mock_rmtree)

    return source_dir, bin_dir, mock_create_venv, mock_create_wrapper


def test_include_groups_processes_only_specified(tmp_path, monkeypatch):
    source_dir, bin_dir, mock_create_venv, mock_create_wrapper = _setup_include_groups_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), # Uses default bin_dir
        "--include-groups", "group_A,group_C"
    ])
    toolwrap.main()

    venv_paths_called = {call.args[1].name for call in mock_create_venv.call_args_list}
    assert "group_A" in venv_paths_called
    assert "group_C" in venv_paths_called
    assert "group_B" not in venv_paths_called

    wrapper_scripts_called = {call.args[0].name for call in mock_create_wrapper.call_args_list}
    # create_wrapper is called with base name, .cmd is added internally for Windows
    assert "tool_a" in wrapper_scripts_called
    assert "tool_c" in wrapper_scripts_called
    assert "tool_b" not in wrapper_scripts_called


def test_include_groups_warns_on_non_existent_group(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    # Only create A and B for this test
    group_scripts = {"group_A": "tool_a.py", "group_B": "tool_b.py"}
    source_dir, bin_dir, mock_create_venv, mock_create_wrapper = _setup_include_groups_test_env(
        tmp_path, monkeypatch, group_names_scripts=group_scripts
    )

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir),
        "--include-groups", "group_A,non_existent_group"
    ])
    toolwrap.main()

    venv_paths_called = {call.args[1].name for call in mock_create_venv.call_args_list}
    assert "group_A" in venv_paths_called
    assert "group_B" not in venv_paths_called
    assert "non_existent_group" not in venv_paths_called # Ensure it wasn't attempted

    wrapper_scripts_called = {call.args[0].name for call in mock_create_wrapper.call_args_list}
    assert "tool_a" in wrapper_scripts_called
    assert "tool_b" not in wrapper_scripts_called

    assert any("Specified group 'non_existent_group' not found" in record.message for record in caplog.records)


def test_include_groups_processes_all_if_omitted(tmp_path, monkeypatch):
    source_dir, bin_dir, mock_create_venv, mock_create_wrapper = _setup_include_groups_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir) # No --include-groups
    ])
    toolwrap.main()

    venv_paths_called = {call.args[1].name for call in mock_create_venv.call_args_list}
    assert "group_A" in venv_paths_called
    assert "group_B" in venv_paths_called
    assert "group_C" in venv_paths_called
    assert len(venv_paths_called) == 3


    wrapper_scripts_called = {call.args[0].name for call in mock_create_wrapper.call_args_list}
    assert "tool_a" in wrapper_scripts_called
    assert "tool_b" in wrapper_scripts_called
    assert "tool_c" in wrapper_scripts_called
    assert len(wrapper_scripts_called) == 3


# --- Tests for --dry-run ---
import os # Required for mocking os.chmod

DRY_RUN_SETUP_ARGS = {
    "source_dir_name": "src_dry_run",
    "group_name": "group_dry",
    "script_name": "script_dry.py",
    "reqs_name": "requirements.txt"
}

def _setup_dry_run_test_env(tmp_path, monkeypatch, initial_reqs_content="existing_package\n", script_content="import existing_package\nimport missing_package"):
    from unittest.mock import Mock

    source_dir = tmp_path / DRY_RUN_SETUP_ARGS["source_dir_name"]
    # Use a unique bin_dir for dry run tests to avoid interference if not cleaned up fully, though tmp_path helps
    bin_dir = tmp_path / "bin_dry_run"
    group_dir = source_dir / DRY_RUN_SETUP_ARGS["group_name"]

    source_dir.mkdir(exist_ok=True)
    bin_dir.mkdir(exist_ok=True) # main will create this anyway, but good for clarity
    group_dir.mkdir(exist_ok=True)

    (group_dir / DRY_RUN_SETUP_ARGS["script_name"]).write_text(script_content)

    req_file_path = None
    if initial_reqs_content is not None:
        req_file_path = group_dir / DRY_RUN_SETUP_ARGS["reqs_name"]
        req_file_path.write_text(initial_reqs_content)

    # Common mocks for dry-run tests
    # This mock will store actual calls for inspection
    actual_run_command_calls = []
    def mock_run_command_dry_run_aware(cmd: List[str], cwd: Optional[Path]=None, env: Optional[Dict[str, str]]=None, dry_run: bool=False):
        actual_run_command_calls.append({'cmd': cmd, 'cwd': cwd, 'env': env, 'dry_run': dry_run})
        if dry_run:
            # This specific message is from the original run_command
            logging.info("[DryRun] Command execution skipped.")
            return True, "", ""
        # Simulate real execution for any non-dry-run calls (shouldn't happen in these tests)
        return True, "Simulated real output", ""

    # Use a Mock to wrap the function so we can assert it was called,
    # while still executing our custom logic and capturing calls in actual_run_command_calls.
    # Directly monkeypatching with mock_run_command_dry_run_aware makes it hard to use mock_run_command.assert_any_call etc.
    # So, we use a Mock instance and make its side_effect our custom function.
    # We also need to pass the actual_run_command_calls list to the tests.
    mock_run_command_spy = Mock(side_effect=mock_run_command_dry_run_aware)
    monkeypatch.setattr(toolwrap, "run_command", mock_run_command_spy)


    mock_os_chmod = Mock()
    monkeypatch.setattr(os, "chmod", mock_os_chmod)

    monkeypatch.setattr(toolwrap, "find_python_executable", Mock(return_value=Path(sys.executable)))
    # Mock setup_logging again to prevent it from interfering with caplog by reconfiguring handlers.
    monkeypatch.setattr(toolwrap, "setup_logging", Mock())
    monkeypatch.setattr(toolwrap.shutil, "rmtree", Mock())

    return source_dir, bin_dir, group_dir, req_file_path, mock_run_command_spy, actual_run_command_calls, mock_os_chmod


def test_dry_run_no_venv_creation(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    source_dir, bin_dir, group_dir, _, mock_run_command_spy, actual_run_cmd_calls, _ = _setup_dry_run_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir), "--dry-run"
    ])

    toolwrap.main()

    expected_venv_path = bin_dir / ".venv" / DRY_RUN_SETUP_ARGS["group_name"]
    assert not expected_venv_path.exists(), "Venv path should not exist in dry run"

    # Check that run_command was not called for venv creation (i.e., its side_effect which logs was not hit for this)
    # The create_virtualenv function itself logs "[DryRun] Would create venv..." before it would call run_command.
    # So, mock_run_command_spy (which IS run_command) should not have 'venv' in its actual commands.
    venv_command_in_mock_calls = False
    for call_info in actual_run_cmd_calls:
        if "venv" in call_info['cmd']:
            venv_command_in_mock_calls = True
            break
    assert not venv_command_in_mock_calls, "run_command mock should not have been called with 'venv' commands"

    # Check for the specific dry run message from create_virtualenv function
    assert any(f"[DryRun] Would create venv at {expected_venv_path}" in record.message for record in caplog.records)


def test_dry_run_no_wrapper_creation(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    source_dir, bin_dir, group_dir, _, mock_run_command_spy, actual_run_cmd_calls, mock_os_chmod = _setup_dry_run_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir), "--dry-run"
    ])

    toolwrap.main()

    expected_wrapper_path = bin_dir / DRY_RUN_SETUP_ARGS["script_name"].replace(".py", "")
    # Check both .cmd and no suffix for robustness, though platform specific is better
    assert not expected_wrapper_path.exists(), "Wrapper script (no suffix) should not exist in dry run"
    assert not expected_wrapper_path.with_suffix(".cmd").exists(), "Wrapper script (.cmd) should not exist in dry run"

    mock_os_chmod.assert_not_called()

    expected_wrapper_path_platform_specific = expected_wrapper_path
    if platform.system() == "Windows":
        expected_wrapper_path_platform_specific = expected_wrapper_path.with_suffix(".cmd")

    assert any(f"[DryRun] Would write wrapper content to {expected_wrapper_path_platform_specific}" in record.message for record in caplog.records)


def test_dry_run_no_requirements_modification(tmp_path, monkeypatch, caplog):
    from unittest.mock import Mock
    caplog.set_level(logging.INFO) # Correct indentation
    source_dir, bin_dir, group_dir, req_file, mock_run_command_spy, actual_run_cmd_calls, _ = _setup_dry_run_test_env(tmp_path, monkeypatch)

    # Specific mock for this test
    monkeypatch.setattr(toolwrap, "find_third_party_imports", Mock(return_value={'existing_package', 'missing_package'}))

    initial_req_content = req_file.read_text()

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir),
        "--missing-requirements", "append", "--dry-run"
    ])

    toolwrap.main()

    assert req_file.read_text() == initial_req_content, "requirements.txt should not be modified in dry run"
    # Check that the informational message about appending is logged (it appears before the dry_run check)
    assert any(f"[APPEND] Appending missing packages to {req_file}" in record.message for record in caplog.records)
    # And ensure no specific "DRY RUN: Would append" message is there if it wasn't designed in.
    # The key is that the file isn't changed.


def test_dry_run_no_pip_install(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    source_dir, bin_dir, group_dir, _, mock_run_command_spy, actual_run_cmd_calls, _ = _setup_dry_run_test_env(tmp_path, monkeypatch)

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir), "--dry-run"
    ])

    toolwrap.main()

    pip_install_call_found_with_dry_run_true = False
    for call_info in actual_run_cmd_calls:
        cmd_list = call_info['cmd']
        # Check if 'pip' and 'install' are in the command list
        is_pip_install_command = any("pip" in str(c).lower() for c in cmd_list) and "install" in cmd_list
        if is_pip_install_command:
            assert call_info['dry_run'] is True, "pip install command should be called with dry_run=True"
            pip_install_call_found_with_dry_run_true = True
            break # Found one, that's enough to confirm it's respecting dry_run flag for pip

    # We expect install_dependencies to ATTEMPT to run pip commands,
    # but those calls to run_command (mocked by mock_run_command_spy)
    # should have dry_run=True.
    # The mock_run_command_dry_run_aware will then log "[DryRun] Command execution skipped."
    # So, we need to ensure that such calls were made.
    # The number of calls could be 1 (pip upgrade only if no reqs) or 2 (pip upgrade + reqs).
    assert pip_install_call_found_with_dry_run_true, "Expected pip install to be called with dry_run=True"

    # Check that the mock (simulating original run_command) logged the skip message
    assert "[DryRun] Command execution skipped." in caplog.text


def test_missing_requirements_empty_file_append(tmp_path, monkeypatch):
    mock_imports = {'my_new_package'}
    source_dir, bin_dir, req_file = _setup_req_test_env(
        tmp_path, monkeypatch,
        initial_reqs_content="", # Empty requirements.txt
        script_content="import my_new_package",
        mock_imports=mock_imports
    )

    monkeypatch.setattr(sys, "argv", [
        "toolwrap", "--source", str(source_dir), "--bin", str(bin_dir),
        "--missing-requirements", "append"
    ])
    toolwrap.main()

    content = req_file.read_text()
    assert "my_new_package" in content
