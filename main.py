#!/usr/bin/env python3
# Quick and dirty buscacursos/catalogo scraper based on the scraper for ramos-uc

import os
import traceback
from bc_scraper.actions.collect import CollectCourses
from bc_scraper.actions.collect_catalogo import CollectCatalogo
from bc_scraper.scraper.request import load_cache
from bc_scraper.storage.semester_store import SemesterSQLiteStore
import json
import logging
import sys



logging.basicConfig(level=logging.WARNING)
log = logging.getLogger()

cookies = ""
if os.path.exists(".cred"):
    try:
        with open(".cred", 'r') as file:
            cookies = file.read()
        log.info(f"using cookies = '{cookies}'")
    except Exception:
        log.error("reading .cred for cookies failed:")
        log.error(traceback.format_exc())


args = sys.argv.copy()
args.pop(0)
opts = set()
vals = {}
for i in reversed(range(len(args))):
    if args[i].startswith("--"):
        opt = args[i][2:]
        if "=" in opt:
            key, val = opt.split("=", 1)
            opts.add(key)
            vals[key] = val
        else:
            opts.add(opt)
        args.pop(i)

if len(args) == 0:
    print(
        "usage: python3 main.py [options] [periods...]")
    print("  options:")
    print("    --skip-program       Do not fetch course program text.")
    print("    --skip-requirements  Do not fetch course requirements information.")
    print("    --skip-quota         Do not fetch course quota information.")
    print("    --disable-cache      Do not load or store cache from SQLite request cache.")
    print("    --workers=N          Number of concurrent workers for course enrichment (default: 12).")
    print("    --output-db=PATH     SQLite file for semester tables (default: scraper_data.sqlite).")
    print("    --stdout-json        Also emit legacy JSON output to stdout.")
    print("    --test               Search for up to 10 courses and then stop.")
    print("  example: python3 main.py 2022-2 2022-1 > stdout.txt 2> stderr.txt")
    print("  if period is 'catalogo' then catalogo UC is scraped")
    sys.exit()
periods = args

settings = {
    "batch_size": 100,
    "cookies": cookies,
    "max-workers": int(vals.get("workers", "12")),
    "output-db": vals.get("output-db", "scraper_data.sqlite"),
    "testmode": "test" in opts,
    "fetch-program": "skip-program" not in opts,
    "fetch-quota": "skip-quota" not in opts,
    "fetch-requirements": "skip-requirements" not in opts,
    "disable-cache": "disable-cache" in opts,
}

if not settings.get("disable-cache"):
    load_cache()

if len(args) == 1 and args[0] == "catalogo":
    # Scrape catalogo UC
    log.info("scraping catalogo UC")
    courses = CollectCatalogo()
    courses.collect(settings)
    data = dict(sorted(courses.courses.items()))
    if "stdout-json" in opts:
        json.dump(data, sys.stdout)
else:
    # Scrape buscacursos
    log.info(f"scraping {len(periods)} buscacurso periods")
    store = SemesterSQLiteStore(settings["output-db"])

    data = {} if "stdout-json" in opts else None
    for period in periods:
        log.info(f"scraping buscacurso period {period}")
        store.ensure_period_table(period)
        print(f"period[{period}]")
        courses = CollectCourses(store=store)
        courses.collect(period, settings)
        if data is not None:
            for course in courses.courses.values():
                course['sections'] = dict(
                    sorted(course["sections"].items(), key=lambda x: int(x[0])))
            data[period] = dict(sorted(courses.courses.items()))

    if data is not None:
        data = dict(sorted(data.items(), reverse=True))
        json.dump(data, sys.stdout)
    else:
        print(f"sqlite output saved to {settings['output-db']}")
