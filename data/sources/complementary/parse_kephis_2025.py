"""Parse KEPHIS Kenya 2025 National Crop Variety List -> records.jsonl + .csv

PDF is organised by sections like '4. NATIONAL SWEET POTATO VARIETY LIST'
followed by 'Species: Ipomea batatas' and then a table.

Table schemas vary slightly per crop. Common columns include:
  Variety name (or Variety name/code, Variety testing name/code)
  (Official) Year of release
  Owner(s)/Licensee
  Maintainer and seed source
  Optimal production altitude (Masl)
  Duration to maturity
  Yield
  Special attributes
"""
import pdfplumber, pathlib, json, csv, re

SRC = pathlib.Path(r"C:\Users\neilha\Downloads\complementary\KEPHIS_Kenya_VarietyList_2025.pdf")
OUT = SRC.parent / "kephis_2025"
OUT.mkdir(exist_ok=True)

SECTION_RE = re.compile(
    r"^\s*(\d+)\.\s+NATIONAL\s+(.+?)\s+VARIETY\s+LIST",
    re.IGNORECASE | re.MULTILINE)
SPECIES_RE = re.compile(r"Species:\s*([A-Z][A-Za-z\.\,\s\-/×]+)", re.IGNORECASE)

# A row is "data" if its first non-empty cell is a number (sequence id)
def is_data_row(row):
    if not row or not row[0]: return False
    first = row[0].strip().rstrip(".")
    # Allow "1." or "1" or "1 " etc.
    head = re.split(r"[\.\s]", first, maxsplit=1)[0]
    return head.isdigit()

def merge_continuation(rows):
    """KEPHIS rows often wrap; rows with empty first cell continue the previous record."""
    merged = []
    for row in rows:
        if not any(row): continue
        if merged and not (row[0] or "").strip():
            # continuation — append to previous columns
            for i, cell in enumerate(row):
                if cell and i < len(merged[-1]):
                    if merged[-1][i]:
                        merged[-1][i] = merged[-1][i] + " " + cell
                    else:
                        merged[-1][i] = cell
        else:
            merged.append(list(row))
    return merged

def main():
    records = []
    current_section = None       # e.g. "SWEET POTATO"
    current_species = None
    header = None
    section_count = {}

    with pdfplumber.open(SRC) as pdf:
        for pn, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""

            m = SECTION_RE.search(text)
            if m:
                current_section = m.group(2).strip().upper()
                # Try to grab species off the same page
                sp = SPECIES_RE.search(text)
                current_species = sp.group(1).strip() if sp else None
                header = None  # reset — different section, different schema

            for t in page.extract_tables():
                if not t: continue
                rows = [[(c or "").strip().replace("\n"," ") for c in row] for row in t]

                # Find header row — heuristic: first row containing "Variety" in cell 0 or "Year" anywhere
                hdr_idx = None
                for i, row in enumerate(rows[:3]):
                    joined = " | ".join(row).lower()
                    if "variety" in joined and ("year" in joined or "release" in joined):
                        hdr_idx = i; break

                if hdr_idx is not None:
                    header = rows[hdr_idx]
                    data_rows = rows[hdr_idx+1:]
                elif header is None:
                    # Skip orphan table fragments before any header has been seen
                    continue
                else:
                    data_rows = rows

                data_rows = merge_continuation(data_rows)
                for row in data_rows:
                    if not is_data_row(row): continue
                    rec = dict(zip(header, row))
                    rec["_page"] = pn
                    rec["_section"] = current_section
                    rec["_species"] = current_species
                    records.append(rec)
                    section_count[current_section] = section_count.get(current_section, 0) + 1

            if pn % 25 == 0:
                print(f"  page {pn}/{len(pdf.pages)}: records={len(records)}")

    print(f"\nTotal records: {len(records)}")
    (OUT / "records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")

    if records:
        keys = sorted({k for r in records for k in r.keys()})
        # Stable order: meta first, then everything else
        meta = ["_section","_species","_page"]
        cols = meta + [k for k in keys if k not in meta]
        with open(OUT / "records.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in records: w.writerow(r)

    print("\nRecords per section:")
    for sec, n in sorted(section_count.items(), key=lambda x: -x[1])[:30]:
        print(f"  {n:>4}  {sec}")

if __name__ == "__main__":
    main()
