import csv, datetime, os, pathlib, requests, sys, time

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))
OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)
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


def fetch_range(start, end):
    where = f"created_date >= '{start}T00:00:00' AND created_date < '{end}T00:00:00'"
    rows, offset, limit, header = [], 0, 50000, None
    while True:
        r = get_page({
            "$select": "date_trunc_ymd(created_date) AS day, borough, complaint_type, "
                       "count(*) AS requests, count(closed_date) AS closed",
            "$where": where,
            "$group": "day, borough, complaint_type",
            "$order": "day, borough, complaint_type",
            "$limit": limit,
            "$offset": offset,
        })
        batch = list(csv.reader(r.text.splitlines()))
        header, data = batch[0], batch[1:]
        rows += data
        if len(data) < limit:
            break
        offset += limit
    return header, rows


def write_year(y, header, rows):
    rows = [r for r in rows if r]
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with open(OUT / f"{y}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(y, len(rows), "rows", flush=True)


def full_year(y):
    header, all_rows = None, []
    for m in range(1, 13):
        s = datetime.date(y, m, 1)
        if s > today:
            break
        e = datetime.date(y + (m == 12), (m % 12) + 1, 1)
        h, rows = fetch_range(s, e)
        header = header or h
        all_rows += rows
    write_year(y, header, all_rows)


def update_year(y):
    start = max(cutoff, datetime.date(y, 1, 1))
    with open(OUT / f"{y}.csv", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        keep = [r for r in reader if r and r[0] < f"{start}T00:00:00"]
    _, new = fetch_range(start, datetime.date(y + 1, 1, 1))
    write_year(y, header, keep + new)


failed = []
for y in range(2020, today.year + 1):
    try:
        if not (OUT / f"{y}.csv").exists():
            full_year(y)
        elif y >= cutoff.year:
            update_year(y)
    except Exception as e:
        print(f"FAILED {y}: {e}", flush=True)
        failed.append(y)

print("failed years:", failed)
sys.exit(1 if failed else 0)
