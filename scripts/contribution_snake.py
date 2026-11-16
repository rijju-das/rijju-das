#!/usr/bin/env python3
"""Draw my GitHub contribution grid as an animated SVG.

A snake crosses the grid, eats every day that has contributions and grows by
one segment for each day it eats. Standard library only.

Usage:
  GITHUB_TOKEN=... GITHUB_USER=rijju-das python3 scripts/contribution_snake.py dist
  python3 scripts/contribution_snake.py dist --from-json calendar.json   (for testing)

Writes:
  dist/github-contribution-grid-snake.svg        (light theme)
  dist/github-contribution-grid-snake-dark.svg   (dark theme)
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
START_LENGTH = 4    # segments before the snake has eaten anything
STEP = 0.11         # seconds the snake takes to move one cell
PAUSE = 2.0         # seconds the empty grid is shown before the loop restarts

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
PALETTES = {
    "light": {"empty": "#ebedf0", "levels": ["#ddd6fe", "#a78bfa", "#7c3aed", "#4c1d95"],
              "snake": "#db2777", "head": "#9d174d", "eye": "#ffffff"},
    "dark": {"empty": "#161b22", "levels": ["#3b1d6e", "#5b21b6", "#7c3aed", "#a78bfa"],
             "snake": "#f472b6", "head": "#fbcfe8", "eye": "#161b22"},
}
QUERY = """query($login: String!) { user(login: $login) { contributionsCollection { contributionCalendar {
  totalContributions weeks { contributionDays { contributionLevel weekday } } } } } }"""


def fetch_weeks(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    request = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": "bearer " + token, "Content-Type": "application/json", "User-Agent": "contribution-snake"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if data.get("errors"):
        raise SystemExit("GitHub API error: %s" % data["errors"])
    return data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]


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


def render(grid, columns, palette):
    route, eaten_at = plan_route(grid, columns)
    steps = len(route) - 1
    final_length = START_LENGTH + len(eaten_at)
    move_time = steps * STEP
    duration = move_time + final_length * STEP + PAUSE
    dur = "%.2fs" % duration
    width = 2 * MARGIN + columns * PITCH - (PITCH - CELL)
    height = 2 * MARGIN + 7 * PITCH - (PITCH - CELL)
    eat_order = sorted(eaten_at.values())

    out = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'viewBox="0 0 %d %d" width="%d" height="%d" role="img">' % (width, height, width, height),
           "<title>A snake eats my GitHub contributions and grows with each day it eats</title>",
           '<defs><path id="track" d="%s"/></defs>' % track_path(route)]

    # the contribution grid: each day with contributions empties when the head reaches it
    for (x, y), level in sorted(grid.items()):
        px, py = MARGIN + x * PITCH, MARGIN + y * PITCH
        base = '<rect x="%d" y="%d" width="%d" height="%d" rx="2.5" fill="%s"' % (
            px, py, CELL, CELL, palette["levels"][level - 1] if level else palette["empty"])
        if (x, y) in eaten_at:
            when = fraction(eaten_at[(x, y)] * STEP / duration)
            out.append(base + '><animate attributeName="fill" calcMode="discrete" values="%s;%s" keyTimes="0;%s" '
                       'dur="%s" repeatCount="indefinite"/></rect>' % (palette["levels"][level - 1], palette["empty"], when, dur))
        else:
            out.append(base + "/>")

    # the snake: every segment follows the same track, each one a step behind the one in front;
    # a new tail segment becomes visible each time a day is eaten
    half = SEGMENT / 2
    for index in range(final_length - 1, -1, -1):          # tail first, so the head is drawn on top
        start = index * STEP / duration
        end = (index * STEP + move_time) / duration
        if index == 0:
            timing = 'keyTimes="0;%s;1" keyPoints="0;1;1"' % fraction(end)
        else:
            timing = 'keyTimes="0;%s;%s;1" keyPoints="0;0;1;1"' % (fraction(start), fraction(end))
        motion = ('<animateMotion dur="%s" repeatCount="indefinite" calcMode="linear" %s%s>'
                  '<mpath xlink:href="#track"/></animateMotion>' % (dur, timing, ' rotate="auto"' if index == 0 else ""))
        if index == 0:
            out.append('<g>%s<rect x="-8" y="-8" width="16" height="16" rx="5" fill="%s"/>'
                       '<circle cx="3.5" cy="-3.5" r="1.7" fill="%s"/><circle cx="3.5" cy="3.5" r="1.7" fill="%s"/></g>'
                       % (motion, palette["head"], palette["eye"], palette["eye"]))
            continue
        shape = '<rect x="%g" y="%g" width="%d" height="%d" rx="4" fill="%s"' % (-half, -half, SEGMENT, SEGMENT, palette["snake"])
        if index < START_LENGTH:
            out.append("%s>%s</rect>" % (shape, motion))
        else:
            appears = fraction(eat_order[index - START_LENGTH] * STEP / duration)
            out.append('%s opacity="0">%s<animate attributeName="opacity" calcMode="discrete" values="0;1" keyTimes="0;%s" '
                       'dur="%s" repeatCount="indefinite"/></rect>' % (shape, motion, appears, dur))
    out.append("</svg>")
    return "\n".join(out), {"steps": steps, "days_eaten": len(eaten_at), "final_length": final_length, "seconds": round(duration, 1)}


def main():
    args = sys.argv[1:]
    out_dir = Path(args[0] if args and not args[0].startswith("--") else "dist")
    if "--from-json" in args:
        weeks = json.loads(Path(args[args.index("--from-json") + 1]).read_text())
    else:
        token = os.environ.get("GITHUB_TOKEN")
        login = os.environ.get("GITHUB_USER")
        if not token or not login:
            raise SystemExit("Set GITHUB_TOKEN and GITHUB_USER, or pass --from-json FILE")
        weeks = fetch_weeks(login, token)
    grid = grid_from_weeks(weeks)
    columns = len(weeks)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, theme in (("github-contribution-grid-snake.svg", "light"), ("github-contribution-grid-snake-dark.svg", "dark")):
        svg, info = render(grid, columns, PALETTES[theme])
        (out_dir / name).write_text(svg, encoding="utf-8")
        print("%-45s %6d bytes  %s" % (name, len(svg), info))


if __name__ == "__main__":
    main()
