import csv, datetime, pathlib, requests

BASE = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
OUT = pathlib.Path("data")
OUT.mkdir(exist_ok=True)

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
        r = requests.get(BASE, params=params, timeout=300)
        r.raise_for_status()
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
    print(y, len(rows), "rows")

this_year = datetime.date.today().year
for y in range(2020, this_year + 1):
    # السنوات القديمة بتتسحب مرة واحدة، والسنة الحالية بتتحدث كل يوم
    if y == this_year or not (OUT / f"{y}.csv").exists():
        fetch_year(y)
