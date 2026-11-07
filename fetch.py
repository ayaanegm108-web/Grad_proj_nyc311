import csv, datetime, os, pathlib, requests, time

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)


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


def fetch_year(y):
    where = f"created_date >= '{y}-01-01T00:00:00' AND created_date < '{y+1}-01-01T00:00:00'"
    rows, offset, limit, header = [], 0, 50000, None
    while True:
        params = {
            "$select": "date_trunc_ymd(created_date) AS day, borough, complaint_type, "
                       "count(*) AS requests, count(closed_date) AS closed",
            "$where": where,
            "$group": "day, borough, complaint_type",
            "$order": "day, borough, complaint_type",
            "$limit": limit,
            "$offset": offset,
        }
        r = get_page(params)
        batch = list(csv.reader(r.text.splitlines()))
        header, data = batch[0], batch[1:]
        rows += data
        if len(data) < limit:
            break
        offset += limit
    with open(OUT / f"{y}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(y, len(rows), "rows", flush=True)


this_year = datetime.date.today().year
for y in range(2020, this_year + 1):
    if y == this_year or not (OUT / f"{y}.csv").exists():
        fetch_year(y)
