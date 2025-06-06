# Toolwrap: Automatic Python script environment setup and CLI wrappers (full)
*For a quick introduction, see [README.md](README.md). This document contains the full reference.*


## 1. Overview and Purpose

The **toolwrap.py** tool automates the setup and management of isolated Python environments for a collection of command-line scripts grouped by functionality. Each group resides in a separate subfolder, containing Python scripts along with optional dependency and Python version requirements. This utility:

1. Identifies all relevant subfolders  (or specified subsets) under a root directory.  
2. For each subfolder (group), sets up or updates a dedicated virtual environment for all Python scripts in that folder.  
3. Installs dependencies listed in a `requirements.txt` file (with optional auto-detection of missing third-party libraries).  
4. Creates or updates wrapper scripts in a user-specified bin directory (bash on POSIX, `.cmd` on Windows), enabling each Python script to be invoked by name from the command line with its virtual environment automatically activated.

This design avoids version conflicts between scripts, simplifies re-creating setups on new machines, and keeps a user’s global environment clean.  

---

## 2. Rationale

1. **Dependency Isolation:**  
   Each group’s Python virtual environment is kept separate, preventing package conflicts when scripts rely on different or incompatible libraries.

2. **Portability and Reproducibility:**
   Because the tool manages creation and maintenance of virtual environments and wrappers, the structure can be cloned, set up again using `toolwrap`, and run on any machine without manual environment activation.

3. **Wrapper Convenience:**
   Wrapper scripts are generated so that each tool can be run as a command from a designated bin folder (e.g., `~/bin/`), without needing to manually activate the correct environment. On Windows, these are `.cmd` files; on POSIX systems, bash scripts are created.

4. **Optional Dependency Detection:**  
   The tool performs a basic scan of user scripts for simple static import statements referencing **third-party** libraries. This approach may not catch dynamic or conditional imports, but it is sufficient as an assistive measure to help ensure that `requirements.txt` includes the most common dependencies. It can optionally suggest missing dependencies or automatically append them.

5. **Python Version Control:**  
   By supporting per-group Python versions via a simple `python_version.txt` file, each group’s environment can match the version intended by the script author.

---

## 3. Folder Structure

The tool expects a root directory (specified via `--source`) containing one or more **direct** subfolders. **Only the top-level subfolders** under that directory are considered separate groups by default (i.e., one level down). **If you intend to handle deeper nested folders, you must adjust or extend the logic accordingly.** Each group subfolder should house related command-line scripts. For each group, you typically have:

- **One or more `.py` Python scripts** implementing individual command-line tools.  
- An **optional `requirements.txt`** listing libraries to install in the group’s virtual environment. This is required for non-standard libraries and can be automatically created using `--missing-requirements`.  
- An **optional `python_version.txt`** specifying the Python version for that group (overriding the fallback version).

**If a subfolder contains no `.py` files, the tool will skip creating a virtual environment for that folder.**

For example, if `--source` is set to `./example_tools`, your structure might look like this:

```
example_tools/
├── math_tools/
│   ├── sum_array.py
│   └── sum_matrix.py
├── media_tools/
│   ├── resize_img.py
│   ├── requirements.txt
│   └── python_version.txt
```

Where:
- `math_tools/` and `media_tools/` are group folders.
- Each `.py` file becomes a standalone command once the script has generated its corresponding wrapper.
- Each group can have its own dependencies and Python version requirements.

### Additional Notes on Configuration Files

- **`requirements.txt`**  
  This file should follow standard [pip-compatible format](https://pip.pypa.io/en/stable/reference/requirement-specifiers/), with one package per line. For example:

  ```
  requests
  numpy>=1.20
  pandas==1.3.5
  Pillow!=9.0.0
  ```

  - Version specifiers such as `==`, `>=`, `<=`, `!=` are supported.
  - Blank lines and comments (starting with `#`) are allowed.
  - Avoid using editable installs (`-e .`) or VCS-based requirements (`git+https://...`) unless you explicitly support such setups. These are not handled by the auto-detection logic used with `--missing-requirements`.
  - *Clarification: Packages listed in `requirements.txt` are always installed, even if the tool’s auto-detection feature doesn’t find direct imports for them. The tool does **not** remove “unused” packages from `requirements.txt` nor change existing content, just append.*

- **`python_version.txt`**  
  This file should contain a **single line** specifying the desired Python version as a version string only. For example:

  ```
  3.9
  ```

  - Only use the version number (e.g., `3.8`, `3.11`).  
  - Do **not** include `python` (e.g., avoid `python3.9`), paths (e.g., `/usr/bin/python3.9`), or shell commands.  
  - The specified version must be available on the system and discoverable (e.g., `python3.9` should work in shell).  
  - If not found, a warning is logged, and the tool falls back to `--python-version` (if set) or else the interpreter used to invoke `toolwrap.py`. The process continues; it does **not** abort.

---

## 4. Command-Line Arguments

The script can be run as:

```bash
python3 toolwrap.py [OPTIONS]
```

Available arguments:

- **`--source`**
  **Description:** Root directory containing tool groups. Each subfolder is treated as a group (one level deep).  
  **Default:** Current directory (`.`)

  - **`--bin`**
    **Description:** Directory where the generated wrapper scripts will be placed. Each script becomes an executable command here. Default is the `bin/` folder under the source directory.
    **Default:** `bin/`

- **`--venv-root`**
  **Description:** Directory under which virtual environments are created. Default is the `.venv` folder inside the bin directory.
  **Default:** `<source>/bin/.venv` (if --bin is not overridden)

- **`--python-version`**  
  **Description:** Fallback Python version to use if a group does not specify one via `python_version.txt`, or if the specified version is unavailable on the system.  
  **Default:** Version of the Python interpreter used to run `toolwrap.py`

- **`--missing-requirements`**  
  **Description:** Controls how the tool handles **third-party** packages that are imported in scripts but missing from `requirements.txt`. Standard library imports are ignored.  
  **Options:**  
  - *(Omitted)* – Only installs what is already listed in `requirements.txt`.  
  - `suggest` – Prints any missing packages that should be added.  
  - `append` – Automatically appends missing package names (without versions) to `requirements.txt`.

- **`--recreate-all`**
  **Description:** Remove existing virtual environment folders before creation. If `--include-groups` is **not** supplied, every subdirectory under `--venv-root` is deleted. When specific groups are listed via `--include-groups`, only those matching subdirectories are removed.
  **Default:** Not set (reuses existing environments if present)

- **`--dry-run`**  
  **Description:** Simulates all actions (environment creation, dependency installation, wrapper generation) without performing them.  
  **Default:** Not set

- **`--include-groups`**  
  **Description:** Comma-separated list of specific group folder names to process (e.g., `math_tools,media_tools`).
  If omitted, all subfolders in `--source` are processed.  
  **Default:** Not set (processes all groups)  
  *If a specified group does not exist, the tool logs a warning and skips it.*

 - **`--verbose`**  
   **Description:** Increase output verbosity to DEBUG level. When enabled, detailed internal operations (such as command invocations and file operations) are logged. By default, only high-level progress, warnings, and errors are shown.  
   **Default:** Not enabled (INFO level logging)

---

## 5. Usage Example

See [example_tools/README.md](example_tools/README.md) for an overview of the
sample scripts used in this guide.

```bash
python toolwrap.py \
  --source ./example_tools \
  --bin ./bin \
  --venv-root ./bin/.venvs \
  --missing-requirements append \
  --recreate-all \
  --include-groups math_tools,media_tools
```

The tool will:

1. Look under `./example_tools` only at `math_tools` and `media_tools` (ignoring any other subfolders).
2. Remove any existing environments for these two groups, recreate them under `./bin/.venvs/`, then install dependencies from each group’s `requirements.txt`.
3. Append any newly detected libraries to `requirements.txt` files.
4. Generate or overwrite command wrappers in `./bin`.
5. Update `./bin/.venvs/toolwrap_envs.log` with the details.

---

## 6. Operational Workflow

1. **Determine Groups to Process:**  
   - If `--include-groups` is provided (e.g., `math_tools,media_tools`), only those subfolders are processed.
   - Otherwise, process **all direct subfolders** in the `--source` directory.  
   - *If a listed group does not exist, a warning is logged.*  
   - **Folders with no `.py` files are skipped.**

2. **Resolve Python Version:**  
   - If a group subfolder has `python_version.txt`, parse that file’s contents as the Python version.  
   - If the system doesn’t have that version installed or discoverable, log a warning and fall back to `--python-version` (if set), or to the interpreter running `toolwrap.py`.  
   - If `--python-version` is not set and no `python_version.txt` is provided, default to the interpreter running the script.  
   - **In all cases, the script continues; it does not abort on version mismatch.**

3. **Create/Reuse Virtual Environment:**  
   - Create or reuse the environment in `<venv-root>/<group>/`.  
   - If `--recreate-all` is set, remove the existing folder before creation.

4. **Install Dependencies:**  
   - Read the group’s `requirements.txt` (if present).  
   - If `--missing-requirements` is `suggest` or `append`, the tool scans `.py` files for **third-party** imports (e.g., `import requests`, `import numpy as np`). **Standard library imports are ignored.**  
     - **suggest**: Print any libraries missing from `requirements.txt`.  
     - **append**: Write them (unversioned) to the end of `requirements.txt`.  
   - If `requirements.txt` is not found and `--missing-requirements` is not set, no dependencies will be installed.  
   - Install or upgrade these packages in the virtual environment. The tool does **not** remove any listed packages, even if they’re not imported in the scripts.

5. **Generate Command Wrappers:**
   - For each `.py` file in the group folder, create a script in `--bin`:
     - Script name matches the `.py` filename (e.g., `ping_helper.py` → `ping_helper`).
     - On POSIX systems the wrapper begins with the shebang `#!/usr/bin/env bash`; on Windows a `.cmd` file is produced.
     - Activates the environment, then invokes the `.py` file with all CLI arguments passed along.
   - Make each wrapper executable (`chmod +x`).
   - **Before generating wrappers, the tool performs a pre-check for duplicate wrapper names across all groups. If duplicate names are detected, no wrappers for those names will be generated in any group, and a warning is logged instructing the user to manually rename the conflicting source .py files to ensure unique wrapper names.**

6. **Cleanup Unused Environments (Optional):**
   - *With `--recreate-all`, toolwrap deletes old environment folders before setup. When `--include-groups` is omitted, **all** subdirectories in `--venv-root` are purged. If specific groups are supplied, only those matching folders are removed.*

7. **Logging:**
   - Every action (creation, updates, errors) is appended to `--venv-root/toolwrap_envs.log` with a timestamp, group name, and short description (e.g., "CREATED ENV," "INSTALLED PACKAGES," "WARNING: Missing version fallback").
   - **The file is append-only and may grow over time.** Users may periodically clear or rotate it if desired.

8. **Dry Run Mode (`--dry-run`):**  
   - Enumerates actions (environment creation, installation, wrapper generation) **without** performing them.  
   - Output includes which environments *would* be created, which dependencies *would* be installed, and which are potentially missing.

9. **Summary Output:**  
   - On completion (or dry run), a summary lists:  
     - New or updated environments  
     - Generated wrapper scripts  
     - Added/removed dependencies  
     - **Skipped groups** (e.g., no `.py` found, not in `--include-groups`)  
     - Any problems encountered (e.g., missing Python versions)  

## Running Tests
To run the automated test suite, install `pytest` and execute:

```bash
pytest
```

