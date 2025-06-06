# Toolwrap: Automatic Python script environment setup and CLI wrappers

**Toolwrap** automatically creates isolated Python environments for your script collections and generates wrapper commands so you can run each script directly from the command line.

## Why Use Toolwrap?

- Run your scripts as simple commands without manually activating environments
- Group and manage many scripts easily - just put your scripts in subfolders, no packaging required
- Keep each tool group's dependencies and environments separate
- Auto-detect basic dependencies for each group and install them
- No extra packages needed to run Toolwrap

## Minimal Folder Layout

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

## Basic Usage

```bash
python toolwrap.py --source ./example_tools --bin ./bin
```
Toolwrap detects that the math tools depend on **NumPy** and installs it
automatically. Packages listed in each group's `requirements.txt` are also
installed. For details on the example scripts, see
[example_tools/README.md](example_tools/README.md).

By default each subfolder of `--source` becomes a tool group. A virtual environment is created for each group and all Python scripts get wrapper commands in `--bin`.

## Customization

- Edit `requirements.txt` or `python_version.txt` in a group folder if you need manual control.
- See [documentation](DOCUMENTATION.md) for command reference, advanced usage examples, and full rationale.
