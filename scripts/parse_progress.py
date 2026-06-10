"""Live progress bar for a running parse — polls DuckDB (read-only), one line per check.
Usage:  .venv/bin/python scripts/parse_progress.py [--match denmark_open_2022_sf]"""
import argparse, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from badminton import db

ap = argparse.ArgumentParser()
ap.add_argument("--match", default="denmark_open_2022_sf")
ap.add_argument("--start", type=int, default=11578)
ap.add_argument("--end", type=int, default=82990)
args = ap.parse_args()

t0, f0 = None, None
while True:
    try:
        con = db.connect(read_only=True)
        n, fmax = con.execute("SELECT COUNT(*), MAX(frame_num) FROM tracks WHERE match_id=?",
                              [args.match]).fetchone()
        con.close()
    except Exception:
        time.sleep(5)          # writer briefly holds the lock at chunk commits
        continue
    fmax = fmax or args.start
    pct = (fmax - args.start) / (args.end - args.start)
    if t0 is None and fmax > args.start:
        t0, f0 = time.time(), fmax
    eta = ""
    if t0 and fmax > f0:
        rate = (fmax - f0) / (time.time() - t0)        # frames/sec since watching
        eta = f" · ETA {(args.end - fmax) / rate / 60:.0f} min"
    bar = "█" * int(pct * 40) + "░" * (40 - int(pct * 40))
    print(f"\r[{bar}] {pct*100:5.1f}% · frame {fmax:,}/{args.end:,} · {n:,} rows{eta}  ",
          end="", flush=True)
    if fmax >= args.end - 130:
        print("\ndone")
        break
    time.sleep(30)
