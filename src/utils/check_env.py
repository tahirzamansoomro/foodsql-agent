"""
FoodSQL-Agent  |  Environment health check

Prints which packages are installed, whether the GPU works with PyTorch and
bitsandbytes (needed for 4-bit / QLoRA), how much disk space is free, and
whether the project files from earlier steps exist.

Run from the repository root:
    python src/utils/check_env.py
"""

import importlib
from importlib import metadata
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path.cwd()

# (import name, pip name)
PACKAGES = [
    ("duckdb", "duckdb"), ("pandas", "pandas"), ("numpy", "numpy"),
    ("yaml", "pyyaml"), ("dotenv", "python-dotenv"), ("tqdm", "tqdm"),
    ("openai", "openai"), ("flask", "flask"), ("flask_cors", "flask-cors"),
    ("torch", "torch"), ("transformers", "transformers"), ("accelerate", "accelerate"),
    ("peft", "peft"), ("trl", "trl"), ("bitsandbytes", "bitsandbytes"),
    ("datasets", "datasets"), ("huggingface_hub", "huggingface_hub"), ("wandb", "wandb"),
]


def section(title):
    print(f"\n=== {title} ===")


def free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1024 ** 3
    except Exception:
        return None


def main():
    problems = []

    section("System")
    print("Python   :", sys.version.split()[0], "|", platform.platform())
    print("Folder   :", ROOT)

    section("Packages")
    missing = []
    for module, pip_name in PACKAGES:
        try:
            importlib.import_module(module)
            try:
                ver = metadata.version(pip_name)
            except Exception:
                ver = ""
            print(f"  OK       {pip_name:<18} {ver}")
        except Exception:
            print(f"  MISSING  {pip_name}")
            missing.append(pip_name)
    if missing:
        problems.append("missing packages: " + " ".join(missing))

    section("GPU")
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            print("  GPU      :", torch.cuda.get_device_name(0))
            print(f"  VRAM     : {total / 1024 ** 3:.1f} GB total, {free / 1024 ** 3:.1f} GB free")
            print("  CUDA     :", torch.version.cuda, "| torch", torch.__version__)
        else:
            print("  CUDA NOT AVAILABLE to PyTorch")
            problems.append("PyTorch cannot see the GPU")
    except Exception as exc:
        print("  PyTorch not usable:", str(exc)[:120])
        problems.append("PyTorch not usable")

    try:
        import bitsandbytes as bnb
        import torch

        layer = bnb.nn.Linear4bit(64, 64, compute_dtype=torch.float16).cuda()
        layer(torch.randn(2, 64, dtype=torch.float16, device="cuda"))
        print("  4-bit (bitsandbytes) test : OK")
    except Exception as exc:
        print("  4-bit (bitsandbytes) test : FAILED -", str(exc)[:150])
        problems.append("bitsandbytes 4-bit test failed")

    section("Disk space (free)")
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    print(f"  Model cache folder : {hf_home}")
    print(f"  Free where models are stored : {free_gb(Path.home()):.0f} GB (7B model needs about 16 GB)")
    if Path("/mnt/d").exists():
        print(f"  Free on D: drive             : {free_gb('/mnt/d'):.0f} GB")

    section("Project files")
    checks = {
        "Gold database": ROOT / "db" / "food_delivery.duckdb",
        "train.jsonl": ROOT / "datasets" / "text2sql" / "train.jsonl",
        "test.jsonl": ROOT / "datasets" / "text2sql" / "test.jsonl",
        ".env file": ROOT / ".env",
    }
    for name, path in checks.items():
        print(f"  {'OK     ' if path.exists() else 'MISSING'}  {name}")

    try:
        import duckdb

        db = ROOT / "db" / "food_delivery.duckdb"
        if db.exists():
            con = duckdb.connect(str(db).replace("\\", "/"), read_only=True)
            counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchall()[0][0]
                      for t in ("restaurants", "riders", "customers", "orders", "deliveries")}
            print("  Table rows:", counts)
            con.close()
    except Exception as exc:
        print("  Could not read database:", str(exc)[:120])

    for name in ("train.jsonl", "test.jsonl"):
        path = checks[name]
        if path.exists():
            with open(path, encoding="utf-8") as f:
                print(f"  {name}: {sum(1 for _ in f)} records")

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    print("  OPENAI_API_KEY set:", "yes" if os.environ.get("OPENAI_API_KEY") else "no")

    section("Summary")
    if problems:
        for p in problems:
            print("  PROBLEM:", p)
    else:
        print("  Everything needed for the next steps is in place.")


if __name__ == "__main__":
    main()