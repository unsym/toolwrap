# Bootstrap Virtual Environments for Personal Command-Line Python Tools

## 1. Overview and Purpose

The **bootstrap_envs.py** tool is designed to automate the setup and management of isolated Python environments for a collection of personal command-line scripts grouped by functionality. Rather than maintaining all tools and their dependencies in a single global environment, this utility organizes scripts into functional groups, creates separate virtual environments for each group, detects missing dependencies, and generates executable bash wrappers. This approach ensures consistency across multiple machines, minimizes dependency conflicts, and provides ease of use when invoking tools from the command line.

## 2. Rationale

- **Isolation of Dependencies:** Each group of tools requires its own isolated Python environment to avoid conflicts between packages and allow for version management per group.
- **Portability and Repeatability:** With environments automatically created and maintained outside the source repository, the system can be easily cloned and set up on a different computer.
- **Ease of Execution:** Bash wrapper scripts are generated so that each tool can be run as a command from a designated bin folder (e.g., `~/bin/`), without needing to manually activate the virtual environment.
- **Automated Dependency Management (Optional):** The system treats `requirements.txt` as defined by the user. However, it provides options to detect all third-party libraries used in the group’s scripts and suggest (or automatically append) any that are missing. This simplifies the creation of a starter `requirements.txt` for users unfamiliar with dependency management.
- **Unaltered Local Environment:** By keeping virtual environments and generated bash wrappers outside the source tree (and excluding them from version control), the system remains clean and reproducible.
- **Python Version Control:** Each tool group may use a different Python version. A `python_version.txt` file can be provided per group to specify the desired version. If not present, a default Python version (provided via command-line or inferred from the environment) is used.

## 3. Folder Structure

The tool expects to operate on a directory such as `~/mytools/`, which contains groups of Python scripts organized by functionality. Each group may have its own `requirements.txt` and optional `python_version.txt`.

**Example folder structure:**
```
~/mytools/                      # Root of the personal command-line tools repository
├── tools/                      # Source folder containing the grouped tools
│   ├── net_tools/              # Group for network-related tools
│   │   ├── ping_helper.py
│   │   ├── ip_lookup.py
│   │   ├── requirements.txt
│   │   └── python_version.txt  # Optional: specific Python version
│   ├── media_tools/            # Group for media processing tools
│   │   ├── resize_img.py
│   │   └── requirements.txt
│   └── ...                     # Additional groups as necessary
└── .gitignore                  # Configured to exclude generated virtual environments and bin wrappers
```

**Directory for Generated Artifacts:**

- **Bash wrappers:** `~/bin/`  
  Each tool will have a launcher shell script placed in `~/bin/` (e.g., `ping_helper`, `resize_img`). These scripts are generated with a `#!/usr/bin/env bash` shebang and marked as executable (`chmod +x`).

- **Virtual environments:** `~/bin/.venvs/`  
  For each group in `tools/`, a separate virtual environment will be created in a subdirectory, for example:
  ```
  ~/bin/.venvs/net_tools/
  ~/bin/.venvs/media_tools/
  ```

- **Log file:** `~/bin/.venvs/bootstrap_envs.log`  
  All actions, such as environment creation, dependency installs, wrapper generation, and errors, are appended to a persistent log.

## 4. Examples of Tools and Binaries

### Example: Network Tools Group
- **Source Files:**  
  `~/mytools/tools/net_tools/ping_helper.py`, `~/mytools/tools/net_tools/ip_lookup.py`
  
- **Generated Virtual Environment:**  
  `~/bin/.venvs/net_tools/`
  
- **Generated Bash Wrappers in ~/bin/:**
  - `~/bin/ping_helper` – A bash script that activates `~/bin/.venvs/net_tools/` and runs `~/mytools/tools/net_tools/ping_helper.py`
  - `~/bin/ip_lookup` – A similar wrapper for `ip_lookup.py`

### Example: Media Tools Group
- **Source Files:**  
  `~/mytools/tools/media_tools/resize_img.py`  
- **Generated Virtual Environment:**  
  `~/bin/.venvs/media_tools/`
- **Generated Bash Wrapper in ~/bin/:**
  - `~/bin/resize_img` – A wrapper for `resize_img.py`

## 5. Command-Line Arguments for bootstrap_envs.py

The bootstrap utility will accept the following arguments, with the indicated default values:

- **`--source`**  
  **Description:** The root directory containing tool groups (e.g., `~/mytools/tools`).  
  **Default:** Current directory, or a required argument if not in the root repository folder.

- **`--bin`**  
  **Description:** The directory where bash wrapper scripts will be placed (e.g., `~/bin/`).  
  **Default:** `~/bin/`

- **`--venv-root`**  
  **Description:** The root directory where virtual environments will be created for each tool group (e.g., `~/bin/.venvs/`).  
  **Default:** `~/bin/.venvs/`

- **`--python-version`**  
  **Description:** Fallback Python version to use if a group does not define its own in `python_version.txt`.  
  **Default:** The version used to invoke `bootstrap_envs.py`

- **`--missing-requirements`**  
  **Description:** Manage handling of missing third-party imports not listed in `requirements.txt`.  
  **Options:**  
    - Omitted: Only installs from `requirements.txt`  
    - `suggest`: Prints suggested packages to add for each group  
    - `append`: Appends missing packages (no version) to each group’s `requirements.txt`  

- **`--recreate-all`**  
  **Description:** Recreate all virtual environments from scratch and reinstall dependencies.  
  **Default:** Not set.

- **`--dry-run`**  
  **Description:** Show what actions would be performed without making any changes.  
  **Default:** Not set.

## 6. Example Usage

```bash
python3 ~/toolwrap/bootstrap_envs.py --source ~/mytools/tools --bin ~/bin --venv-root ~/bin/.venvs --missing-requirements append --recreate-all
```

This will:
- Process all tool groups in `~/mytools/tools/`
- Append any detected missing packages to `requirements.txt`
- Create (or recreate) virtual environments in `~/bin/.venvs/`
- Generate executable bash wrapper scripts in `~/bin/`

## 7. Operational Workflow

1. **Group Processing:**  
   The tool scans each subfolder under the `--source` directory. For each group:
   - **Python Version Resolution:**  
     - If `python_version.txt` exists, its version is used.
     - Otherwise, the version is determined by `--python-version`, or defaults to the current interpreter.
   
   - **Dependency Detection:**  
     - Parses Python files in the folder for third-party imports.
     - Skips standard library modules.
     - Behavior depends on `--missing-requirements`:
       - If omitted, dependencies are only installed from `requirements.txt`.
       - If `suggest`, any extra packages are listed in the console.
       - If `append`, extra packages are appended (no version pinning) at the end of the file.

   - **Virtual Environment Setup:**  
     A virtual environment is created or reused at `--venv-root/<group>/`. If `--recreate-all` is passed, it is removed and recreated. Packages in `requirements.txt` are installed into the environment.

   - **Wrapper Script Generation:**  
     Each script in the group results in a bash wrapper (named after the script) in `--bin`. Scripts must have **unique names across all groups**, or the user is prompted to rename or rearrange them. The wrapper:
     - Begins with `#!/usr/bin/env bash`
     - Activates the appropriate virtual environment
     - Executes the tool with forwarded arguments
     - Is made executable (`chmod +x`)

2. **Cleanup:**  
   - Removes any virtual environments under `--venv-root/` that no longer correspond to a tool group.

3. **Logging:**  
   - All actions are logged in `--venv-root/bootstrap_envs.log`.

4. **Dry Run:**  
   - If `--dry-run` is specified, all operations are simulated and printed to the console, with no file system or environment changes.

5. **Completion:**  
   A summary is printed showing:
   - New or updated virtual environments
   - Generated wrapper scripts
   - Dependency changes (if any)
   - Any errors or conflicts

## 8. Summary

The **bootstrap_envs.py** utility provides an automated mechanism to structure, set up, and maintain a personal collection of command-line tools. By isolating dependencies in separate virtual environments, supporting per-group Python versions, auto-detecting and managing dependencies, and generating executable wrappers, the system ensures a clean, portable, and reproducible environment for running individual tools from a centralized bin directory.
