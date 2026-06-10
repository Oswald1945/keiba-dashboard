import os, subprocess, sys

repo = r"C:\Users\r-ito\keiba-dashboard"
lock = os.path.join(repo, ".git", "index.lock")

if os.path.exists(lock):
    os.remove(lock)
    print("[1] index.lock deleted")
else:
    print("[1] no lock file")

r = subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, text=True)
print("[2] git add:", r.returncode, r.stderr or "OK")

env = os.environ.copy()
env["GIT_AUTHOR_NAME"] = "kuroame"
env["GIT_AUTHOR_EMAIL"] = "jrock.b.b.express@gmail.com"
env["GIT_COMMITTER_NAME"] = "kuroame"
env["GIT_COMMITTER_EMAIL"] = "jrock.b.b.express@gmail.com"
r = subprocess.run(
    ["git", "commit", "-m",
     "ui: add badge area for 注目馬/本命馬自信あり; rename 自信あり badge with horse name"],
    cwd=repo, capture_output=True, text=True, env=env
)
print("[3] git commit:", r.returncode)
print(r.stdout or r.stderr)

r = subprocess.run(["git", "push"], cwd=repo, capture_output=True, text=True)
print("[4] git push:", r.returncode)
print(r.stdout or r.stderr)
print("\n=== DONE ===")
