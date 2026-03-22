from ..scraper.search import bc_search
from ..scraper.programs import get_program
from ..scraper.requirements import get_requirements
from ..scraper.banner import banner_quota
from .schedule import process_schedule
from .errors import handle
import logging
import copy
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Union
import json

log = logging.getLogger("scraper")


class CollectCourses:
    processed_initials: Dict[str, bool]
    processed_nrcs: Dict[str, bool]
    new_sections: int
    new_courses: int

    # Map code to course
    courses: Dict[str, dict]

    def __init__(self, store=None):
        # Global procesed courses and sections
        self.procesed_initials = {}
        self.procesed_nrcs = {}
        self.new_sections = 0
        self.new_courses = 0
        self.courses = {}
        self.store = store
        self.lock = threading.Lock()
        self.initial_locks = {}

    def _get_initial_lock(self, initials: str):
        with self.lock:
            if initials not in self.initial_locks:
                self.initial_locks[initials] = threading.Lock()
            return self.initial_locks[initials]

    def _upsert_store_section(self, period: str, initials: str, section_number: int):
        if self.store is None:
            return
        with self.lock:
            course_snapshot = copy.deepcopy(self.courses[initials])
            section_snapshot = copy.deepcopy(
                self.courses[initials]["sections"][str(section_number)]
            )
        self.store.upsert_course_section(
            period,
            initials,
            course_snapshot,
            section_number,
            section_snapshot,
        )

    def _process_single_course(self, cfg, c: Dict[str, Union[str, bool, int]], period: str):
        if c["nrc"] in self.procesed_nrcs:
            return

        initial_lock = self._get_initial_lock(c["initials"])

        # Mark section as processed as early as possible to avoid duplicate work.
        with self.lock:
            if c["nrc"] in self.procesed_nrcs:
                return
            self.procesed_nrcs[c["nrc"]] = True

        try:
            with initial_lock:
                needs_course = False
                with self.lock:
                    if c["initials"] not in self.procesed_initials:
                        needs_course = True

                if needs_course:
                    program = ""
                    if cfg.get("fetch-program"):
                        program = get_program(cfg, c["initials"])
                    req, con, restr, equiv = "", "", "", ""
                    if cfg.get("fetch-requirements"):
                        req, con, restr, equiv = get_requirements(cfg, c["initials"])

                    with self.lock:
                        if c["initials"] not in self.procesed_initials:
                            self.courses[c["initials"]] = {
                                "name": c["name"],
                                "credits": c["credits"],
                                "req": req,
                                "conn": con,
                                "restr": restr,
                                "equiv": equiv,
                                "program": program,
                                "school": c["school"],
                                "area": c["area"],
                                "category": c["category"],
                                "sections": {},
                            }
                            print(
                                f"course[{c['initials']}]: {json.dumps(self.courses[c['initials']])}"
                            )
                            self.new_courses += 1
                            self.procesed_initials[c["initials"]] = True

            quota = {}
            if cfg.get("fetch-quota"):
                quota = banner_quota(cfg, c["nrc"], period)

            with self.lock:
                self.courses[c["initials"]]["sections"][str(c["section"])] = {
                    "nrc": c["nrc"],
                    "teachers": c["teachers"],
                    "schedule": process_schedule(c["schedule"]),
                    "format": c["format"],
                    "campus": c["campus"],
                    "is_english": c["is_english"],
                    "is_removable": c["is_removable"],
                    "is_special": c["is_special"],
                    "total_quota": c["total_quota"],
                    "quota": quota,
                }
                print(
                    f"section[{c['initials']}][{c['section']}]: {json.dumps(self.courses[c['initials']]['sections'][str(c['section'])])}"
                )
                self.new_sections += 1

            self._upsert_store_section(period, c["initials"], int(c["section"]))

            log.info(
                "Processed: %s %s",
                c["initials"] + "-" + str(c["section"]),
                c["name"],
            )

        except Exception as err:
            handle(c, err)

    def process_courses(self, cfg, courses: List[Dict[str, Union[str, bool, int]]], period: str, executor: ThreadPoolExecutor):
        """For a list of courses, process and gathers all related data and commits to DB."""
        futures = [executor.submit(self._process_single_course, cfg, c, period) for c in courses]
        for future in as_completed(futures):
            future.result()

    def collect(self, period: str, cfg: dict):
        """Iterates a search throw all BC and process all courses and sections found."""

        testmode: bool = cfg.get('testmode', False)
        max_workers: int = cfg.get("max-workers", 12)

        LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        NUMBERS = "0123456789"
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for l1 in LETTERS:
                comb = l1
                log.info("Searching %s", comb)
                courses = bc_search(cfg, comb, period)
                if testmode and len(courses) > 10:
                    courses = courses[:10]
                    pass
                self.process_courses(cfg, courses, period, executor)
                if testmode:
                    break
                if len(courses) < 50:
                    continue

                for l2 in LETTERS:
                    comb = l1 + l2
                    log.info("Searching %s", comb)
                    courses = bc_search(cfg, comb, period)
                    self.process_courses(cfg, courses, period, executor)
                    if len(courses) < 50:
                        continue

                    for l3 in LETTERS:
                        comb = l1 + l2 + l3
                        log.info("Searching %s", comb)
                        courses = bc_search(cfg, comb, period)
                        self.process_courses(cfg, courses, period, executor)
                        if len(courses) < 50:
                            continue

                        for n1 in NUMBERS:
                            comb = l1 + l2 + l3 + n1
                            log.info("Searching %s", comb)
                            courses = bc_search(cfg, comb, period)
                            self.process_courses(cfg, courses, period, executor)
                            if len(courses) < 50:
                                continue

                            for n2 in NUMBERS:
                                comb = l1 + l2 + l3 + n1 + n2
                                log.info("Searching %s", comb)
                                courses = bc_search(cfg, comb, period)
                                self.process_courses(cfg, courses, period, executor)

        log.info("New courses: %s", self.new_courses)
        log.info("New sections: %s", self.new_sections)
        log.info("Total courses: %s", len(self.procesed_initials))
        log.info("Total sections: %s", len(self.procesed_nrcs))
