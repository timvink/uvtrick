from __future__ import annotations

import inspect
import os
import pickle
import subprocess
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path

PICKLED_INPUTS_PATH = "pickled_inputs.pickle"
PICKLED_OUTPUTS_PATH = "tmp.pickle"

def argskwargs_to_callstring(func, *args, **kwargs) -> str:
    string_kwargs = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
    string_args = ", ".join([f"{a}" for a in args]) + ", " if args else ""
    return f"{func.__name__}({string_args} {string_kwargs})"


def uvtrick_(path: str | Path, func: Callable, *args, **kwargs):
    """This is a *very* hacky way to run functions from Python files from another virtual environment."""
    string_kwargs = ", ".join([f"{k}={v}" for k, v in kwargs.items()])
    string_args = ", ".join([f"{a}" for a in args]) + ", " if args else ""


    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        script = temp_dir / "pytemp.py"
        output = temp_dir / "tmp.pickle"

        code = Path(path).read_text()
        idx = code.find("if __name__")
        code = code[:idx] + "\n\n"

        if func + "(" not in code:
            raise ValueError(f"Function {func} not found in the file {path}")
        if "# /// script" not in code:
            raise ValueError("Script metadata/dependencies not found in the file")

        code += f"""if __name__ == "__main__":
    import pickle
    with open('tmp.pickle', 'wb') as f:
        pickle.dump({func}({string_args} {string_kwargs}), f)\n"""

        script.write_text(code)
        # print(code)
        cmd = ["uv", "run", "--quiet", str(script)]
        subprocess.run(cmd, cwd=temp_dir, check=True)

        return pickle.loads(output.read_bytes())


def load(path: str | Path, func: Callable) -> Callable:
    """
    Load a function from a Python file, this function will be executed in a separate virtual environment using uv.
    
    Note that this approach is more of a demo, it is very hacky and it assumes that the Python script in question 
    uses inline script metadata. More information on this feature can be found here:

    - https://docs.astral.sh/uv/guides/scripts/#declaring-script-dependencies
    - https://packaging.python.org/en/latest/specifications/inline-script-metadata/#inline-script-metadata

    Usage: 

    ```python
    from uvtrick import load

    # Load the function `hello` from the file `some_script.py`
    # It runs in another virtualenv, but you get back the response via pickle. 
    # Be aware of the limitations, please only consider base Python objects.
    hello = load("some_script.py", "hello")
    ```
    """
    def load_func(*args, **kwargs):
        return uvtrick_(path, func, *args, **kwargs)
    return load_func


class Env:
    """Represents a virtual environment with a specific Python version and set of dependencies."""
    def __init__(self, *requirements: str, python: str = None, debug: bool = False):
        self.requirements = requirements
        self.python = python
        self.debug = debug

    @staticmethod
    def maincall(func, inputs_path, outputs_path):
        """A main block to deserialise a function signature then serialise a result.

        Load the args/kwargs from an 'inputs' pickle, call a Python function
        with them, and store the result in an 'output' pickle.
        """
        func_name = func.__name__
        return textwrap.dedent(f"""
        if __name__ == "__main__":
            import pickle
            from pathlib import Path

            args, kwargs = pickle.loads(Path('{inputs_path!s}').read_bytes())
            result = {func_name}(*args, **kwargs)
            Path('{outputs_path!s}').write_bytes(pickle.dumps(result))
        """)

    def run(self, func: Callable, *args, **kwargs):
        """Run a function in the virtual environment using uv."""
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            inputs = temp_dir / "pickled_inputs.pickle"
            script = temp_dir / "pytemp.py"
            output = temp_dir / "tmp.pickle"
            # First pickle the inputs
            inputs.write_bytes(pickle.dumps((args, kwargs)))

            # Now write the contents of the script
            contents = textwrap.dedent(inspect.getsource(func))
            contents += "\n\n"
            contents += self.maincall(func, temp_dir / PICKLED_INPUTS_PATH, temp_dir / PICKLED_OUTPUTS_PATH)
            script.write_text(contents)
            
            quiet = [] if self.debug else ["--quiet"]
            deps = [f"--with={dep}" for dep in self.requirements]
            pyversion = [f"--python={self.python}"] if self.python else []
            cmd = ["uv", "run", *quiet, *deps, *pyversion, str(script)]

            if self.debug:
                print(f"Running files in {temp_dir}\n{cmd}")
                with open(temp_dir / PICKLED_INPUTS_PATH, 'rb') as file:
                    args, kwargs = pickle.load(file)
                print(f"Pickled args: {args}")
                print(f"Pickled kwargs: {kwargs}")
                print(f"Contents of the script:\n\n {contents}")

            subprocess.run(cmd, cwd=temp_dir, check=True)

            return pickle.loads(output.read_bytes())
