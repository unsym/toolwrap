#!/usr/bin/env python3
"""
Bootstrap Virtual Environments for Personal Command-Line Python Tools (v_implementation_W_updated)

This script automates the setup and management of isolated Python environments
for command-line scripts grouped by functionality within subfolders.

Key Features:
- Scans subfolders (groups) in a source directory.
- Creates/updates dedicated virtual environments per group.
- Supports per-group Python version specification (`python_version.txt`).
- Installs dependencies from `requirements.txt`, after upgrading pip.
- Optionally detects missing third-party imports (`--missing-requirements`).
- Generates bash wrappers in a bin directory for easy command-line access.
- Handles platform differences (Unix/Windows) for venv paths.
- Uses robust AST parsing for import detection.
- Provides detailed logging and dry-run capability.
"""

import argparse
import ast
import importlib.util
import logging
import re
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# --- Configuration ---
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_FILENAME = "bootstrap_envs.log"
PYTHON_VERSION_FILENAME = "python_version.txt"
REQUIREMENTS_FILENAME = "requirements.txt"


# --- Exception class ---

class BootstrapError(Exception):
    """Custom exception to signal critical bootstrap errors."""
    pass


# --- Helper Functions ---

def setup_logging(log_file_path: Path, dry_run: bool, verbose: bool = False):
    """Configures logging to file and console."""
    log_level = logging.DEBUG if verbose else logging.INFO
    log_file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure log dir exists

    console_formatter = logging.Formatter(
        f"{'[DryRun] ' if dry_run else ''}%(levelname)s: %(message)s"
    )
    file_formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)

    # Configure root logger
    logging.basicConfig(level=log_level, handlers=[file_handler, console_handler])
    logging.info("Logging initialized.")


def run_command(
    cmd: List[str],
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    dry_run: bool = False,
) -> Tuple[bool, str, str]:
    """
    Executes a command, captures output, logs details, and returns status.

    Returns:
        Tuple[bool, str, str]: (success_status, stdout, stderr)
    """
    cmd_str = shlex.join(cmd)
    logging.debug(f"Running command: {cmd_str}" + (f" in {cwd}" if cwd else ""))
    if dry_run:
        logging.info("[DryRun] Command execution skipped.")
        return True, "", ""

    try:
        process_env = os.environ.copy()
        if env:
            process_env.update({k: str(v) for k, v in env.items()})  # Ensure env vars are strings

        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,  # We check returncode manually for better logging
            env=process_env,
            encoding='utf-8',
            errors='surrogateescape'  # Handle potential weird output
        )

        if result.returncode != 0:
            logging.error(f"Command failed with exit code {result.returncode}: {cmd_str}")
            if result.stderr:
                logging.error(f"Stderr:\n{result.stderr.strip()}")
            if result.stdout:
                logging.error(f"Stdout:\n{result.stdout.strip()}")
            return False, result.stdout, result.stderr
        else:
            logging.debug(f"Command successful. Stdout:\n{result.stdout.strip()}")
            return True, result.stdout, result.stderr

    except FileNotFoundError:
        logging.error(f"Command not found: {cmd[0]}")
        return False, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        logging.error(f"Error running command '{cmd_str}': {e}")
        logging.debug("Traceback:", exc_info=True)
        return False, "", str(e)


def find_python_executable(version_str: Optional[str]) -> Optional[Path]:
    """Tries to find a python executable for the given version string (e.g., '3.9')."""
    if not version_str:
        return None

    potential_names = [f"python{version_str}"]
    # Add "pythonX.Y" if version_str is like "X.Y" and not already prefixed
    if '.' in version_str and not version_str.startswith('python'):
         major_minor = version_str.split('.')[:2]
         potential_names.append(f"python{'.'.join(major_minor)}")
    # Also try plain version number if it was given like that
    if not version_str.startswith('python'):
         potential_names.append(version_str)

    # De-duplicate while preserving order
    checked_names = set()
    unique_potential_names = []
    for name in potential_names:
        if name not in checked_names:
            unique_potential_names.append(name)
            checked_names.add(name)

    for name in unique_potential_names:
        executable_path = shutil.which(name)
        if executable_path:
            logging.debug(f"Found Python executable for '{version_str}' via '{name}': {executable_path}")
            return Path(executable_path)

    logging.warning(f"Could not find Python executable for version '{version_str}' in PATH.")
    return None


def is_standard_library(module_name: str) -> bool:
    """Checks if a module name belongs to the Python standard library."""
    if not module_name or '.' in module_name:
         module_name = module_name.split('.')[0]

    if module_name in sys.builtin_module_names:
        return True
    if hasattr(sys, 'stdlib_module_names') and module_name in sys.stdlib_module_names:
        return True

    try:
        spec = importlib.util.find_spec(module_name)
        if spec is None or spec.origin is None:
            return False
        if spec.origin in ('built-in', 'frozen'):
            return True
        origin_path = Path(spec.origin).resolve()
        stdlib_paths = [sysconfig.get_path('stdlib'), sysconfig.get_path('platstdlib')]
        py_prefix_lib = Path(sys.prefix) / 'lib'
        if py_prefix_lib.is_dir():
            stdlib_paths.append(str(py_prefix_lib))
        for stdlib_path_str in stdlib_paths:
            if stdlib_path_str:
                stdlib_path = Path(stdlib_path_str).resolve()
                try:
                    if origin_path.is_relative_to(stdlib_path):
                        return True
                except AttributeError:
                    if os.path.commonprefix([str(origin_path), str(stdlib_path)]) == str(stdlib_path):
                        return True
                except ValueError:
                    pass
        if 'site-packages' not in spec.origin.lower() and 'dist-packages' not in spec.origin.lower():
             logging.debug(f"Module '{module_name}' origin '{spec.origin}' not in site/dist-packages; assuming stdlib.")
             return True

    except ModuleNotFoundError:
        return False
    except Exception as e:
        logging.warning(f"Could not determine if '{module_name}' is stdlib: {e}. Assuming non-stdlib.")
        return False

    return False


def find_third_party_imports(py_files: List[Path]) -> Set[str]:
    """Scans Python files for third-party imports using AST parsing."""
    imports = set()
    for py_file in py_files:
        logging.debug(f"Scanning for imports in: {py_file}")
        try:
            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]
                        if module_name and not is_standard_library(module_name):
                            imports.add(module_name)
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        module_name = node.module.split('.')[0]
                        if module_name and not is_standard_library(module_name):
                            imports.add(module_name)
        except SyntaxError as e:
            logging.warning(f"Skipping import scan for {py_file} due to SyntaxError: {e}")
        except Exception as e:
            logging.warning(f"Error parsing {py_file} for imports: {e}")
            logging.debug("Traceback:", exc_info=True)
    logging.debug(f"Found third-party imports: {imports}")
    return imports


def parse_requirements(req_file: Path) -> Set[str]:
    """
    Parses a requirements.txt file, returning a set of base package names.
    Ignores comments and blank lines.
    """
    packages = set()
    if not req_file.is_file():
        return packages
    try:
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'^([a-zA-Z0-9_.-]+)', line)
            if match:
                packages.add(match.group(1).lower())
            else:
                logging.warning(f"Could not parse package from line: '{line}' in {req_file}")
    except Exception as e:
        logging.error(f"Error reading {req_file}: {e}")
    return packages


def create_bash_wrapper(
    wrapper_path: Path,
    venv_path: Path,
    target_script_path: Path,
    dry_run: bool = False
) -> bool:
    """
    Generates and writes the bash wrapper script.
    
    Modification:
      Instead of using the resolved absolute python executable from the venv,
      the wrapper now calls "python" after activation. This ensures that the 
      virtual environment's activated PATH is used and that any symlink resolution 
      (which might yield the system python) is bypassed.
    """
    logging.debug(f"Creating wrapper script: {wrapper_path}")

    abs_venv_path = venv_path.resolve()
    abs_target_script_path = target_script_path.resolve()

    # Determine the activation script path based on platform.
    activate_script_name = 'Scripts/activate' if platform.system() == "Windows" else 'bin/activate'
    activate_script = (abs_venv_path / activate_script_name).resolve()

    # Instead of resolving the python executable from the venv, we will use "python"
    # after activating the virtual environment.
    # The generated wrapper will call "exec python ..." so that the activated interpreter is used.
    wrapper_content = f"""#!/usr/bin/env bash
# Wrapper script generated by bootstrap_envs.py for:
# Target Script: {shlex.quote(str(abs_target_script_path))}

set -e

VENV_PATH={shlex.quote(str(abs_venv_path))}
SCRIPT_PATH={shlex.quote(str(abs_target_script_path))}
ACTIVATE_SCRIPT={shlex.quote(str(activate_script))}

if [ ! -f "$ACTIVATE_SCRIPT" ]; then
    echo "Error: Activation script not found at $ACTIVATE_SCRIPT" >&2
    exit 1
fi
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: Target script not found at $SCRIPT_PATH" >&2
    exit 1
fi

. "$ACTIVATE_SCRIPT"
exec python "$SCRIPT_PATH" "$@"
"""

    if dry_run:
        logging.info(f"[DryRun] Would write wrapper content to {wrapper_path}:\n{wrapper_content}")
        return True

    try:
        with open(wrapper_path, "w", encoding="utf-8") as f:
            f.write(wrapper_content)
        os.chmod(wrapper_path,
                 stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        logging.debug(f"Successfully created wrapper: {wrapper_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to create wrapper {wrapper_path}: {e}")
        if wrapper_path.exists():
            try:
                wrapper_path.unlink()
            except OSError:
                pass
        return False


# --- Virtual Environment Setup ---

def create_virtualenv(python_exec: Path, venv_path: Path, dry_run: bool) -> bool:
    """Creates a virtual environment at the specified path."""
    if dry_run:
        logging.info(f"[DryRun] Would create venv at {venv_path} using {python_exec}")
        return True
    try:
        cmd = [str(python_exec), "-m", "venv", str(venv_path)]
        success, _, _ = run_command(cmd, dry_run=dry_run)
        return success
    except Exception as e:
        logging.error(f"Error creating venv: {e}")
        return False


def install_dependencies(venv_path: Path, req_file: Path, dry_run: bool) -> bool:
    """Upgrades pip and installs dependencies from the requirements file."""
    venv_bin_dir = venv_path / ('Scripts' if platform.system() == "Windows" else 'bin')
    venv_pip = venv_bin_dir / ('pip.exe' if platform.system() == "Windows" else 'pip')

    # Upgrade pip first (best practice)
    upgrade_cmd = [str(venv_pip), "install", "--upgrade", "pip"]
    logging.info(f"Upgrading pip in venv {venv_path}...")
    success, _, _ = run_command(upgrade_cmd, dry_run=dry_run)
    if not success:
        logging.error(f"Failed to upgrade pip in venv at {venv_path}.")
        return False

    if req_file.is_file():
        install_cmd = [str(venv_pip), "install", "-r", str(req_file)]
        logging.info(f"Installing dependencies from {req_file}...")
        success, _, _ = run_command(install_cmd, dry_run=dry_run)
        return success
    else:
        logging.info(f"{req_file} not found; skipping dependency installation.")
        return True


def check_duplicate_wrappers(target_groups: List[Path]) -> dict:
    duplicate_wrappers = {}
    for group in target_groups:
        py_files = list(group.glob("*.py"))
        for py_file in py_files:
            wrapper_name = py_file.stem
            if wrapper_name in duplicate_wrappers:
                duplicate_wrappers[wrapper_name].append(group.name)
            else:
                duplicate_wrappers[wrapper_name] = [group.name]
    collisions = {name: groups for name, groups in duplicate_wrappers.items() if len(groups) > 1}
    return collisions


# --- Main Bootstrap Process ---

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Virtual Environments for Personal Command-Line Tools",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source", type=Path, default=Path("."),
                        help="Root directory containing tool groups (subfolders).")
    parser.add_argument("--bin", type=Path, default=Path("bin"),
                        help="Directory to place generated bash wrapper scripts. Default is the 'bin' folder under the source directory.")
    parser.add_argument("--venv-root", type=Path, default=None,
                        help="Directory under which virtual environments are created. Default is the '.venv' folder inside the bin directory.")
    parser.add_argument("--python-version", type=str, default=None,
                        help="Fallback Python version (e.g., '3.9') if not specified in group.")
    parser.add_argument("--missing-requirements", choices=["suggest", "append"], default=None,
                        help="Action for missing third-party imports not in requirements.txt.")
    parser.add_argument("--recreate-all", action="store_true",
                        help="Remove and recreate all virtual environments.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate actions without making changes.")
    parser.add_argument("--include-groups", type=str, default=None,
                        help=("Comma-separated list of specific group folder names to process. "
                              "If omitted, all direct subfolders are processed."))
    parser.add_argument("--verbose", action="store_true",
                        help="Increase output verbosity (DEBUG level logging).")

    args = parser.parse_args()

    source_dir = args.source.expanduser().resolve()
    if not args.bin.is_absolute():
        bin_dir = (source_dir / args.bin).resolve()
    else:
        bin_dir = args.bin.resolve()

    if args.venv_root is None:
        venv_root_dir = (bin_dir / ".venv").resolve()
    elif not args.venv_root.is_absolute():
        venv_root_dir = (source_dir / args.venv_root).resolve()
    else:
        venv_root_dir = args.venv_root.resolve()
    log_file = venv_root_dir / LOG_FILENAME

    setup_logging(log_file, args.dry_run, args.verbose)
    logging.info("--- Starting Bootstrap Environments ---")
    logging.info(f"Source: {source_dir}, Bin: {bin_dir}, Venv Root: {venv_root_dir}")
    logging.info(f"Missing Requirements Action: {args.missing_requirements or 'None'}")
    logging.info(f"Recreate All: {args.recreate_all}, Dry Run: {args.dry_run}")

    if not source_dir.is_dir():
        error_msg = f"Source directory not found: {source_dir}"
        logging.error(error_msg)
        raise BootstrapError(error_msg)

    for dir_path in [bin_dir, venv_root_dir]:
        if not dir_path.exists():
            logging.debug(f"Creating directory: {dir_path}")
            if not args.dry_run:
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    error_msg = f"Failed to create directory {dir_path}: {e}"
                    logging.error(error_msg)
                    raise BootstrapError(error_msg)
        elif not dir_path.is_dir():
            error_msg = f"Path exists but is not a directory: {dir_path}"
            logging.error(error_msg)
            raise BootstrapError(error_msg)

    # Identify group folders
    all_subdirs = [d for d in source_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
    target_groups: List[Path] = []
    if args.include_groups:
        included_names = {name.strip() for name in args.include_groups.split(",") if name.strip()}
        logging.info(f"Processing specified groups: {', '.join(sorted(included_names))}")
        group_map = {d.name: d for d in all_subdirs}
        for name in included_names:
            if name in group_map:
                target_groups.append(group_map[name])
            else:
                logging.warning(f"Specified group '{name}' not found in {source_dir}.")
    else:
        logging.info("Processing all subdirectories in source.")
        target_groups = all_subdirs

    if not target_groups:
        error_msg = "No valid group folders found."
        logging.error(error_msg)
        raise BootstrapError(error_msg)
    
    collisions = check_duplicate_wrappers(target_groups)
    if collisions:
        collision_names = set(collisions.keys())
        logging.warning("Duplicate wrapper names detected: " + ", ".join(sorted(collision_names)) +
                        ". These wrappers will not be generated across any groups. Please rename the conflicting source .py files.")
    else:
        collision_names = set()

    fallback_version_str = args.python_version or f"{sys.version_info.major}.{sys.version_info.minor}"
    fallback_python_executable = find_python_executable(fallback_version_str)
    if not fallback_python_executable:
        logging.warning(f"Fallback Python '{fallback_version_str}' not found. Using current interpreter: {sys.executable}")
        fallback_python_executable = Path(sys.executable)
    else:
        logging.info(f"Using fallback Python: {fallback_version_str} ({fallback_python_executable})")

    processed_groups: List[str] = []
    encountered_errors = False
    generated_wrapper_targets: Dict[str, Path] = {}
    summary_actions = {
        "venvs_created": [], "venvs_reused": [], "venvs_recreated": [],
        "deps_installed": [], "deps_suggested": [], "deps_appended": [],
        "pip_upgraded": [], "wrappers_generated": []
    }

    for group_dir in target_groups:
        group_name = group_dir.name
        logging.info(f"--- Processing Group: {group_name} ---")
        py_files = sorted(list(group_dir.glob("*.py")))
        if not py_files:
            logging.warning(f"No Python files found in {group_dir}. Skipping group.")
            continue

        processed_groups.append(group_name)
        python_executable = fallback_python_executable
        python_version_file = group_dir / PYTHON_VERSION_FILENAME
        if python_version_file.is_file():
            try:
                version_requested = python_version_file.read_text(encoding="utf-8").strip()
                if version_requested:
                    logging.info(f"Found {PYTHON_VERSION_FILENAME}: requesting '{version_requested}'")
                    found_exec = find_python_executable(version_requested)
                    if found_exec:
                        python_executable = found_exec
                        logging.info(f"Using requested Python: {python_executable}")
                    else:
                        logging.warning(f"Requested Python '{version_requested}' not found. Using fallback.")
                else:
                    logging.warning(f"{PYTHON_VERSION_FILENAME} is empty. Using fallback Python.")
            except Exception as e:
                logging.warning(f"Error reading {PYTHON_VERSION_FILENAME}: {e}. Using fallback Python.")
        else:
            logging.info(f"No {PYTHON_VERSION_FILENAME} found. Using fallback Python: {python_executable}")

        # Create/Recreate venv
        venv_path = venv_root_dir / group_name
        if args.recreate_all and venv_path.is_dir():
            logging.info(f"Recreate-all: Removing existing venv at {venv_path}")
            if not args.dry_run:
                try:
                    shutil.rmtree(venv_path)
                except OSError as e:
                    logging.error(f"Failed to remove venv at {venv_path}: {e}")
                    encountered_errors = True
                    continue
            summary_actions["venvs_recreated"].append(group_name)
        if not venv_path.is_dir():
            logging.info(f"Creating venv for group '{group_name}' at {venv_path} using {python_executable}")
            if create_virtualenv(python_executable, venv_path, args.dry_run):
                summary_actions["venvs_created"].append(group_name)
            else:
                logging.error(f"Failed to create venv for {group_name}. Skipping group.")
                encountered_errors = True
                continue
        else:
            logging.info(f"Reusing existing venv at {venv_path}")
            summary_actions["venvs_reused"].append(group_name)

        # Check venv executables
        venv_bin_dir = venv_path / ('Scripts' if platform.system() == "Windows" else 'bin')
        venv_python = venv_bin_dir / ('python.exe' if platform.system() == "Windows" else 'python')
        venv_pip = venv_bin_dir / ('pip.exe' if platform.system() == "Windows" else 'pip')
        if not args.dry_run and not (venv_python.is_file() and venv_pip.is_file()):
            error_msg = f"Venv at {venv_path} appears incomplete (missing python or pip) for group '{group_name}'."
            logging.error(error_msg)
            raise BootstrapError(error_msg)

        # Handle dependencies
        requirements_file = group_dir / REQUIREMENTS_FILENAME
        installed_packages = parse_requirements(requirements_file) if requirements_file.is_file() else set()
        if requirements_file.is_file():
            logging.debug(f"Found {REQUIREMENTS_FILENAME} with packages: {', '.join(sorted(installed_packages)) or 'None'}")
        else:
            logging.info(f"No {REQUIREMENTS_FILENAME} for group '{group_name}'.")

        if args.missing_requirements in ["suggest", "append"]:
            logging.debug("Scanning Python files for third-party imports...")
            detected_imports = find_third_party_imports(py_files)
            logging.debug(f"Detected imports: {', '.join(sorted(detected_imports)) or 'None'}")
            missing_pkgs = detected_imports - installed_packages
            if missing_pkgs:
                missing_str = ", ".join(sorted(missing_pkgs))
                if args.missing_requirements == "suggest":
                    logging.warning(f"[SUGGEST] Group '{group_name}' missing packages: {missing_str}.")
                    summary_actions["deps_suggested"].append(f"{group_name}: {missing_str}")
                elif args.missing_requirements == "append":
                    logging.info(f"[APPEND] Appending missing packages to {requirements_file}: {missing_str}.")
                    if not args.dry_run:
                        try:
                            if not requirements_file.exists():
                                requirements_file.parent.mkdir(parents=True, exist_ok=True)
                                requirements_file.write_text("", encoding="utf-8")
                            with open(requirements_file, "a", encoding="utf-8") as f:
                                f.write("\n# --- Auto-appended by bootstrap_envs.py ---\n")
                                for pkg in sorted(missing_pkgs):
                                    f.write(f"{pkg}\n")
                            installed_packages.update(missing_pkgs)
                            summary_actions["deps_appended"].append(f"{group_name}: {missing_str}")
                        except Exception as e:
                            logging.error(f"Failed to append to {requirements_file}: {e}")
                            encountered_errors = True
            else:
                logging.info("No missing third-party imports detected.")

        # Upgrade pip before installing dependencies
        if not install_dependencies(venv_path, requirements_file, args.dry_run):
            logging.error(f"Dependency installation failed for group '{group_name}'.")
            encountered_errors = True
        else:
            summary_actions["deps_installed"].append(group_name)
        # Generate bash wrappers for Python scripts, handling duplicate names by skipping duplicates.
        logging.info("Generating bash wrappers for Python scripts...")
        for py_file in py_files:
            wrapper_name = py_file.stem
            if wrapper_name in collision_names:
                logging.warning(f"Wrapper '{wrapper_name}' is in duplicate collision (detected in multiple groups). Skipping generation for group '{group_name}'.")
                continue
            wrapper_path = bin_dir / wrapper_name
            if wrapper_name in generated_wrapper_targets:
                conflict = generated_wrapper_targets[wrapper_name]
                logging.warning(f"Wrapper collision: '{wrapper_name}' already exists for group '{conflict.parent.name}'. Skipping generation for group '{group_name}'.")
                continue
            if create_bash_wrapper(wrapper_path, venv_path, py_file, args.dry_run):
                generated_wrapper_targets[wrapper_name] = py_file
                try:
                    rel_path = wrapper_path.relative_to(Path.home())
                    summary_actions["wrappers_generated"].append(f"~/{rel_path}")
                except ValueError:
                    summary_actions["wrappers_generated"].append(str(wrapper_path))
            else:
                encountered_errors = True

        logging.info(f"--- Finished processing group: {group_name} ---")
        processed_groups.append(group_name)

    # --- Final Summary ---
    logging.info("--- Bootstrap Environments Summary ---")
    if args.dry_run:
        logging.info("NOTE: Dry-run mode active. No changes were made.")
    logging.info(f"Processed groups ({len(processed_groups)}): {', '.join(sorted(processed_groups)) or 'None'}")
    if summary_actions["venvs_created"]:
        logging.info(f"New venvs created: {', '.join(sorted(summary_actions['venvs_created']))}")
    if summary_actions["venvs_recreated"]:
        logging.info(f"Venvs recreated: {', '.join(sorted(summary_actions['venvs_recreated']))}")
    if summary_actions["venvs_reused"]:
        logging.info(f"Existing venvs reused: {', '.join(sorted(summary_actions['venvs_reused']))}")
    if summary_actions["pip_upgraded"]:
        logging.info(f"Pip upgraded in venvs for: {', '.join(sorted(summary_actions['pip_upgraded']))}")
    if summary_actions["deps_installed"]:
        logging.info(f"Dependencies installed for: {', '.join(sorted(summary_actions['deps_installed']))}")
    if summary_actions["deps_suggested"]:
        logging.info("Suggested missing dependencies:")
        for s in sorted(summary_actions["deps_suggested"]):
            logging.info(f"  - {s}")
    if summary_actions["deps_appended"]:
        logging.info("Appended missing dependencies for:")
        for s in sorted(summary_actions["deps_appended"]):
            logging.info(f"  - {s}")
    if summary_actions["wrappers_generated"]:
        logging.info(f"Generated wrappers ({len(summary_actions['wrappers_generated'])}):")
        for w in sorted(summary_actions["wrappers_generated"]):
            logging.info(f"  - {w}")
    else:
        logging.info("No wrappers generated.")
    logging.info(f"Log file located at: {log_file}")
    if encountered_errors:
        error_msg = "Bootstrap process completed with errors. Review the logs above."
        logging.error(error_msg)
        raise BootstrapError(error_msg)
    else:
        logging.info("Bootstrap process completed successfully.")
        return


if __name__ == "__main__":
    try:
        main()
    except BootstrapError as e:
        logging.error("Critical error encountered:")
        logging.error(e)
        sys.exit(1)
    except Exception as e:
        logging.exception("An unexpected error occurred:")
        sys.exit(1)
    else:
        logging.info("Bootstrap process completed successfully.")
        sys.exit(0)
