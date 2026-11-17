#!/usr/bin/env python3
"""Draw my GitHub contributions as animated SVGs, one picture per year.

Each picture looks like the contribution panel on a GitHub profile: the line
"N contributions in YEAR" above that year's grid. A snake crosses the grid and
eats every day that has contributions, then the picture loops. Each square has
a colour value from 1 (lightest) to 4 (darkest); the snake gains one body block
each time the colour it has eaten adds up to one darkest square.
Standard library only.

Usage:
  GITHUB_TOKEN=... GITHUB_USER=rijju-das python3 scripts/contribution_snake.py dist
  python3 scripts/contribution_snake.py dist --from-json years.json   (for testing: {"2026": weeks, ...})

Writes, for every year with contributions:
  dist/contributions-YEAR.svg        (light theme)
  dist/contributions-YEAR-dark.svg   (dark theme)
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
PAUSE = 1.5         # seconds the empty grid is shown before the loop restarts
LABEL_HEIGHT = 24   # room for the "N contributions in YEAR" line above the grid
FONT = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
PALETTES = {
    "light": {"empty": "#ebedf0", "levels": ["#ddd6fe", "#a78bfa", "#7c3aed", "#4c1d95"],
              "snake": "#db2777", "head": "#9d174d", "eye": "#ffffff", "label": "#57606a"},
    "dark": {"empty": "#161b22", "levels": ["#3b1d6e", "#5b21b6", "#7c3aed", "#a78bfa"],
             "snake": "#f472b6", "head": "#fbcfe8", "eye": "#161b22", "label": "#8b949e"},
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


def draw_year(plan, palette, duration, track_id, offset=0.0):
    """SVG for one year's grid and its snake, looping every `duration` seconds."""
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


def render_year(label, calendar, palette, columns):
    """One year's picture: the heading, the grid and its snake, looping on its own."""
    plan = plan_year(grid_from_weeks(calendar["weeks"]), columns)
    duration = plan["busy_time"] + PAUSE
    width = 2 * MARGIN + columns * PITCH - (PITCH - CELL)
    height = LABEL_HEIGHT + 2 * MARGIN + 7 * PITCH - (PITCH - CELL)
    total = calendar["total"]
    heading = ("%s contribution%s in %s" % (total, "" if total == 1 else "s", label)) if total is not None else label

    out = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'viewBox="0 0 %d %d" width="%d" height="%d" role="img">' % (width, height, width, height),
           "<title>My GitHub contributions in %s: a snake eats the grid and grows as it eats</title>" % label,
           '<defs><path id="track" d="%s"/></defs>' % track_path(plan["route"]),
           '<text x="%d" y="16" font-family="%s" font-size="13" fill="%s">%s</text>' % (MARGIN, FONT, palette["label"], heading),
           '<g transform="translate(0 %d)">' % LABEL_HEIGHT]
    out.extend(draw_year(plan, palette, duration, "track"))
    out.append("</g></svg>")
    info = {"days_eaten": len(plan["eaten_at"]), "blocks_gained": len(plan["grow_at"]),
            "final_length": plan["final_length"], "loop_seconds": round(duration, 1), "size": "%dx%d" % (width, height)}
    return "\n".join(out), info


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
    calendars = normalise(calendars)
    columns = max(len(calendar["weeks"]) for calendar in calendars.values())   # same width for every year
    out_dir.mkdir(parents=True, exist_ok=True)
    for label in sorted(calendars, reverse=True):
        for suffix, theme in (("", "light"), ("-dark", "dark")):
            svg, info = render_year(label, calendars[label], PALETTES[theme], columns)
            name = "contributions-%s%s.svg" % (label, suffix)
            (out_dir / name).write_text(svg, encoding="utf-8")
            print("%-32s %6d bytes  %s" % (name, len(svg), json.dumps(info)))


if __name__ == "__main__":
    main()
