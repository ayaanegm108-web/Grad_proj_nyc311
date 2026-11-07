import csv, datetime, gzip, io, os, pathlib, requests, time

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
YEAR = 2026
PAGE = 50000
ROWS_PER_PART = 150000
OUT = pathlib.Path("data/raw")
OUT.mkdir(parents=True, exist_ok=True)
today = datetime.date.today()


def get_page(params):
    headers = {}
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    r = None
    for attempt in range(8):
        r = requests.get(BASE, params=params, headers=headers, timeout=300)
        if r.status_code in (429, 500, 502, 503, 504):
            wait = min(30 * (attempt + 1), 300)
            print(f"HTTP {r.status_code}, retrying in {wait}s", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(1)
        return r
    r.raise_for_status()


def fetch_month(y, m):
    start = datetime.date(y, m, 1)
    end = datetime.date(y + (m == 12), (m % 12) + 1, 1)
    where = f"created_date >= '{start}T00:00:00' AND created_date < '{end}T00:00:00'"
    for old in OUT.glob(f"{y}-{m:02d}-p*.csv.gz"):
        old.unlink()
    offset, part, in_part, total = 0, 0, 0, 0
    f = w = None
    while True:
        r = get_page({
            "$where": where, "$order": "unique_key",
            "$limit": PAGE, "$offset": offset})
        rows = list(csv.reader(io.StringIO(r.text)))
        header, data = rows[0], rows[1:]
        if not data:
            break
        for row in data:
            if f is None or in_part >= ROWS_PER_PART:
                if f:
                    f.close()
                part += 1
                f = gzip.open(OUT / f"{y}-{m:02d}-p{part:02d}.csv.gz",
                              "wt", encoding="utf-8", newline="")
                w = csv.writer(f)
                w.writerow(header)
                in_part = 0
            w.writerow(row)
            in_part += 1
        total += len(data)
        if len(data) < PAGE:
            break
        offset += PAGE
    if f:
        f.close()
    print(f"{y}-{m:02d}: {total} rows, {part} parts", flush=True)


for m in range(1, 13):
    if datetime.date(YEAR, m, 1) > today:
        break
    has_files = any(OUT.glob(f"{YEAR}-{m:02d}-p*.csv.gz"))
    is_recent = YEAR == today.year and m >= today.month - 1
    if is_recent or not has_files:
        fetch_month(YEAR, m)

files = sorted(p.name for p in OUT.glob(f"{YEAR}-*.csv.gz"))
(OUT / "manifest.txt").write_text("\n".join(files), encoding="utf-8")
print("manifest:", len(files), "files")
