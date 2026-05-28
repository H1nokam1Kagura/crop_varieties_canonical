"""
check_sources.py - quarterly fingerprint diff for the canonical pipeline.

For each upstream source, perform a *cheap* check (HEAD, count-only API,
or first-N-bytes hash) to detect whether the source has changed since
the last recorded fingerprint. No bulk downloads. Designed to run in <60s.

State file:
  unified/source_fingerprints.json
    { "<source>": {
        "url":         "...",
        "method":      "head|stats|jsonbody|wiewscount",
        "fingerprint": "<hash or count>",
        "last_checked": "<iso>",
      }, ...
    }

Usage:
  py check_sources.py              # check and print diff
  py check_sources.py --commit     # check, print diff, AND update state file
  py check_sources.py --json       # machine-readable output

Exit codes:
  0  no changes detected
  1  one or more sources changed (re-run pipeline)
  2  one or more sources erroring (investigate manually)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "unified" / "source_fingerprints.json"

NOAUTH_CTX = ssl.create_default_context()
NOAUTH_CTX.check_hostname = False
NOAUTH_CTX.verify_mode = ssl.CERT_NONE  # corporate-proxy survival

BROWSER_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------- per-source fingerprint strategies ----------

def fp_agra() -> tuple[str, dict]:
    """AGRA: /api/visits/stats returns {total: N, varieties: M}.

    Note: `varieties` here counts only currently-active varieties from the AGRA
    perspective (~3911), whereas our extraction includes inactive + test entries
    (~4605). The fingerprint will lag the row count by some constant, but ticks
    up reliably whenever new varieties are registered — that's all we need.
    """
    url = "https://varietycatalogues.com/apiv1/public/api/visits/stats"
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={**BROWSER_HDRS, "Accept": "application/json"}),
        timeout=20,
    ) as r:
        obj = json.loads(r.read())
    n = int(obj.get("varieties", -1))
    return f"varieties_count:{n}", {"url": url, "method": "stats",
                                     "extra": {"raw": obj}}

def fp_ppvfra() -> tuple[str, dict]:
    """PPV&FRA: HEAD request on cer.json, fingerprint Content-Length + Last-Modified."""
    url = "https://plantauthority.gov.in/sites/default/files/cer.json"
    req = urllib.request.Request(url, headers=BROWSER_HDRS, method="HEAD")
    with urllib.request.urlopen(req, timeout=20) as r:
        size = r.headers.get("Content-Length", "?")
        lm   = r.headers.get("Last-Modified", "?")
    return f"size:{size}|lm:{lm}", {"url": url, "method": "head"}

def fp_wiews() -> tuple[str, dict]:
    """WIEWS: POST wiewsIndicatorsSearch for global aggregate (1 row).
    Track NumberOfNewVarieties (global count) — increments when iterations close."""
    url = "https://wiews.fao.org/wiewsIndicatorsSearch"
    body = json.dumps({
        "lang": "en", "indicator": 40, "separator": ",",
        "filters": {"region": {"type": "M49", "values": ["1"]},
                    "iteration": ["1"]},
        "stakeholder": False, "list_of_countries": False,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        **BROWSER_HDRS,
        "Content-Type": "text/plain; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.fao.org/",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=NOAUTH_CTX) as r:
        obj = json.loads(r.read())
    n = obj["data"][0]["NumberOfNewVarieties"] if obj.get("data") else -1
    return f"global_count:{n}", {"url": url, "method": "wiewscount",
                                  "extra": {"raw": obj}}

def fp_recovery_probe(name: str, url: str) -> tuple[str, dict]:
    """Watch-source probe: ping URL with GET, fingerprint only the status code
    + content-type (NOT body hash — too noisy for live pages with timestamps).

    Used for sources that are currently blocked/down. A status flip
    (503 -> 200, DNS failure -> 200) is the "changed" signal that says:
    try extracting again. We deliberately don't track body content; if a site
    starts serving real data after being in maintenance, you'll see the status
    code stay 200 but you'll notice when you re-probe manually.
    """
    try:
        req = urllib.request.Request(url, headers=BROWSER_HDRS)
        with urllib.request.urlopen(req, timeout=15, context=NOAUTH_CTX) as r:
            ct = (r.headers.get("Content-Type", "?") or "?").split(";")[0].strip()
            return f"status:{r.status}|ct:{ct}", {"url": url, "method": "recovery_probe"}
    except urllib.error.HTTPError as e:
        return f"status:{e.code}|reason:{e.reason}", {"url": url, "method": "recovery_probe"}
    except Exception as e:
        return f"err:{type(e).__name__}", {"url": url, "method": "recovery_probe"}

def fp_pdf_head(name: str, url: str) -> tuple[str, dict]:
    """Generic PDF source: HEAD for Last-Modified + Content-Length."""
    req = urllib.request.Request(url, headers=BROWSER_HDRS, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=20, context=NOAUTH_CTX) as r:
            size = r.headers.get("Content-Length", "?")
            lm   = r.headers.get("Last-Modified", "?")
        return f"size:{size}|lm:{lm}", {"url": url, "method": "head"}
    except urllib.error.HTTPError as e:
        # Some servers reject HEAD; fall back to range GET (first 4 KB)
        if e.code in (403, 405, 501):
            req2 = urllib.request.Request(url, headers={**BROWSER_HDRS,
                "Range": "bytes=0-4095"}, method="GET")
            with urllib.request.urlopen(req2, timeout=20, context=NOAUTH_CTX) as r:
                body = r.read()
                lm = r.headers.get("Last-Modified", "?")
                size = r.headers.get("Content-Range", "?")
            h = hashlib.sha256(body).hexdigest()[:16]
            return f"range_hash:{h}|lm:{lm}|range:{size}", {"url": url, "method": "range_get"}
        raise

SOURCES = [
    # ---- Active sources (ingested into canonical) ----
    ("agra",        lambda: fp_agra()),
    ("ppvfra",      lambda: fp_ppvfra()),
    ("wiews_global",lambda: fp_wiews()),
    ("nacgrab",     lambda: fp_pdf_head("nacgrab",
        "https://www.nacgrab.gov.ng/wp-content/uploads/2025/10/Varieties-Released-Catalogue-updated-April-2025.pdf")),
    ("kephis_2025", lambda: fp_pdf_head("kephis_2025",
        "https://www.kephis.go.ke/sites/default/files/2025-02/NATIONAL%20CROP%20VARIETY%20LIST-%202025%20EDITION.pdf")),
    ("ecowas",      lambda: fp_pdf_head("ecowas",
        "https://ecowap.ecowas.int/media/events/concept/all/Regional_Catalogue_Version.pdf")),
    ("ghana_2019",  lambda: fp_pdf_head("ghana_2019",
        "https://nastag.org/docx/resources/2019%20NATIONAL%20CROP%20VARIETY%20CATALOGUE.pdf")),

    # ---- Watch sources (currently blocked / not ingested; want recovery signal) ----
    ("cimmyt_maize_watch", lambda: fp_recovery_probe("cimmyt",
        "https://maizecatalog.cimmyt.org/")),
    ("glomip_watch",       lambda: fp_recovery_probe("glomip",
        "https://glomip.cgiar.org/product-catalog")),
    ("cgspace_watch",      lambda: fp_recovery_probe("cgspace",
        "https://cgspace.cgiar.org/server/api")),
    # FAO data catalog WIEWS bulk dump — may publish CSV exports we can use directly
    ("fao_wiews_catalog_watch", lambda: fp_recovery_probe("fao_catalog",
        "https://data.apps.fao.org/catalog/dataset/fao-wiews")),
    # Ethiopia EAA — the only African country in our targets with no national source yet
    ("ethiopia_eaa_watch", lambda: fp_recovery_probe("ethiopia_eaa",
        "https://www.eservices.gov.et/en/services?oID=1009&name=Ethiopian+Agricultural+Authority")),
    # Sri Lanka — Department of Agriculture Seed Certification Service
    ("srilanka_doa_watch", lambda: fp_recovery_probe("srilanka_doa",
        "https://doa.gov.lk/scs-home/")),
    # Bangladesh — Ministry of Agriculture portal (NSB lists are PDFs under here)
    ("bangladesh_moa_watch", lambda: fp_recovery_probe("bangladesh_moa",
        "https://moa.portal.gov.bd/")),
    # Pakistan — Federal Seed Certification & Registration Department (note: HTTP not HTTPS)
    ("pakistan_fscrd_watch", lambda: fp_recovery_probe("pakistan_fscrd",
        "http://www.federalseed.gov.pk/")),
    # Pakistan — Plant Breeders' Rights Registry (separate from FSC&RD)
    ("pakistan_pbrr_watch", lambda: fp_recovery_probe("pakistan_pbrr",
        "https://pbrr.gov.pk/")),
]

# ---------- main ----------

def load_state() -> dict:
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                     encoding="utf-8")

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="Write new fingerprints to state file")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON instead of a table")
    args = ap.parse_args()

    prev = load_state()
    now  = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = []

    for name, fn in SOURCES:
        prev_fp = (prev.get(name) or {}).get("fingerprint")
        try:
            new_fp, meta = fn()
            status = "new" if not prev_fp else ("unchanged" if new_fp == prev_fp else "changed")
            results.append({
                "source": name, "status": status,
                "url": meta.get("url"),
                "method": meta.get("method"),
                "prev_fp": prev_fp,
                "new_fp": new_fp,
                "checked_at": now,
            })
        except Exception as e:
            results.append({
                "source": name, "status": "error",
                "error": f"{type(e).__name__}: {e}",
                "checked_at": now,
            })

    # Output
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        # Human-readable table
        print(f"Quarterly source-fingerprint check  [{now}]")
        print("=" * 90)
        print(f"{'source':<14} {'status':<10} {'fingerprint diff'}")
        print("-" * 90)
        for r in results:
            st = r["status"]
            tag = {
                "unchanged": "OK",
                "changed":   "CHG",
                "new":       "NEW",
                "error":     "ERR",
            }[st]
            line = f"{r['source']:<14} {tag:<10} "
            if st == "changed":
                line += f"{r['prev_fp']}  ->  {r['new_fp']}"
            elif st == "new":
                line += f"<no prior>  ->  {r['new_fp']}"
            elif st == "error":
                line += r["error"]
            else:
                line += r["new_fp"]
            print(line)
        print("=" * 90)

        # Action summary
        changed = [r["source"] for r in results if r["status"] in ("changed", "new")]
        errors  = [r["source"] for r in results if r["status"] == "error"]
        if changed:
            print(f"\nRe-extract these sources:")
            for c in changed:
                print(f"  - {c}")
        if errors:
            print(f"\nErrors — investigate:")
            for e in errors:
                print(f"  - {e}")
        if not (changed or errors):
            print("\nNo changes detected. Skip extraction; pipeline can stay as-is.")
        if changed and not args.commit:
            print("\n(Re-run with --commit to record new fingerprints once you've "
                  "re-extracted the changed sources.)")

    # Commit if requested
    if args.commit:
        new_state = dict(prev)
        for r in results:
            if r["status"] in ("unchanged", "changed", "new"):
                new_state[r["source"]] = {
                    "url": r.get("url"),
                    "method": r.get("method"),
                    "fingerprint": r["new_fp"],
                    "last_checked": r["checked_at"],
                }
        save_state(new_state)
        print(f"\nWrote {STATE}")

    # Exit code
    if any(r["status"] == "error" for r in results):
        return 2
    if any(r["status"] in ("changed", "new") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
