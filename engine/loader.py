"""Load a strategy class from a .py file."""
import importlib.util
from pathlib import Path

from .core import Strategy


def load_strategy(path: str):
    path = str(Path(path).resolve())
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "STRATEGY"):
        return mod.STRATEGY
    for v in vars(mod).values():
        if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy:
            return v
    raise SystemExit(f"no Strategy class found in {path}")
