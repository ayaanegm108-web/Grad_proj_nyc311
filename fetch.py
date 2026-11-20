import csv, datetime, os, pathlib, requests, sys, time

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)
today = datetime.date.today()


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


def fetch_month(y, m):
    start = datetime.date(y, m, 1)
    end = datetime.date(y + (m == 12), (m % 12) + 1, 1)
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


def fetch_year(y):
    all_rows, header = [], None
    for m in range(1, 13):
        if datetime.date(y, m, 1) > today:
            break
        h, rows = fetch_month(y, m)
        header = header or h
        all_rows += rows
    with open(OUT / f"{y}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(all_rows)
    print(y, len(all_rows), "rows", flush=True)


failed = []
for y in range(2020, today.year + 1):
    if y == today.year or not (OUT / f"{y}.csv").exists():
        try:
            fetch_year(y)
        except Exception as e:
            print(f"FAILED {y}: {e}", flush=True)
            failed.append(y)

print("failed years:", failed)
sys.exit(1 if failed else 0)
