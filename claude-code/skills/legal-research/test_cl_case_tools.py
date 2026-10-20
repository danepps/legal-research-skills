#!/usr/bin/env python3
"""Offline tests for cl_case_tools.py's pure helpers (no network): court-level
classification, party-word extraction, name queries and phrases, docket-entry
history flags, docket-number cores, deduplication, SCOTUS-cite detection."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("clt", os.path.join(HERE, "cl_case_tools.py"))
clt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clt)

fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


# court levels
for cid, want in [("scotus", "scotus"), ("ca1", "circuit"), ("cadc", "circuit"), ("cafc", "circuit"),
                  ("mad", "district"), ("cand", "district"), ("nysd", "district"), ("dcd", "district"),
                  ("innd", "district"), ("mab", "bankruptcy"), ("nysb", "bankruptcy"),
                  ("ind", "state"), ("md", "state"), ("tex", "state"), ("calctapp", "state"), ("", "unknown")]:
    check(f"court_level {cid!r} -> {want}", clt.court_level(cid) == want)
check("circuit reviews district", clt.above("district", "ca1") is True)
check("scotus reviews district", clt.above("district", "scotus") is True)
check("district reviews bankruptcy", clt.above("bankruptcy", "mad") is True)
check("another district does not review a district", clt.above("district", "nysd") is False)
check("only scotus reviews a circuit", clt.above("circuit", "scotus") and not clt.above("circuit", "ca2"))
check("state origin: no federal chain", clt.above("state", "scotus") is False)

# party words / queries / phrases
n = "Students for Fair Admissions, Inc. v. President and Fellows of Harvard College"
check("party_words drops noise and keeps order", clt.party_words(n) == [["Students", "Fair"], ["Harvard", "College"]])
check("party_keys one distinctive word per side", clt.party_keys(n) == ["Students", "Harvard"])
check("name_query ANDs caseName words", clt.name_query(n) == "caseName:Students AND caseName:Harvard")
ph = clt.name_phrases(n)
check("name_phrases: full name first", ph[0] == n)
check("name_phrases: ampersand variant", "President & Fellows" in ph[1])
check("name_phrases: short form", ph[-1] == "Students v. Harvard")
check("name_phrases: Fought short form", clt.name_phrases("Fought v. City of Wilkes-Barre") == ["Fought v. City of Wilkes-Barre", "Fought v. Wilkes-Barre"])
check("In re caption has no sides", clt.name_query("In re Brayden Crook") == "caseName:Brayden")
check("empty name", clt.name_phrases("") == [] and clt.party_keys("") == [])

# history flags on docket-entry text
check("mandate flagged", "mandate" in clt.flag_entry("MANDATE of USCA as to 674 Notice of Appeal filed by SFFA. Appeal 674 Terminated"))
check("notice of appeal flagged", clt.flag_entry("NOTICE OF APPEAL 672 FINDINGS OF FACT by Students") == ["notice_of_appeal"])
check("cert granted flagged", set(clt.flag_entry("Order from the Supreme Court of the United States: The petition for a writ of certiorari is granted.")) >= {"appealed_to_supreme_court", "cert_granted"})
check("cert denied flagged", "cert_denied" in clt.flag_entry("Supreme Court order: certiorari denied"))
check("amended opinion flagged", "amended_or_substituted_opinion" in clt.flag_entry("ORDER re motion (Attachments: # 1 Amended Opinion)"))
check("errata flagged", "amended_or_substituted_opinion" in clt.flag_entry("ERRATA to opinion"))
check("Rule 59 flagged as reconsideration", "reconsideration" in clt.flag_entry("MOTION to Alter or Amend Judgment under Rule 59(e)"))
check("vacated and remanded flagged", {"vacated", "remanded"} <= set(clt.flag_entry("USCA JUDGMENT: VACATED and REMANDED")))
check("notice of appearance is routine", clt.flag_entry("NOTICE of Withdrawal of Appearance by Felicia H. Ellsworth") == [])
check("pro hac vice is routine", clt.flag_entry("MOTION for Leave to Appear Pro Hac Vice; mandate fee paid") == [])
check("plain scheduling order unflagged", clt.flag_entry("ELECTRONIC ORDER entered: scheduling conference set") == [])
check("attachments parenthetical extracted", clt.attachments_of("ORDER (Attachments: # 1 Amended Opinion, # 2 Errata) (x)") == "# 1 Amended Opinion, # 2 Errata")
check("no attachments -> empty", clt.attachments_of("ORDER entered") == "")

# docket number cores
for raw, want in [("Civil Action No. 14-cv-14176-ADB", "14-cv-14176"), ("1:14-cv-14176", "14-cv-14176"),
                  ("4:20-cr-00123-ABC", "20-cr-00123"), ("No. 2:19-cv-1234", "19-cv-1234"), ("19-2005P", None), ("", None)]:
    check(f"docket_core {raw!r} -> {want!r}", clt.docket_core(raw) == want)

# dedupe + scotus detection
rows = [{"cluster_id": 1, "case": "A v. B", "date": "2020"}, {"cluster_id": 1, "case": "A v. B (dissent)", "date": "2020"},
        {"cluster_id": None, "case": "C v. D", "date": "2021"}, {"cluster_id": None, "case": "c v d", "date": "2021"},
        {"cluster_id": 2, "case": "E v. F", "date": "2022"}]
check("dedupe_rows: by cluster id, then by name+date", [r["case"] for r in clt.dedupe_rows(rows)] == ["A v. B", "C v. D", "E v. F"])
check("is_scotus_cite U.S.", clt.is_scotus_cite("600 U.S. 181") and clt.is_scotus_cite("143 S. Ct. 2141") and clt.is_scotus_cite("216 L. Ed. 2d 857"))
check("is_scotus_cite lower", not clt.is_scotus_cite("980 F.3d 157") and not clt.is_scotus_cite("397 F. Supp. 3d 126"))
check("signals scan", clt.scan_signals("we conclude Roe was overruled by Dobbs and is no longer good law") == ["overruled", "no_longer_good_law"])

# merging a head (oldest-first) and a tail (newest-first) read of a long docket
head = [{"entry": 1, "date": "2017-06-02", "description": "ORDER a"}, {"entry": 2, "date": "2017-07-01", "description": "ORDER b"}]
tail = [{"entry": 9, "date": "2020-12-03", "description": "MANDATE of USCA"}, {"entry": 2, "date": "2017-07-01", "description": "ORDER b"}]
merged = clt.merge_entries(head, tail)
check("merge_entries: union in date order, no duplicate", [e["entry"] for e in merged] == [1, 2, 9])
check("merge_entries: empty tail is a no-op", clt.merge_entries(head, []) == head)

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
