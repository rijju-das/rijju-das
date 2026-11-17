#!/usr/bin/env python3
"""Draw my GitHub contributions as one animated SVG that moves through the years.

The years sit in one line above the grid. They take turns, newest first: the
current year is highlighted, its line "N contributions in YEAR" and its grid
are shown, and a snake crosses the grid and eats every day that has
contributions. Then the next year appears. Each square has a colour value from
1 (lightest) to 4 (darkest); the snake gains one body block each time the
colour it has eaten adds up to one darkest square. Standard library only.

Usage:
  GITHUB_TOKEN=... GITHUB_USER=rijju-das python3 scripts/contribution_snake.py dist
  python3 scripts/contribution_snake.py dist --from-json years.json   (for testing: {"2026": weeks, ...})

Writes:
  dist/contributions.svg        (light theme)
  dist/contributions-dark.svg   (dark theme)
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

PITCH = 16          # distance between cell centres, in pixels
CELL = 12           # cell size
MARGIN = 8
SEGMENT = 14        # snake body segment size
START_LENGTH = 3    # blocks before the snake has eaten anything: the head and two body blocks
LEVEL_VALUE = {1: 1, 2: 2, 3: 3, 4: 4}   # colour value of a square, from lightest to darkest
FULL_BLOCK = 4      # colour value the snake must eat to gain one body block (one darkest square)
STEP = 0.11         # seconds the snake takes to move one cell
PAUSE = 1.2         # seconds the empty grid is shown before the next year appears
YEAR_ROW = 36       # room for the line of years at the top
YEAR_WIDTH = 52     # size of one year in that line
YEAR_HEIGHT = 24
YEAR_SPACING = 8
LABEL_HEIGHT = 24   # room for the "N contributions in YEAR" line above the grid
FONT = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
PALETTES = {
    "light": {"empty": "#ebedf0", "levels": ["#ddd6fe", "#a78bfa", "#7c3aed", "#4c1d95"],
              "snake": "#db2777", "head": "#9d174d", "eye": "#ffffff", "label": "#57606a",
              "active": "#7c3aed", "active_text": "#ffffff"},
    "dark": {"empty": "#161b22", "levels": ["#3b1d6e", "#5b21b6", "#7c3aed", "#a78bfa"],
             "snake": "#f472b6", "head": "#fbcfe8", "eye": "#161b22", "label": "#8b949e",
             "active": "#6d28d9", "active_text": "#ffffff"},
}
YEARS_QUERY = "query($login: String!) { user(login: $login) { contributionsCollection { contributionYears } } }"
CALENDAR_QUERY = """query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
  contributionsCollection(from: $from, to: $to) { contributionCalendar {
    totalContributions weeks { contributionDays { contributionLevel weekday } } } } } }"""


def ask_github(query, variables, token):
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": "bearer " + token, "Content-Type": "application/json", "User-Agent": "contribution-snake"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if data.get("errors"):
        raise SystemExit("GitHub API error: %s" % data["errors"])
    return data["data"]["user"]["contributionsCollection"]


def fetch_years(login, token):
    """Return {year: {"total": contributions, "weeks": weeks}} for every calendar year with contributions."""
    years = ask_github(YEARS_QUERY, {"login": login}, token)["contributionYears"]
    calendars = {}
    for year in years:
        variables = {"login": login, "from": "%d-01-01T00:00:00Z" % year, "to": "%d-12-31T23:59:59Z" % year}
        calendar = ask_github(CALENDAR_QUERY, variables, token)["contributionCalendar"]
        calendars[str(year)] = {"total": calendar["totalContributions"], "weeks": calendar["weeks"]}
    return calendars


def grid_from_weeks(weeks):
    """Return {(column, row): level 0-4} for every day in the calendar."""
    grid = {}
    for x, week in enumerate(weeks):
        for day in week["contributionDays"]:
            grid[(x, day["weekday"])] = LEVELS.get(day["contributionLevel"], 0)
    return grid


def plan_route(grid, columns):
    """Walk to the nearest uneaten day each time. Returns the cells visited, one per
    step, and the step at which each day is eaten."""
    position = (-(START_LENGTH + 1), 3)          # start outside the left edge
    route = [position]
    eaten_at = {}
    remaining = {cell for cell, level in grid.items() if level > 0}

    def move_to(target):
        nonlocal position
        for axis in (0, 1):                       # horizontal first, then vertical
            while position[axis] != target[axis]:
                delta = 1 if target[axis] > position[axis] else -1
                position = (position[0] + delta, position[1]) if axis == 0 else (position[0], position[1] + delta)
                route.append(position)
                if position in remaining:
                    remaining.discard(position)
                    eaten_at[position] = len(route) - 1

    while remaining:
        target = min(remaining, key=lambda c: (abs(c[0] - position[0]) + abs(c[1] - position[1]), c[0], c[1]))
        move_to(target)
    move_to((columns + 1, position[1]))           # leave through the right edge
    return route, eaten_at


def growth_steps(grid, eaten_at):
    """Steps at which the snake gains a body block. Each square eaten adds its colour
    value to a running total; a block is added each time the total reaches another
    FULL_BLOCK. Any colour left over carries on towards the next block."""
    steps, total = [], 0
    for cell, step in sorted(eaten_at.items(), key=lambda item: item[1]):
        total += LEVEL_VALUE[grid[cell]]
        while total >= FULL_BLOCK * (len(steps) + 1):
            steps.append(step)
    return steps


def centre(cell):
    return (MARGIN + cell[0] * PITCH + CELL / 2, MARGIN + cell[1] * PITCH + CELL / 2)


def track_path(route):
    """SVG path through the route, keeping only the corners."""
    points = [route[0]]
    for previous, current, following in zip(route, route[1:], route[2:]):
        straight = (current[0] - previous[0], current[1] - previous[1]) == (following[0] - current[0], following[1] - current[1])
        if not straight:
            points.append(current)
    points.append(route[-1])
    parts = []
    for index, cell in enumerate(points):
        x, y = centre(cell)
        parts.append("%s%g %g" % ("M" if index == 0 else "L", x, y))
    return " ".join(parts)


def fraction(value):
    return ("%.5f" % value).rstrip("0").rstrip(".") or "0"


def plan_year(grid, columns):
    route, eaten_at = plan_route(grid, columns)
    grow_at = growth_steps(grid, eaten_at)
    steps = len(route) - 1
    return {"grid": grid, "route": route, "eaten_at": eaten_at, "grow_at": grow_at, "steps": steps,
            "final_length": START_LENGTH + len(grow_at),
            "busy_time": steps * STEP + (START_LENGTH + len(grow_at)) * STEP}


def shown_between(on, off, start, end):
    """values and keyTimes for a discrete animation that is `on` from start to end (fractions of the loop)."""
    if start <= 0 and end >= 1:
        return None
    if start <= 0:
        return "%s;%s" % (on, off), "0;%s" % fraction(end)
    if end >= 1:
        return "%s;%s" % (off, on), "0;%s" % fraction(start)
    return "%s;%s;%s" % (off, on, off), "0;%s;%s" % (fraction(start), fraction(end))


def switch(attribute, on, off, start, end, dur):
    """An <animate> element that sets `attribute` to `on` between start and end, and `off` otherwise."""
    timing = shown_between(on, off, start, end)
    if timing is None:
        return ""
    return ('<animate attributeName="%s" calcMode="discrete" values="%s" keyTimes="%s" dur="%s" repeatCount="indefinite"/>'
            % (attribute, timing[0], timing[1], dur))


def draw_year(plan, palette, duration, track_id, offset=0.0):
    """SVG for one year's grid and its snake. `offset` is when this year's turn starts, in seconds."""
    dur = "%.2fs" % duration
    grid, eaten_at, grow_at = plan["grid"], plan["eaten_at"], plan["grow_at"]
    move_time = plan["steps"] * STEP
    out = []

    # the contribution grid: each day with contributions empties when the head reaches it
    for (x, y), level in sorted(grid.items()):
        px, py = MARGIN + x * PITCH, MARGIN + y * PITCH
        base = '<rect x="%d" y="%d" width="%d" height="%d" rx="2.5" fill="%s"' % (
            px, py, CELL, CELL, palette["levels"][level - 1] if level else palette["empty"])
        if (x, y) in eaten_at:
            when = fraction((offset + eaten_at[(x, y)] * STEP) / duration)
            out.append(base + '><animate attributeName="fill" calcMode="discrete" values="%s;%s" keyTimes="0;%s" '
                       'dur="%s" repeatCount="indefinite"/></rect>' % (palette["levels"][level - 1], palette["empty"], when, dur))
        else:
            out.append(base + "/>")

    # the snake: every block follows the same track, each one a step behind the one in front;
    # a new tail block becomes visible each time the colour eaten completes another block
    half = SEGMENT / 2
    for index in range(plan["final_length"] - 1, -1, -1):  # tail first, so the head is drawn on top
        start = (offset + index * STEP) / duration
        end = (offset + index * STEP + move_time) / duration
        if start <= 0:
            timing = 'keyTimes="0;%s;1" keyPoints="0;1;1"' % fraction(end)
        else:
            timing = 'keyTimes="0;%s;%s;1" keyPoints="0;0;1;1"' % (fraction(start), fraction(end))
        motion = ('<animateMotion dur="%s" repeatCount="indefinite" calcMode="linear" %s%s>'
                  '<mpath xlink:href="#%s"/></animateMotion>' % (dur, timing, ' rotate="auto"' if index == 0 else "", track_id))
        if index == 0:
            out.append('<g>%s<rect x="-8" y="-8" width="16" height="16" rx="5" fill="%s"/>'
                       '<circle cx="3.5" cy="-3.5" r="1.7" fill="%s"/><circle cx="3.5" cy="3.5" r="1.7" fill="%s"/></g>'
                       % (motion, palette["head"], palette["eye"], palette["eye"]))
            continue
        shape = '<rect x="%g" y="%g" width="%d" height="%d" rx="4" fill="%s"' % (-half, -half, SEGMENT, SEGMENT, palette["snake"])
        if index < START_LENGTH:
            out.append("%s>%s</rect>" % (shape, motion))
        else:
            appears = fraction((offset + grow_at[index - START_LENGTH] * STEP) / duration)
            out.append('%s opacity="0">%s<animate attributeName="opacity" calcMode="discrete" values="0;1" keyTimes="0;%s" '
                       'dur="%s" repeatCount="indefinite"/></rect>' % (shape, motion, appears, dur))
    return out


def normalise(calendars):
    """Accept {year: weeks} or {year: {"total": n, "weeks": weeks}}."""
    return {str(year): (value if isinstance(value, dict) else {"total": None, "weeks": value})
            for year, value in calendars.items()}


def render(calendars, palette):
    """One picture: the years in a line at the top, then the heading and grid of the year whose turn it is."""
    calendars = normalise(calendars)
    labels = sorted(calendars, reverse=True)
    columns = max(len(calendars[label]["weeks"]) for label in labels)
    plans = {label: plan_year(grid_from_weeks(calendars[label]["weeks"]), columns) for label in labels}
    turns, clock = {}, 0.0
    for label in labels:                                   # each year's turn: (start, end) in seconds
        turns[label] = (clock, clock + plans[label]["busy_time"] + PAUSE)
        clock = turns[label][1]
    duration = clock
    dur = "%.2fs" % duration
    only_one = len(labels) == 1

    width = 2 * MARGIN + columns * PITCH - (PITCH - CELL)
    height = YEAR_ROW + LABEL_HEIGHT + 2 * MARGIN + 7 * PITCH - (PITCH - CELL)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'viewBox="0 0 %d %d" width="%d" height="%d" role="img">' % (width, height, width, height),
           "<title>My GitHub contributions, year by year: a snake eats each year's grid and grows as it eats</title>",
           "<defs>%s</defs>" % "".join('<path id="track%d" d="%s"/>' % (i, track_path(plans[label]["route"]))
                                       for i, label in enumerate(labels))]

    # the line of years at the top: the year being shown is highlighted
    for i, label in enumerate(labels):
        start, end = turns[label][0] / duration, turns[label][1] / duration
        first = start <= 0 or only_one
        x, y = MARGIN + i * (YEAR_WIDTH + YEAR_SPACING), 4
        out.append('<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s" opacity="%s">%s</rect>' % (
            x, y, YEAR_WIDTH, YEAR_HEIGHT, palette["active"], "1" if first else "0", switch("opacity", "1", "0", start, end, dur)))
        out.append('<text x="%g" y="%g" text-anchor="middle" font-family="%s" font-size="13" font-weight="600" fill="%s">%s%s</text>' % (
            x + YEAR_WIDTH / 2, y + 17, FONT, palette["active_text"] if first else palette["label"], label,
            switch("fill", palette["active_text"], palette["label"], start, end, dur)))

    # the heading and grid: every year is drawn in the same place and only shown during its turn
    for i, label in enumerate(labels):
        start, end = turns[label][0] / duration, turns[label][1] / duration
        visible = switch("opacity", "1", "0", start, end, dur)
        total = calendars[label]["total"]
        heading = ("%s contribution%s in %s" % (total, "" if total == 1 else "s", label)) if total is not None else label
        out.append('<g transform="translate(0 %d)"%s>%s' % (YEAR_ROW, ' opacity="0"' if (visible and start > 0) else "", visible))
        out.append('<text x="%d" y="16" font-family="%s" font-size="13" fill="%s">%s</text>' % (MARGIN, FONT, palette["label"], heading))
        out.append('<g transform="translate(0 %d)">' % LABEL_HEIGHT)
        out.extend(draw_year(plans[label], palette, duration, "track%d" % i, turns[label][0]))
        out.append("</g></g>")
    out.append("</svg>")
    info = {label: {"days_eaten": len(plans[label]["eaten_at"]), "blocks_gained": len(plans[label]["grow_at"]),
                    "final_length": plans[label]["final_length"], "turn_seconds": [round(t, 1) for t in turns[label]]}
            for label in labels}
    return "\n".join(out), {"years": info, "loop_seconds": round(duration, 1), "size": "%dx%d" % (width, height)}


def main():
    args = sys.argv[1:]
    out_dir = Path(args[0] if args and not args[0].startswith("--") else "dist")
    if "--from-json" in args:
        calendars = json.loads(Path(args[args.index("--from-json") + 1]).read_text())
    else:
        token = os.environ.get("GITHUB_TOKEN")
        login = os.environ.get("GITHUB_USER")
        if not token or not login:
            raise SystemExit("Set GITHUB_TOKEN and GITHUB_USER, or pass --from-json FILE")
        calendars = fetch_years(login, token)
    if not calendars:
        raise SystemExit("No contribution years found")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, theme in (("contributions.svg", "light"), ("contributions-dark.svg", "dark")):
        svg, info = render(calendars, PALETTES[theme])
        (out_dir / name).write_text(svg, encoding="utf-8")
        print("%-26s %6d bytes  %s" % (name, len(svg), json.dumps(info)))


if __name__ == "__main__":
    main()
