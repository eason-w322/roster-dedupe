#!/usr/bin/env python3
"""
BLCK UNICRN - Safety list dedupe + flag tool (Week 3, Job 2).
 
Unions every Apollo CSV export in a folder, removes duplicate people
(same person = same Apollo Contact Id, or same email if no id),
KEEPS EVERY ORIGINAL COLUMN, and appends flag columns on the right.
Prints the real unique count plus a verification breakdown.
 
Flag rules are data-driven (tuned to the real Stage / Email Status
values seen across the 13 safety lists). See the sets below - these
are the judgment calls to defend.
 
Usage:  python3 dedupe_safety_lists.py  <folder_with_csvs>  [output_folder]
"""
import csv, sys, glob, os, re
from collections import defaultdict, Counter
 
csv.field_size_limit(10_000_000)
 
# ============================================================
#  JUDGMENT CALLS - the definitions behind every flag.
#  Values are matched case-insensitively and trimmed.
# ============================================================
 
# Email statuses we consider GENUINELY BAD (unreachable by email).
BAD_EMAIL_STATUSES = {
    "unavailable", "email no longer verified", "potentially invalid",
    "invalid", "do_not_mail", "abuse", "unknown",
}
# Emails that are plausible but NOT confirmed -> usable, but soft-flagged.
UNCONFIRMED_EMAIL_STATUSES = {
    "catch-all", "extrapolated", "user managed",
}
# Everything else (verified, valid, likely, new data available, ...) = good.
 
# Stages that mean a dead / off-limits deal (closed-lost).
# NOTE: "Unresponsive" is deliberately NOT here - worked-but-quiet is still live.
LOST_STAGES = {
    "do not contact", "not interested", "bad data", "do_not_mail", "abuse",
}
 
PHONE_COLS = ["Work Direct Phone","Home Phone","Mobile Phone",
              "Corporate Phone","Other Phone","Company Phone"]
 
# ---------- helpers ----------
def norm_email(s): return (s or "").strip().lower()
def is_true(v):    return (v or "").strip().lower() == "true"
 
def has_phone(row):
    for c in PHONE_COLS:
        v = (row.get(c) or "").strip().strip("'").strip()
        if re.search(r"\d", v): return True
    return False
 
def email_bad(row):
    if not norm_email(row.get("Email","")):          return True   # no email at all
    if is_true(row.get("Email Bounced","")):         return True   # hard bounce
    return (row.get("Email Status") or "").strip().lower() in BAD_EMAIL_STATUSES
 
def email_unconfirmed(row):
    return (row.get("Email Status") or "").strip().lower() in UNCONFIRMED_EMAIL_STATUSES
 
def stage_is_lost(row):
    s = (row.get("Stage") or "").strip().lower()
    return s in LOST_STAGES
 
def flags_for(row):
    f = {
      "flag_contacted_before":   bool((row.get("Last Contacted") or "").strip()) or is_true(row.get("Email Sent","")),
      "flag_replied":            is_true(row.get("Replied","")),
      "flag_demoed":             is_true(row.get("Demoed","")),
      "flag_email_opened":       is_true(row.get("Email Open","")),
      "flag_bounced":            is_true(row.get("Email Bounced","")),
      "flag_closed_lost_or_dnc": stage_is_lost(row) or is_true(row.get("Do Not Call","")),
      "flag_no_phone":           not has_phone(row),
      "flag_bad_email":          email_bad(row),
      "flag_email_unconfirmed":  email_unconfirmed(row),   # usable, but not verified
    }
    f["flag_no_valid_contact"] = f["flag_bad_email"] and f["flag_no_phone"]
    return f
 
FLAG_COLS = ["flag_contacted_before","flag_replied","flag_demoed","flag_email_opened",
             "flag_bounced","flag_closed_lost_or_dnc","flag_no_phone","flag_bad_email",
             "flag_email_unconfirmed","flag_no_valid_contact","times_seen","source_lists"]
 
def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    outdir = sys.argv[2] if len(sys.argv) > 2 else "."
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    if not files:
        print("No CSV files found in", folder); return
 
    people = {}
    key_sources = defaultdict(set)
    all_cols = []; seen_cols = set(); total_in = 0
 
    for path in files:
        fname = os.path.basename(path)
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for c in (reader.fieldnames or []):
                if c not in seen_cols and c not in FLAG_COLS:
                    seen_cols.add(c); all_cols.append(c)
            for row in reader:
                total_in += 1
                cid = (row.get("Apollo Contact Id") or "").strip()
                key = cid or norm_email(row.get("Email","")) or f"__norow_{total_in}"
                key_sources[key].add(fname)
                if key not in people:
                    people[key] = dict(row)
                elif (row.get("Last Contacted") or "") > (people[key].get("Last Contacted") or ""):
                    people[key] = dict(row)
 
    uniq = list(people.items())
 
    os.makedirs(outdir, exist_ok=True)
    master_path = os.path.join(outdir, "safety_master_deduped.csv")
    counts = defaultdict(int)
    contactable_never = 0; contactable_never_confirmed = 0
    stage_vals = Counter(); email_status_vals = Counter()
 
    with open(master_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_cols + FLAG_COLS, extrasaction="ignore")
        w.writeheader()
        for key, row in uniq:
            fl = flags_for(row)
            for k, v in fl.items():
                if v is True: counts[k] += 1
            reachable = (not fl["flag_no_valid_contact"]) and (not fl["flag_closed_lost_or_dnc"])
            if reachable and not fl["flag_contacted_before"]:
                contactable_never += 1
                if not fl["flag_bad_email"] and not fl["flag_email_unconfirmed"]:
                    contactable_never_confirmed += 1
            stage_vals[(row.get("Stage") or "(empty)").strip()] += 1
            email_status_vals[(row.get("Email Status") or "(empty)").strip()] += 1
            out = dict(row)
            out.update({k: ("TRUE" if v else "FALSE") if isinstance(v, bool) else v
                        for k, v in fl.items()})
            out["times_seen"]   = len(key_sources[key])
            out["source_lists"] = " | ".join(sorted(key_sources[key]))
            w.writerow(out)
 
    dups = sum(1 for k, s in key_sources.items() if len(s) > 1)
    print("="*60)
    print("  SAFETY LIST DEDUPE - SUMMARY")
    print("="*60)
    print(f"  Files processed............ {len(files)}")
    print(f"  Original columns kept...... {len(all_cols)}  (+{len(FLAG_COLS)} flag cols)")
    print(f"  Total rows read (raw)...... {total_in:,}")
    print(f"  REAL UNIQUE PEOPLE......... {len(uniq):,}")
    dropped = total_in - len(uniq)
    print(f"  Duplicate rows collapsed... {dropped:,}  ({(dropped/total_in*100 if total_in else 0):.0f}% of raw)")
    print(f"  People on >1 source list... {dups:,}")
    print("-"*60)
    print("  FLAGS (count of unique people):")
    labels = {
      "flag_contacted_before":"already contacted (emailed/touched)",
      "flag_replied":"replied","flag_demoed":"demoed","flag_email_opened":"opened an email",
      "flag_bounced":"email bounced","flag_closed_lost_or_dnc":"closed-lost / do-not-contact",
      "flag_no_phone":"no valid phone","flag_bad_email":"bad / unreachable email",
      "flag_email_unconfirmed":"email usable but UNCONFIRMED (catch-all/extrapolated)",
      "flag_no_valid_contact":"NO valid contact data at all"}
    for k, lab in labels.items():
        print(f"   {counts[k]:>8,}  {lab}")
    print("-"*60)
    print(f"  >>> CONTACTABLE & NEVER WORKED......... {contactable_never:,}")
    print(f"      of which, on a CONFIRMED email..... {contactable_never_confirmed:,}")
    print(f"      (remainder reachable via unconfirmed emails)")
    print("-"*60)
    print("  VERIFY (distinct values actually seen):")
    print("  STAGE:")
    for v, n in stage_vals.most_common():
        print(f"     {n:>7,}  {v}")
    print("  EMAIL STATUS:")
    for v, n in email_status_vals.most_common():
        print(f"     {n:>7,}  {v}")
    print("="*60)
    print("  Master written to:", master_path)
 
if __name__ == "__main__":
    main()