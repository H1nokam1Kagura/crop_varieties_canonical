"""Parse Ghana 2019 National Crop Variety Catalogue -> records.jsonl + .csv

Schema: 11 columns
  Name of Variety | National Code | Origin/Source | Breeder(s)/Institution
  | Applicant | DUS | VCU | Preferred Ecology | Pedigree/Line
  | Year of Release | Year of Registry

Each crop section is preceded by lines like 'Maize - Species: Zea mays L.'.
Crop sections are detected from text; table headers are repeated each page.
"""
import pdfplumber, pathlib, json, csv, re

SRC = pathlib.Path(r"C:\Users\neilha\Downloads\complementary\Ghana_2019_NationalCropVarietyCatalogue.pdf")
OUT = SRC.parent / "ghana_2019"
OUT.mkdir(exist_ok=True)

HEADER_KEY = "Name of Variety"
# Crop heading pattern: e.g. 'Maize - Species: Zea mays L.'
CROP_RE = re.compile(r"^([A-Z][A-Za-z ]+?)\s*[-–]\s*Species:\s*(.+)$", re.MULTILINE)

def main():
    records = []
    current_crop = None
    current_latin = None
    header = None

    with pdfplumber.open(SRC) as pdf:
        for pn, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""

            # Update current crop if a Species: heading appears on this page
            for m in CROP_RE.finditer(text):
                current_crop = m.group(1).strip().upper()
                current_latin = m.group(2).strip().rstrip(".")
                # Special case: Sorghum bicolor L. Moences -> Moench
                if "Moences" in current_latin:
                    current_latin = current_latin.replace("Moences", "Moench")

            for t in page.extract_tables():
                if not t: continue
                rows = [[(c or "").strip().replace("\n"," ") for c in row] for row in t]

                # Identify header row in the table (may be row 0 OR appear mid-table)
                hdr_idx = None
                for i, row in enumerate(rows[:3]):
                    if row and row[0] == HEADER_KEY:
                        hdr_idx = i; break
                if hdr_idx is not None:
                    header = rows[hdr_idx]
                    data_rows = rows[hdr_idx+1:]
                else:
                    data_rows = rows

                if header is None: continue
                for row in data_rows:
                    if not any(row): continue
                    # filter rows that are continuations (variety-name column empty)
                    if not row[0] or row[0] == HEADER_KEY: continue
                    rec = dict(zip(header, row))
                    rec["_page"] = pn
                    rec["_crop_section"] = current_crop
                    rec["_crop_latin"] = current_latin
                    records.append(rec)

            if pn % 10 == 0:
                print(f"  page {pn}/{len(pdf.pages)}: cumulative records={len(records)}")

    print(f"\nTotal records: {len(records)}")
    (OUT / "records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")

    if records:
        keys = list({k for r in records for k in r.keys()})
        # Stable column order
        priority = [HEADER_KEY, "National Code", "Origin/ Source", "Breeder (s)/ Institution",
                    "Applicant", "Distinctness Uniformity and Stability (DUS)",
                    "Value for Cultivation and Use (VCU)", "Preferred Ecology",
                    "Pedigree/ Line", "Year of Release", "Year of Registry",
                    "_crop_section","_crop_latin","_page"]
        cols = [k for k in priority if k in keys] + sorted(set(keys) - set(priority))
        with open(OUT / "records.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in records: w.writerow(r)

    # Stats
    from collections import Counter
    crops = Counter(r.get("_crop_section") for r in records if r.get("_crop_section"))
    print("\nCrop section counts:")
    for c, n in crops.most_common():
        print(f"  {n:>3}  {c}")

if __name__ == "__main__":
    main()
