import csv, datetime, gzip, io, os, pathlib, requests, shutil, sys, time

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
YEAR = 2026
PAGE = 25000
ROWS_PER_PART = 150000
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))
OUT = pathlib.Path("data/raw")
OUT.mkdir(parents=True, exist_ok=True)
TMP = pathlib.Path("tmp_raw")
today = datetime.date.today()
cutoff = today - datetime.timedelta(days=LOOKBACK_DAYS)


def get_page(params):
    headers = {}
    token = os.environ.get("SOCRATA_APP_TOKEN")
    if token:
        headers["X-App-Token"] = token
    for attempt in range(8):
        wait = min(30 * (attempt + 1), 300)
        try:
            r = requests.get(BASE, params=params, headers=headers, timeout=(30, 180))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"{type(e).__name__}, retrying in {wait}s", flush=True)
            time.sleep(wait)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"HTTP {r.status_code}, retrying in {wait}s", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        time.sleep(1)
        return r
    raise RuntimeError("too many failed attempts")


class PartWriter:
    def __init__(self, y, m):
        self.y, self.m = y, m
        self.header = None
        self.part = self.in_part = self.total = 0
        self.f = self.w = None

    def write(self, row):
        if self.f is None or self.in_part >= ROWS_PER_PART:
            self.close_file()
            self.part += 1
            self.f = gzip.open(TMP / f"{self.y}-{self.m:02d}-p{self.part:02d}.csv.gz",
                               "wt", encoding="utf-8", newline="")
            self.w = csv.writer(self.f)
            self.w.writerow(self.header)
            self.in_part = 0
        self.w.writerow(row)
        self.in_part += 1
        self.total += 1

    def close_file(self):
        if self.f:
            self.f.close()
            self.f = None


def fetch_month(y, m):
    start = datetime.date(y, m, 1)
    end = datetime.date(y + (m == 12), (m % 12) + 1, 1)
    existing = sorted(OUT.glob(f"{y}-{m:02d}-p*.csv.gz"))
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir()
    pw = PartWriter(y, m)
    fetch_start = start
    try:
        if existing:
            fetch_start = max(cutoff, start)
            keep_before = f"{fetch_start}T00:00:00"
            for p in existing:
                with gzip.open(p, "rt", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    hdr = next(reader)
                    if pw.header is None:
                        pw.header = hdr
                    ci = hdr.index("created_date")
                    for row in reader:
                        if row and row[ci] < keep_before:
                            pw.write(row)
        where = f"created_date >= '{fetch_start}T00:00:00' AND created_date < '{end}T00:00:00'"
        offset = 0
        while True:
            r = get_page({"$where": where, "$order": "unique_key",
                          "$limit": PAGE, "$offset": offset})
            rows = list(csv.reader(io.StringIO(r.text)))
            if not rows:
                break
            hdr, data = rows[0], rows[1:]
            if not data:
                break
            if pw.header is None:
                pw.header = hdr
            if hdr != pw.header:
                idx = {c: i for i, c in enumerate(hdr)}
                data = [[row[idx[c]] if c in idx and idx[c] < len(row) else ""
                         for c in pw.header] for row in data]
            for row in data:
                pw.write(row)
            if len(data) < PAGE:
                break
            offset += PAGE
    finally:
        pw.close_file()
    if pw.total == 0:
        print(f"{y}-{m:02d}: nothing to write, kept old files", flush=True)
        return
    for old in existing:
        old.unlink()
    for new in TMP.glob("*.csv.gz"):
        shutil.move(str(new), str(OUT / new.name))
    print(f"{y}-{m:02d}: {pw.total} rows total, {pw.part} parts (fetched from {fetch_start})", flush=True)


def write_manifest():
    files = sorted(p.name for p in OUT.glob(f"{YEAR}-*.csv.gz"))
    (OUT / "manifest.txt").write_text("\n".join(files), encoding="utf-8")


failed = []
for m in range(1, 13):
    if datetime.date(YEAR, m, 1) > today:
        break
    end = datetime.date(YEAR + (m == 12), (m % 12) + 1, 1)
    has_files = any(OUT.glob(f"{YEAR}-{m:02d}-p*.csv.gz"))
    if not has_files or end > cutoff:
        try:
            fetch_month(YEAR, m)
        except Exception as e:
            print(f"FAILED {YEAR}-{m:02d}: {e}", flush=True)
            failed.append(m)
        write_manifest()

shutil.rmtree(TMP, ignore_errors=True)
write_manifest()
print("failed months:", failed)
sys.exit(1 if failed else 0)
