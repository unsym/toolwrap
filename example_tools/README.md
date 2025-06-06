# Example tools for Toolwrap

This folder provides a small set of sample scripts used for demonstrating
[toolwrap](../toolwrap.py). There are three example tool groups:

- `demo_tools` – contains a single `hello.py` script that simply prints a
  greeting.
- `math_tools` – demonstrates tools that depend on **NumPy**. Toolwrap
  detects this requirement automatically. It includes `sum_array.py` and
  `sum_matrix.py`.
- `media_tools` – showcases basic image processing. `requirements.txt`
  lists **Pillow**, which Toolwrap installs for this group. It provides a
  `resize_img.py` script for resizing an image file.

To test Toolwrap using these samples, run from the repository root:

```bash
python toolwrap.py --source example_tools --bin example_tools/bin
```

After setup, you can invoke the wrapper scripts:

```bash
example_tools/bin/hello
example_tools/bin/sum_array
example_tools/bin/sum_matrix
example_tools/bin/resize_img --help
```

Running `hello` should print `Hello from demo_tools!` while `sum_array` and
`sum_matrix` operate on NumPy arrays. The `media_tools` directory includes a
`python_version.txt` file specifying the Python version used for that group.
