#!/usr/bin/env python3
"""Generate annual and animated history SVGs from GitHub public aggregates."""

from __future__ import annotations

import argparse
import calendar
import html
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path


TOTAL_RE = re.compile(
    r'<h2[^>]*id="js-contribution-activity-description"[^>]*>'
    r"\s*([\d,.]+)\s+contributions?",
    re.IGNORECASE,
)
COUNT_RE = re.compile(r"^(No|[\d,.]+)\s+contributions?\s+on\s+", re.IGNORECASE)
MONTHS = ("", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")
CELL = 12
GAP = 3
STEP = CELL + GAP
LEFT = 66
TOP = 86


@dataclass(frozen=True)
class ContributionDay:
    day: date
    count: int
    level: int


class CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cells: dict[str, tuple[date, int]] = {}
        self.tooltips: dict[str, str] = {}
        self._for: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "td" and "ContributionCalendar-day" in classes:
            cell_id = values.get("id")
            raw_date = values.get("data-date")
            raw_level = values.get("data-level")
            if cell_id and raw_date and raw_level is not None:
                self.cells[cell_id] = (date.fromisoformat(raw_date), int(raw_level))
        elif tag == "tool-tip" and values.get("for") in self.cells:
            self._for = values["for"]
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._for is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tool-tip" and self._for is not None:
            self.tooltips[self._for] = "".join(self._text).strip()
            self._for = None
            self._text = []


def parse_number(value: str) -> int:
    return int(value.replace(",", "").replace(".", ""))


def parse_calendar(raw_html: str) -> tuple[list[ContributionDay], int]:
    total_match = TOTAL_RE.search(raw_html)
    if total_match is None:
        raise ValueError("GitHub aggregate total was not found")
    expected_total = parse_number(total_match.group(1))
    parser = CalendarParser()
    parser.feed(raw_html)
    days: list[ContributionDay] = []
    for cell_id, (cell_date, level) in parser.cells.items():
        count_match = COUNT_RE.match(parser.tooltips.get(cell_id, ""))
        if count_match is None:
            raise ValueError(f"contribution count missing for {cell_date}")
        value = count_match.group(1)
        count = 0 if value.lower() == "no" else parse_number(value)
        days.append(ContributionDay(cell_date, count, level))
    days.sort(key=lambda item: item.day)
    actual_total = sum(item.count for item in days)
    if actual_total != expected_total:
        raise ValueError(f"daily sum {actual_total} differs from GitHub total {expected_total}")
    return days, expected_total


def validate_year(days: list[ContributionDay], year: int) -> None:
    expected = 366 if calendar.isleap(year) else 365
    if len(days) != expected:
        raise ValueError(f"{year}: expected {expected} days, found {len(days)}")
    if days[0].day != date(year, 1, 1) or days[-1].day != date(year, 12, 31):
        raise ValueError(f"{year}: incomplete date range")
    if any(item.day.year != year or item.level not in range(5) for item in days):
        raise ValueError(f"{year}: invalid day or level")


def fetch_year(username: str, year: int) -> tuple[list[ContributionDay], int]:
    url = f"https://github.com/users/{username}/contributions?from={year}-01-01&to={year}-12-31"
    request = urllib.request.Request(url, headers={"User-Agent": "USERLIMA-public-history"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw_html = response.read().decode("utf-8")
    days, total = parse_calendar(raw_html)
    validate_year(days, year)
    return days, total


def first_sunday(year: int) -> date:
    first = date(year, 1, 1)
    return first - timedelta(days=(first.weekday() + 1) % 7)


def cell_position(day: date, year: int) -> tuple[int, int]:
    start = first_sunday(year)
    week = (day - start).days // 7
    sunday_index = (day.weekday() + 1) % 7
    return LEFT + week * STEP, TOP + sunday_index * STEP


def week_count(days: list[ContributionDay], year: int) -> int:
    start = first_sunday(year)
    return max((item.day - start).days // 7 for item in days) + 1


def shared_style() -> str:
    return (
        ".title{font:600 16px system-ui,sans-serif;fill:#24292f}"
        ".meta,.label{font:12px system-ui,sans-serif;fill:#57606a}"
        ".cell{stroke:#1b1f230f;stroke-width:1}.l0{fill:#ebedf0}.l1{fill:#9be9a8}"
        ".l2{fill:#40c463}.l3{fill:#30a14e}.l4{fill:#216e39}.snake{fill:#7c3aed}"
        "@media(prefers-color-scheme:dark){.title{fill:#f0f6fc}.meta,.label{fill:#8c959f}"
        ".l0{fill:#161b22}.l1{fill:#0e4429}.l2{fill:#006d32}.l3{fill:#26a641}"
        ".l4{fill:#39d353}.cell{stroke:#ffffff0f}.snake{fill:#a78bfa}}"
    )


def calendar_elements(year: int, days: list[ContributionDay], total: int) -> list[str]:
    parts = [
        f'<text x="16" y="26" class="title">{year} · {total} contribuições</text>',
        '<text x="16" y="50" class="meta">GitHub · agregado público reconhecido para esta conta</text>',
    ]
    for index, label in ((1, "Seg"), (3, "Qua"), (5, "Sex")):
        parts.append(f'<text x="16" y="{TOP + index * STEP + 10}" class="label">{label}</text>')
    start = first_sunday(year)
    for month in range(1, 13):
        week = (date(year, month, 1) - start).days // 7
        parts.append(f'<text x="{LEFT + week * STEP}" y="78" class="label">{MONTHS[month]}</text>')
    for item in days:
        x, y = cell_position(item.day, year)
        label = "Nenhuma contribuição" if item.count == 0 else f"{item.count} contribuição" + ("" if item.count == 1 else "ões")
        parts.append(
            f'<rect class="cell l{item.level}" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2">'
            f'<title>{label} em {item.day.isoformat()}</title></rect>'
        )
    return parts


def render_static(username: str, year: int, days: list[ContributionDay], total: int) -> str:
    width = LEFT + week_count(days, year) * STEP + 24
    height = TOP + 7 * STEP + 54
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">Contribuições de {year}</title>',
        f'<desc id="desc">Calendário público agregado com {total} contribuições reconhecidas para {html.escape(username)} em {year}.</desc>',
        f"<style>{shared_style()}@media(prefers-reduced-motion:reduce){{.snake{{display:none}}}}</style>",
        *calendar_elements(year, days, total),
    ]
    path = snake_path(year, days)
    for part, radius in enumerate((5.0, 4.4, 3.8, 3.2)):
        parts.append(
            f'<circle class="snake" r="{radius:g}" aria-hidden="true">'
            f'<animateMotion dur="6s" begin="-{part * 0.12:g}s" repeatCount="indefinite" path="{path}"/>'
            "</circle>"
        )
    parts.append("</svg>")
    return "".join(parts)


def year_keyframes(index: int, count: int) -> str:
    slot = 100 / count
    start = index * slot
    end = (index + 1) * slot
    fade = min(1.5, slot / 5)
    name = f"year{index}"
    if index == 0:
        return f"@keyframes {name}{{0%,{end-fade:.3f}%{{opacity:1}}{end:.3f}%,100%{{opacity:0}}}}"
    return (
        f"@keyframes {name}{{0%,{start:.3f}%{{opacity:0}}"
        f"{start+fade:.3f}%,{end-fade:.3f}%{{opacity:1}}{end:.3f}%,100%{{opacity:0}}}}"
    )


def snake_path(year: int, days: list[ContributionDay]) -> str | None:
    active = [item for item in days if item.count > 0]
    if not active:
        active = days[::7]
        if active[-1] != days[-1]:
            active.append(days[-1])
    points = []
    for item in active:
        x, y = cell_position(item.day, year)
        points.append((x + CELL / 2, y + CELL / 2))
    if len(points) == 1:
        points.append(points[0])
    return "M" + " L".join(f"{x:g},{y:g}" for x, y in points)


def render_history(
    username: str,
    yearly: list[tuple[int, list[ContributionDay], int]],
    seconds_per_year: int,
) -> str:
    max_weeks = max(week_count(days, year) for year, days, _ in yearly)
    width = LEFT + max_weeks * STEP + 24
    height = TOP + 7 * STEP + 54
    cycle_seconds = seconds_per_year * len(yearly)
    totals = ", ".join(f"{year}: {total}" for year, _, total in yearly)
    animation_style = ".year{opacity:0}" + "".join(
        year_keyframes(index, len(yearly)) + f".year{index}{{animation:year{index} {cycle_seconds}s linear infinite}}"
        for index in range(len(yearly))
    )
    current_index = len(yearly) - 1
    reduced = (
        "@media(prefers-reduced-motion:reduce){.year{animation:none!important;opacity:0!important}"
        f".year{current_index}{{opacity:1!important}}.snake{{display:none}}}}"
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="history-title history-desc">',
        '<title id="history-title">Histórico anual de contribuições</title>',
        f'<desc id="history-desc">Sequência animada dos calendários públicos agregados de {yearly[0][0]} a {yearly[-1][0]}. Totais: {totals}.</desc>',
        f"<style>{shared_style()}{animation_style}{reduced}</style>",
    ]
    for index, (year, days, total) in enumerate(yearly):
        parts.append(f'<g class="year year{index}">')
        parts.extend(calendar_elements(year, days, total))
        path = snake_path(year, days)
        for part, radius in enumerate((5.0, 4.4, 3.8, 3.2)):
            parts.append(
                f'<circle class="snake" r="{radius:g}" aria-hidden="true">'
                f'<animateMotion dur="{seconds_per_year}s" begin="-{part * 0.12:g}s" repeatCount="indefinite" path="{path}"/>'
                "</circle>"
            )
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def run_self_test() -> None:
    synthetic = """
    <h2 id="js-contribution-activity-description">3 contributions</h2>
    <td id="d1" data-date="2023-01-01" data-level="0" class="ContributionCalendar-day"></td>
    <tool-tip for="d1">No contributions on January 1st.</tool-tip>
    <td id="d2" data-date="2023-01-02" data-level="2" class="ContributionCalendar-day"></td>
    <tool-tip for="d2">3 contributions on January 2nd.</tool-tip>
    """
    days, total = parse_calendar(synthetic)
    assert total == 3 and len(days) == 2
    static = render_static("USERLIMA", 2023, days, total)
    history = render_history("USERLIMA", [(2023, days, total)], 6)
    assert "2023 · 3 contribuições" in static
    assert "animateMotion" in history and "dur=\"6s\"" in history
    assert "repository" not in history.lower() and "organization" not in history.lower()
    print("self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="USERLIMA")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--seconds-per-year", type=int, default=6)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.start_year > args.end_year:
        parser.error("--start-year must not be after --end-year")
    if args.seconds_per_year < 2:
        parser.error("--seconds-per-year must be at least 2")
    return args


def main() -> int:
    args = parse_args()
    try:
        if args.self_test:
            run_self_test()
            return 0
        args.output_dir.mkdir(parents=True, exist_ok=True)
        yearly: list[tuple[int, list[ContributionDay], int]] = []
        for year in range(args.start_year, args.end_year + 1):
            days, total = fetch_year(args.username, year)
            yearly.append((year, days, total))
            output = args.output_dir / f"contributions-{year}.svg"
            output.write_text(render_static(args.username, year, days, total), encoding="utf-8")
            print(f"{output}: days={len(days)}; total={total}")
        history = args.output_dir / "contribution-history.svg"
        history.write_text(
            render_history(args.username, yearly, args.seconds_per_year), encoding="utf-8"
        )
        print(f"{history}: years={len(yearly)}; cycle={len(yearly) * args.seconds_per_year}s")
    except (OSError, ValueError, AssertionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
