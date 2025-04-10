# Bootstrap Virtual Environments for Personal Command-Line Python Tools

## 1. Overview and Purpose

The **bootstrap_envs.py** tool automates the setup and management of isolated Python environments for a collection of command-line scripts grouped by functionality. Each group resides in a separate subfolder, containing Python scripts along with optional dependency and Python version requirements. This utility:

1. Identifies all subfolders (or specified subsets) under a root directory.  
2. For each subfolder (group), sets up or updates a dedicated virtual environment for all Python scripts.  
3. Installs dependencies listed in a `requirements.txt` file (with optional auto-detection of missing third-party libraries).  
4. Creates or updates bash wrapper scripts in a user-specified bin directory, enabling each Python script to be invoked by name from the command line with its virtual environment automatically activated.

This design avoids version conflicts between scripts, simplifies re-creating setups on new machines, and keeps a user’s global environment clean.  

---

## 2. Rationale

1. **Dependency Isolation:**  
   Each group’s Python virtual environment is kept separate, preventing package conflicts when scripts rely on different or incompatible libraries.

2. **Portability and Reproducibility:**  
   Because the tool manages creation and maintenance of virtual environments and wrappers, the structure can be cloned, re-bootstrapped, and run on any machine without manual environment activation.

3. **Wrapper Convenience:**  
   Bash wrapper scripts are generated so that each tool can be run as a command from a designated bin folder (e.g., `~/bin/`), without needing to manually activate the correct environment.

4. **Optional Dependency Detection:**  
   The tool can scan user scripts for import packages referencing third-party libraries, ensuring that `requirements.txt` has the required libraries (either suggesting or automatically appending missing libraries).

5. **Python Version Control:**  
   By supporting per-group Python versions via a simple `python_version.txt` file, each group’s environment can match the version intended by the script author.

---

## 3. Folder Structure

The tool expects a root directory (specified via `--source`) containing one or more subfolders. Each subfolder (“group”) should house related command-line scripts. For each group, you typically have:

- **One or more `.py` Python scripts** implementing individual command-line tools.  
- An **optional `requirements.txt`** listing libraries to install in the group’s virtual environment. This is required for non-standard libraries and can be automatically created using `--missing-requirements`.  
- An **optional `python_version.txt`** specifying the Python version for that group (overriding the fallback version).

For example, if `--source` is set to `~/mytools`, your structure might look like this:

```
~/mytools/
├── net_tools/
│   ├── ping_helper.py
│   ├── ip_lookup.py
│   ├── requirements.txt
│   └── python_version.txt
├── media_tools/
│   ├── resize_img.py
│   └── requirements.txt
└── ...
```

Where:
- `net_tools/` and `media_tools/` are group folders.
- Each `.py` file becomes a standalone command once the script has generated its corresponding bash wrapper.
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
  - If not found, the tool will fall back to `--python-version` (if set), or the interpreter used to invoke `bootstrap_envs.py`.  
  - *A warning is logged if the specified version can’t be found.*

---

## 4. Command-Line Arguments

The script can be run as:

```bash
python3 bootstrap_envs.py [OPTIONS]
```

Available arguments:

- **`--source`**  
  **Description:** Root directory containing tool groups. Each subfolder is treated as a group.  
  **Default:** Current directory (`.`)

- **`--bin`**  
  **Description:** Directory where the generated bash wrapper scripts will be placed. Each script becomes an executable command here.  
  **Default:** `~/bin/`

- **`--venv-root`**  
  **Description:** Directory under which virtual environments are created, one per group.  
  **Default:** `~/bin/.venvs/`

- **`--python-version`**  
  **Description:** Fallback Python version to use if a group does not specify one via `python_version.txt`.  
  **Default:** Version of the Python interpreter used to run `bootstrap_envs.py`

- **`--missing-requirements`**  
  **Description:** Controls how the tool handles third-party packages that are imported in scripts but missing from `requirements.txt`.  
  **Options:**  
  - *(Omitted)* – Only installs what is already listed in `requirements.txt`  
  - `suggest` – Prints any missing packages that should be added  
  - `append` – Automatically appends missing package names (without versions) to `requirements.txt`

- **`--recreate-all`**  
  **Description:** If specified, removes and recreates all virtual environments before reinstalling packages.  
  **Default:** Not set (reuses existing environments)

- **`--dry-run`**  
  **Description:** Simulates all actions (environment creation, dependency installation, wrapper generation) without performing them.  
  **Default:** Not set

- **`--include-groups`**  
  **Description:** Comma-separated list of specific group folder names to process (e.g., `net_tools,media_tools`).  
  If omitted, all subfolders in `--source` are processed.  
  **Default:** Not set (processes all groups)  
  *If a specified group does not exist, the tool logs a warning and skips it.*

---

## 5. Usage Example

```bash
python3 bootstrap_envs.py \
  --source ~/mytools \
  --bin ~/bin \
  --venv-root ~/bin/.venvs \
  --missing-requirements append \
  --recreate-all \
  --include-groups net_tools,media_tools
```

The tool will:

1. Look under `~/mytools` only at `net_tools` and `media_tools` (ignoring any other subfolders).  
2. Remove any existing environments for these two groups, recreate them under `~/bin/.venvs/`, then install dependencies from each group’s `requirements.txt`.  
3. Append any newly detected libraries to `requirements.txt` files.  
4. Generate or overwrite bash wrappers in `~/bin/`.  
5. Update `~/bin/.venvs/bootstrap_envs.log` with the details.

---

## 6. Operational Workflow

1. **Determine Groups to Process:**  
   - If `--include-groups` is provided (e.g., `net_tools,media_tools`), only those subfolders are processed.  
   - Otherwise, process all subfolders in the `--source` directory.  
   - *If a listed group doesn’t exist, a warning is logged.*

2. **Resolve Python Version:**  
   - If a group subfolder has `python_version.txt`, parse that file’s contents as the Python version.  
   - If the system doesn’t have that version installed, log a warning and fall back to `--python-version` (if set), or to the interpreter running `bootstrap_envs.py`.  
   - If `--python-version` is not set and no `python_version.txt` is provided, default to the interpreter running the script.

3. **Create/Reuse Virtual Environment:**  
   - Create or reuse the environment in `<venv-root>/<group>/`.  
   - If `--recreate-all` is set, remove the existing folder before creation.

4. **Install Dependencies:**  
   - Read the group’s `requirements.txt` (if present).  
   - If `--missing-requirements` is `suggest` or `append`, detect third-party imports in `.py` files.  
     - **suggest**: Print any libraries missing from `requirements.txt`.  
     - **append**: Write them (unversioned) to the end of `requirements.txt`.  
   - If `requirements.txt` is not found and `--missing-requirements` is not set, no dependencies will be installed.  
   - Install or upgrade these packages in the virtual environment. *The tool does not remove any packages even if they aren’t imported by the script.*

5. **Generate Bash Wrappers:**  
   - For each `.py` file in the group folder, create a shell script in `--bin`:
     - Script name matches the `.py` filename (e.g., `ping_helper.py` → `ping_helper`).  
     - Shebang: `#!/usr/bin/env bash`  
     - Activates the environment, then invokes the `.py` file with all CLI arguments passed along.  
   - Make each wrapper executable (`chmod +x`).  
   - *If multiple scripts across groups share the same filename, the user must rename them to avoid collisions.*

6. **Cleanup Unused Environments:**  
   - (Optional) Remove any virtual environments under `--venv-root` that correspond to groups no longer present in `--source`. This step helps keep the environment directory tidy, but the user may choose not to run it automatically.  
   - *If `--recreate-all` is given, existing environments for the included groups are removed before being recreated.*

7. **Logging:**  
   - Every action (creation, updates, errors) is appended to `--venv-root/bootstrap_envs.log`, with a timestamp, group name, and a short description of the action (e.g., “CREATED ENV,” “INSTALLED PACKAGES,” “WARNING: Missing version fallback”).  
   - *This ensures consistent, trackable logs for troubleshooting.*

8. **Dry Run Mode (`--dry-run`):**  
   - Enumerates actions (environment creation, installation, wrapper generation) without performing them.  
   - Output includes which environments *would* be created, which dependencies *would* be installed, which potential missing dependencies, etc.

9. **Summary Output:**  
   - On completion (or dry run), a summary lists new or updated environments, wrapper scripts, added/removed dependencies, and any problems encountered (e.g., missing Python versions).  
   - This helps confirm the final state of the tool.
