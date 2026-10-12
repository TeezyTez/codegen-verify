import json,re,sys
from pathlib import Path
sys.path.insert(0,r"C:/Users/16039/.codex/skills/citation-management/scripts")
from _common import parse_bibtex
p=Path(__file__).resolve().parent
text=(p/"references.bib").read_text(encoding="utf-8")
entries=parse_bibtex(text)
audit=json.loads((p/"citation_audit.json").read_text(encoding="utf-8"))["records"]
errors=[]
def check(ok,msg):
    if not ok: errors.append(msg)
check(len(entries)==9,"expected nine bibliography records")
check(len(audit)==9,"expected nine audit records")
check(len({x["key"] for x in entries})==9,"duplicate bibkey")
check(len({x["fields"]["doi"].lower() for x in entries})==9,"duplicate DOI")
check(text.count("{")==text.count("}"),"unbalanced brace total")
for e,a in zip(entries,audit):
    for f in ("author","title","year","url","doi","urldate"):
        check(bool(e["fields"].get(f)),e["key"]+": missing "+f)
    check(e["key"]==a["bibkey"],"key mismatch "+e["key"])
    check(e["fields"]["doi"]==a["doi"],"DOI mismatch "+e["key"])
    check(bool(re.fullmatch(r"20\d\d",e["fields"]["year"])),"invalid year")
    check(a["human_verification"]["state"]=="pending" and a["human_verification"]["verified_by"] is None,"fabricated human state")
    check(bool(a["locator"] and a["supported_claim"]),"missing support locator")
result={"validator":"local metadata/BibTeX structural and manifest consistency check","date":"2026-10-12","total_entries":len(entries),"errors":errors,"passed":not errors,
"human_verification":"pending for all nine records",
"limitations":["Bundled validate_citations.py could not start: requests module unavailable in both bundled Python and project venv.","No package installation performed.","This local check does not independently resolve DOI URLs, certify scientific support, or replace human review."],
"doi_verification":"Values extracted from original arXiv records and author/publisher metadata; no Crossref API resolution succeeded."}
(p/"validation_report.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps(result))
sys.exit(bool(errors))

