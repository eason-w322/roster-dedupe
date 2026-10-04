
#!/usr/bin/env python3
"""
BLCK UNICRN — Safety list dedupe + flag tool (Week 3, Job 2).
Point it at a folder of Apollo CSV exports. It unions them, removes duplicate
people, flags each, and reports the real unique count.
 
Usage:  python dedupe_safety_lists.py  <folder_with_csvs>  [output_folder]
"""
import csv, sys, glob, os, re
from collections import defaultdict
 
def norm_email(s):
    return (s or "").strip().lower()
 
def has_phone(row):
    for c in ["Work Direct Phone","Home Phone","Mobile Phone","Corporate Phone","Other Phone","Company Phone"]:
        v = (row.get(c) or "").strip().strip("'").strip()
        if re.search(r"\d", v):
            return True
    return False
 
def is_true(v):
    return (v or "").strip().lower() == "true"
 
def bad_email(row):
    status = (row.get("Email Status") or "").strip().lower()
    if not norm_email(row.get("Email","")):
        return True
    if is_true(row.get("Email Bounced","")):
        return True
    # Apollo "good" statuses are verified / likely / new data available; treat these as NOT bad
    good = ("verified","likely","new data")
    if status and not any(g in status for g in good):
        return True
    return False
 
def stage_is_lost(row):
    s = (row.get("Stage") or "").strip().lower()
    return ("lost" in s) or ("do not" in s) or ("unqualif" in s) or ("bad" in s)
 
def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    outdir = sys.argv[2] if len(sys.argv) > 2 else "."
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    if not files:
        print("No CSV files found in", folder); return
 
    people = {}              # key -> merged record
    total_in = 0
    key_sources = defaultdict(set)   # key -> set of source files
 
    for path in files:
        fname = os.path.basename(path)
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                total_in += 1
                cid = (row.get("Apollo Contact Id") or "").strip()
                email = norm_email(row.get("Email",""))
                key = cid or email or f"__norow_{total_in}"   # prefer Apollo ID, then email
                key_sources[key].add(fname)
                if key not in people:
                    people[key] = dict(row)
                else:
                    # keep the most-complete / most-recently-contacted copy
                    old = people[key]
                    if (row.get("Last Contacted") or "") > (old.get("Last Contacted") or ""):
                        people[key] = dict(row)
 
    uniq = list(people.items())
 
    # ---- flag each unique person ----
    def flags_for(row):
        contacted = bool((row.get("Last Contacted") or "").strip()) or is_true(row.get("Email Sent",""))
        return {
            "flag_contacted_before": contacted,
            "flag_replied":          is_true(row.get("Replied","")),
            "flag_demoed":           is_true(row.get("Demoed","")),
            "flag_email_opened":     is_true(row.get("Email Open","")),
            "flag_bounced":          is_true(row.get("Email Bounced","")),
            "flag_closed_lost_or_dnc": stage_is_lost(row) or is_true(row.get("Do Not Call","")),
            "flag_no_phone":         not has_phone(row),
            "flag_bad_email":        bad_email(row),
        }
 
    # ---- write master ----
    os.makedirs(outdir, exist_ok=True)
    master_path = os.path.join(outdir, "safety_master_deduped.csv")
    base_cols = ["Apollo Contact Id","First Name","Last Name","Title","Company Name","Email",
                 "Email Status","Stage","Last Contacted","Corporate Phone","Mobile Phone","Lists"]
    flag_cols = ["flag_contacted_before","flag_replied","flag_demoed","flag_email_opened",
                 "flag_bounced","flag_closed_lost_or_dnc","flag_no_phone","flag_bad_email",
                 "flag_no_valid_contact","times_seen","source_lists"]
    with open(master_path,"w",newline="",encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(base_cols + flag_cols)
        counts = defaultdict(int)
        contactable_never = 0
        for key,row in uniq:
            fl = flags_for(row)
            fl["flag_no_valid_contact"] = fl["flag_bad_email"] and fl["flag_no_phone"]
            for k,v in fl.items():
                if v is True: counts[k]+=1
            # the gold number: valid contact, not lost, never contacted
            if (not fl["flag_no_valid_contact"] and not fl["flag_closed_lost_or_dnc"]
                    and not fl["flag_contacted_before"]):
                contactable_never += 1
            w.writerow([row.get(c,"") for c in base_cols] +
                       [fl["flag_contacted_before"],fl["flag_replied"],fl["flag_demoed"],
                        fl["flag_email_opened"],fl["flag_bounced"],fl["flag_closed_lost_or_dnc"],
                        fl["flag_no_phone"],fl["flag_bad_email"],fl["flag_no_valid_contact"],
                        len(key_sources[key]), " | ".join(sorted(key_sources[key]))])
 
    dups = sum(1 for k,s in key_sources.items() if len(s) > 1)
    # ---- summary ----
    print("="*58)
    print("  SAFETY LIST DEDUPE — SUMMARY")
    print("="*58)
    print(f"  Files processed............ {len(files)}")
    print(f"  Total rows read (raw)...... {total_in:,}")
    print(f"  REAL UNIQUE PEOPLE......... {len(uniq):,}")
    dropped = total_in-len(uniq)
    pct = (dropped/total_in*100) if total_in else 0
    print(f"  Duplicate rows collapsed... {dropped:,}  ({pct:.0f}% of raw)")
    print(f"  People on >1 source list... {dups:,}")
    print("-"*58)
    print("  FLAGS (count of unique people):")
    labels = {
      "flag_contacted_before":"  already contacted (emailed/touched)",
      "flag_replied":          "  replied",
      "flag_demoed":           "  demoed",
      "flag_email_opened":     "  opened an email",
      "flag_bounced":          "  email bounced",
      "flag_closed_lost_or_dnc":"  closed-lost / do-not-contact",
      "flag_no_phone":         "  no valid phone",
      "flag_bad_email":        "  bad / unverified email",
      "flag_no_valid_contact": "  NO valid contact data at all",
    }
    for k,lab in labels.items():
        print(f"   {counts[k]:>7,}  {lab}")
    print("-"*58)
    print(f"  >>> CONTACTABLE & NEVER WORKED: {contactable_never:,}")
    print("      (valid data, not lost, never contacted — the")
    print("       number that tests Alex's 'out of people' story)")
    print("="*58)
    print("  Master written to:", master_path)
 
if __name__ == "__main__":
    main()