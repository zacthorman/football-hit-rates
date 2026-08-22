"""Report which fixtures span disconnected rating pools."""
import json, re, sys, glob
import hitrates

paths = sys.argv[1:] or sorted(glob.glob("reports/*.html"))
bad = 0
for path in paths:
    s = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r'const ALL = (\{.*?\});\n', s, re.S)
    if not m:
        continue
    try:
        data = json.loads(m.group(1))
    except Exception:
        continue
    for i, fx in enumerate(data.get("fixtures", [])):
        try:
            names = [t["name"] for t in fx["teams"]]
            ids = [t["id"] for t in fx["teams"]]
            recs = {ids[0]: fx["records"][0], ids[1]: fx["records"][1]}
        except Exception:
            continue
        pools = hitrates.rating_pools(recs)
        if hitrates.pool_of(pools, ids[0]) != hitrates.pool_of(pools, ids[1]):
            bad += 1
            comps = {n: sorted({r["competition"] for r in rs})
                     for n, rs in zip(names, fx["records"])}
            print(f"DISCONNECTED  {path}  [{i}] {names[0]} v {names[1]}")
            for n, c in comps.items():
                print(f"      {n}: {c}")
print()
print(f"{bad} disconnected fixture(s) found")
