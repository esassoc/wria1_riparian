"""Run every tests/test_*.py script in order. Exits 1 if any fails.
Run: python tests/run_all.py"""
import glob, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def main():
    scripts = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    failed = []
    for s in scripts:
        name = os.path.basename(s)
        print(f"\n=== {name} ===")
        r = subprocess.run([sys.executable, s], cwd=ROOT)
        if r.returncode != 0:
            failed.append(name)
    print("\n" + ("ALL PASSED" if not failed else f"FAILED: {failed}"))
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
