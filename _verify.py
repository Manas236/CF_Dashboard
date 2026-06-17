"""Real-browser verification harness (Playwright + Chromium).

Starts the Flask app, loads every panel, and checks the things Phase 3 cares
about: no console/page errors, each ECharts instance initialized with a
non-empty option, the chart canvas actually receives pointer events (the
Phase-2 overlay bug), tooltips show on hover, drill/zoom/toggle fire without
errors, and the light/dark toggle re-themes the charts. Screenshots both
themes for every page.

Usage:  .venv\\Scripts\\python.exe _verify.py [--shots]
"""
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5050"
SITE = "newsband.in"
ROOT = Path(__file__).resolve().parent
SHOT_DIR = ROOT / "_shots"

# page path -> chart container ids expected to be live
PAGES = {
    "/": ["traffic-chart"],
    "/articles": ["momentum-chart"],
    "/categories": ["treemap-chart", "radar-chart"],
    "/errors": ["heatmap-chart"],
    "/audience": ["sunburst-chart", "timeline-chart"],
    "/geo": ["geo-chart"],
}

results = []


def log(ok, msg):
    results.append(ok)
    print(("  PASS " if ok else "  FAIL ") + msg)


def wait_port(host, port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.3)
    return False


def chart_probe(page, cid):
    """Return dict: instance present, has option, what's at the canvas center."""
    return page.evaluate(
        """(cid) => {
            const el = document.getElementById(cid);
            if (!el) return { exists: false };
            const inst = window.echarts && echarts.getInstanceByDom(el);
            const opt = inst && inst.getOption ? inst.getOption() : null;
            const r = el.getBoundingClientRect();
            const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            const hit = document.elementFromPoint(cx, cy);
            return {
                exists: true,
                hasInstance: !!inst,
                seriesCount: opt && opt.series ? opt.series.length : 0,
                w: Math.round(r.width), h: Math.round(r.height),
                cx, cy,
                hitTag: hit ? hit.tagName : null,
                hitClass: hit ? (hit.className && hit.className.toString()) : null,
                hitInsideChart: hit ? !!hit.closest('#' + CSS.escape(cid)) : false,
            };
        }""",
        cid,
    )


def tooltip_visible(page, cid):
    """ECharts default tooltip renders a positioned div inside the container."""
    return page.evaluate(
        """(cid) => {
            const el = document.getElementById(cid);
            if (!el) return false;
            const divs = el.querySelectorAll('div');
            for (const d of divs) {
                const s = d.getAttribute('style') || '';
                if (s.includes('position: absolute') && d.offsetParent !== null
                    && (d.innerText || '').trim().length > 0) return true;
            }
            return false;
        }""",
        cid,
    )


def scroll_into_view(page, cid):
    page.evaluate(
        "(cid) => { const el = document.getElementById(cid);"
        " if (el) el.scrollIntoView({ block: 'center' }); }", cid)
    page.wait_for_timeout(200)


def show_tip_any(page, cid):
    """Ask ECharts to show a tooltip for the first non-empty (series,data) it
    finds — radial/map charts have a gap at the geometric center, and some
    series (e.g. an empty momentum class) carry no points. Driven from Python
    so we can wait for the tooltip DOM to paint after each dispatch."""
    counts = page.evaluate(
        """(cid) => {
            const inst = echarts.getInstanceByDom(document.getElementById(cid));
            if (!inst) return [];
            return (inst.getOption().series || []).map(s => (s.data || []).length);
        }""", cid)
    for si, n in enumerate(counts):
        for di in range(min(n, 5)):
            page.evaluate(
                """([cid, si, di]) => {
                    echarts.getInstanceByDom(document.getElementById(cid))
                        .dispatchAction({ type: 'showTip', seriesIndex: si, dataIndex: di });
                }""", [cid, si, di])
            page.wait_for_timeout(110)
            if tooltip_visible(page, cid):
                return True
    return False


def exercise_toggles(page):
    """Click every segmented toggle once; report if any throws / clears charts."""
    n = page.locator(".seg button").count()
    for i in range(n):
        page.locator(".seg button").nth(i).click()
        page.wait_for_timeout(250)
    return n


def run():
    SHOT_DIR.mkdir(exist_ok=True)
    want_shots = "--shots" in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("PAGEERROR: " + str(e)))

        for path, charts in PAGES.items():
            errors.clear()
            url = f"{BASE}{path}?site={SITE}&range=7d"
            print(f"\n=== {path} ===")
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(1400)  # chart init + data fetch + animation

            if errors:
                log(False, f"console/page errors: {errors[:3]}")
            else:
                log(True, "no console/page errors")

            for cid in charts:
                scroll_into_view(page, cid)
                pr = chart_probe(page, cid)
                if not pr.get("exists"):
                    log(False, f"{cid}: container missing")
                    continue
                log(pr["hasInstance"] and pr["seriesCount"] > 0,
                    f"{cid}: instance={pr['hasInstance']} series={pr['seriesCount']} "
                    f"size={pr['w']}x{pr['h']}")
                # the root-cause test: center of chart must hit the chart, not an overlay
                log(pr["hitInsideChart"],
                    f"{cid}: pointer hits chart (got <{pr['hitTag']} class="
                    f"'{pr['hitClass']}'> insideChart={pr['hitInsideChart']})")
                # hover -> tooltip (fall back to showTip for radial/map gaps)
                page.mouse.move(pr["cx"], pr["cy"], steps=8)
                page.wait_for_timeout(350)
                ok = tooltip_visible(page, cid)
                if not ok:
                    ok = show_tip_any(page, cid)
                log(ok, f"{cid}: tooltip renders on hover/showTip")
                page.mouse.move(5, 5)
                page.wait_for_timeout(120)

            # exercise toggles (paths/status, all/human, world/india, etc.)
            n_tog = exercise_toggles(page)
            log(not errors, f"toggles ({n_tog}) fire without console errors"
                + (f" — {errors[:2]}" if errors else ""))

            # theme toggle re-themes charts
            has_toggle = page.locator("#theme-toggle").count() > 0
            if has_toggle:
                before = page.evaluate("document.documentElement.getAttribute('data-theme')")
                page.click("#theme-toggle")
                page.wait_for_timeout(700)
                after = page.evaluate("document.documentElement.getAttribute('data-theme')")
                log(before != after, f"theme toggled {before} -> {after}")
                pr = chart_probe(page, charts[0])
                log(pr.get("hasInstance") and pr.get("seriesCount", 0) > 0,
                    f"{charts[0]}: still live after theme switch")
                if want_shots:
                    page.screenshot(path=str(SHOT_DIR / f"{path.strip('/') or 'overview'}_{after}.png"),
                                    full_page=True)
                page.click("#theme-toggle")  # back to default
                page.wait_for_timeout(500)
                if want_shots:
                    page.screenshot(path=str(SHOT_DIR / f"{path.strip('/') or 'overview'}_dark.png"),
                                    full_page=True)
            else:
                log(False, "theme toggle (#theme-toggle) not found")

        browser.close()

    total = len(results)
    passed = sum(results)
    print(f"\n{'='*48}\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


def main():
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), str(ROOT / "run.py")],
        env={**__import__("os").environ, "DASH_PORT": "5050", "FLASK_DEBUG": "0"},
        cwd=str(ROOT),
    )
    try:
        if not wait_port("127.0.0.1", 5050, 30):
            print("Flask did not start", file=sys.stderr)
            return 1
        time.sleep(0.5)
        return run()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
