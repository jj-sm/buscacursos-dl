import json
from ..scraper.search_catalogo import catalogo_search
from ..scraper.programs import get_program
from ..scraper.requirements import get_requirements
from .schedule import process_schedule
from .errors import handle
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Set, Dict, List, Union

log = logging.getLogger("scraper")


CATALOGO_LIMIT = 1000


class CollectCatalogo:
    processed: Set[str]
    courses: Dict[str, dict]

    def __init__(self):
        self.processed = set()
        self.courses = {}
        self.lock = threading.Lock()

    def _process_single_course(self, cfg: dict, c: dict):
        with self.lock:
            if c['initials'] in self.processed:
                return
            self.processed.add(c['initials'])

        try:
            # Fetch auxiliary data
            program = ""
            if cfg.get("fetch-program"):
                program = get_program(cfg, c["initials"])
            req, con, restr, equiv = "", "", "", ""
            if cfg.get("fetch-requirements"):
                req, con, restr, equiv = get_requirements(cfg, c["initials"])

            # Save course
            with self.lock:
                self.courses[c['initials']] = {
                    'name': c['name'],
                    'credits': c['credits'],
                    'req': req,
                    'conn': con,
                    'restr': restr,
                    'equiv': equiv,
                    'program': program,
                    'school': c['school'],
                    'relevance': c['relevance'],
                }

                print(f"course[{c['initials']}]: {json.dumps(self.courses[c['initials']])}")
        except Exception as err:
            handle(c, err)

        # Commit to DB
        log.info(
            "Processed: %s %s",
            c["initials"],
            c["name"],
        )

    def process_courses(self, cfg: dict, courses: List[dict], executor: ThreadPoolExecutor):
        futures = [executor.submit(self._process_single_course, cfg, c) for c in courses]
        for future in as_completed(futures):
            future.result()

    def collect(self, cfg: dict):
        testmode: bool = cfg.get('testmode', False)
        max_workers: int = cfg.get("max-workers", 12)

        LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        NUMBERS = "0123456789"
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for l1 in LETTERS:
                comb = l1
                log.info("Searching %s", comb)
                courses = catalogo_search(cfg, comb)
                if testmode and len(courses) > 10:
                    courses = courses[:10]
                    pass
                self.process_courses(cfg, courses, executor)
                if testmode:
                    break
                if len(courses) < CATALOGO_LIMIT:
                    continue

                for l2 in LETTERS:
                    comb = l1 + l2
                    log.info("Searching %s", comb)
                    courses = catalogo_search(cfg, comb)
                    self.process_courses(cfg, courses, executor)
                    if len(courses) < CATALOGO_LIMIT:
                        continue

                    for l3 in LETTERS:
                        comb = l1 + l2 + l3
                        log.info("Searching %s", comb)
                        courses = catalogo_search(cfg, comb)
                        self.process_courses(cfg, courses, executor)
                        if len(courses) < CATALOGO_LIMIT:
                            continue

                        for n1 in NUMBERS:
                            comb = l1 + l2 + l3 + n1
                            log.info("Searching %s", comb)
                            courses = catalogo_search(cfg, comb)
                            self.process_courses(cfg, courses, executor)
                            if len(courses) < CATALOGO_LIMIT:
                                continue

                            for n2 in NUMBERS:
                                comb = l1 + l2 + l3 + n1 + n2
                                log.info("Searching %s", comb)
                                courses = catalogo_search(cfg, comb)
                                self.process_courses(cfg, courses, executor)

        log.info("Found %s courses", len(self.courses))
