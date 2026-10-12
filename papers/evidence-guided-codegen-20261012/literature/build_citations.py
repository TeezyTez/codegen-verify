"""Rebuild citations from saved public original-source tool responses; no network."""
import json,re,sys,hashlib
from pathlib import Path
sys.path.insert(0, r"C:/Users/16039/.codex/skills/citation-management/scripts")
from _common import parse_bibtex,render_entry
ROOT=Path(__file__).resolve().parent
raw=json.loads((ROOT/"raw/arxiv_bibtex_web_response.json").read_text(encoding="utf-8"))
clean=re.sub(r"L\d+: ?", "", raw)
entries={x["fields"].get("eprint"):x for x in parse_bibtex(clean)}
absraw=(ROOT/"raw/arxiv_abs_web.txt").read_text(encoding="utf-8")
blocks=[b.strip() for b in absraw.split("-"*80)] + [b.strip() for b in (ROOT/"raw/version_supplement_web.txt").read_text(encoding="utf-8").split("-"*80)]
fallback=(ROOT/"raw/metadata_fallback_web.txt").read_text(encoding="utf-8")
clover=parse_bibtex(re.sub(r"L\d+: ?", "",fallback.split("-"*80)[0]))[0]
clover["fields"].pop("abstract",None)
for k,v in clover["fields"].items():
    clover["fields"][k]=v.replace("â€“","--")
ids=["2406.08467","2310.17807","2512.18436","2601.05385","2608.09277","2608.29841","2603.25810","2609.00065","2606.32007"]
keys=["DafnyBench2024","Clover2024","VeruSAGE2026","DafnyPro2026","P32026","SkillForge2026","ExVerus2026","ScientificAgentSkills2026","AxDafny2026"]
details=json.loads((ROOT/"audit_annotations.json").read_text(encoding="utf-8"))
out=[]
for i,(id,key,ann) in enumerate(zip(ids,keys,details)):
    block=max((b for b in blocks if b.startswith("["+id+"]")),key=len)
    title=re.search(r"L9: # Title:(.*)",block).group(1).strip()
    authline=re.search(r"L11: Authors:(.*)",block).group(1)
    authors=re.findall(r"†([^†\ue201]+)\ue201",authline)
    # Extract the labels of original arXiv author links, excluding tool marker syntax.
    authors=re.findall(r"†([^\ue201]+)\ue201",authline)
    assert authors and all("cite" not in a for a in authors),(id,authors)
    version=re.search(r"arXiv:"+re.escape(id)+r"(v\d+)",block).group(1)
    doi=re.search(r"https://doi.org/(10\.48550/arXiv\."+re.escape(id)+")",block).group(1)
    submission=re.search(r"\[Submitted on ([^\](]+)",block).group(1).strip()
    source=f"https://arxiv.org/bibtex/{id}"
    if id not in entries:
        entries[id]={"type":"misc","key":key,"fields":{"title":title,"author":" and ".join(authors),"year":"2026","eprint":id,"archiveprefix":"arXiv","url":"https://arxiv.org/abs/"+id}}
        source="arXiv abstract metadata parsed from raw/arxiv_abs_web.txt; BibTeX export unavailable"
    ent=entries[id]
    if id=="2310.17807":
        ent=clover
        source="author-provided BibTeX from https://web.stanford.edu/~chuyues/files/clover.html; Springer publication fields cross-check"
    ent["key"]=key
    ent["fields"]["urldate"]="2026-10-12"
    if id!="2310.17807": ent["fields"]["doi"]=doi
    # Whole title protection preserves Dafny/LLM/Verus/P3 casing.
    ent["fields"]["title"]="{"+ent["fields"]["title"]+"}"
    out.append(render_entry(ent["type"],key,ent["fields"]))
    ann.update({"evidence_id":f"E{101+i}","bibkey":key,"arxiv_id":id,"title":title,"authors":authors,
      "year":int(ent["fields"]["year"]),"first_submission_date":submission,"arxiv_version_opened":version,
      "url":ent["fields"]["url"],"arxiv_url":"https://arxiv.org/abs/"+id,"doi":ent["fields"]["doi"],
      "accessdate":"2026-10-12","metadata_extraction":source,
      "machine_verification":{"state":"metadata_and_targeted_source_locators_checked","by":"Codex citation subagent","date":"2026-10-12","scope":"Original metadata and selected claim-support passages; no replication or exhaustive full-paper review"},
      "human_verification":{"state":"pending","verified_by":None,"verified_at":None},
      "verification_status":"pending","confidentiality":"public","retraction_check":"No withdrawal/correction notice seen in opened arXiv record; no exhaustive retraction-database search",
      "unavailable_fields":"For arXiv-only cited versions, volume/pages/issue/publisher DOI not asserted."})
    assert all(a in ent["fields"]["author"] or id=="2310.17807" for a in authors),(id,authors)
(ROOT/"references.bib").write_text("% Generated from original-source metadata; human scientific verification remains pending.\n\n"+"\n\n".join(out)+"\n",encoding="utf-8")
audit={"accessdate":"2026-10-12","review_type":"targeted narrative literature check, not a systematic review",
"verification_policy":"Machine access/metadata checking is not accountable human verification. All sources remain human pending.",
"records":details}
(ROOT/"citation_audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
rows=["# 公开文献核验台账\n","访问日期：2026-10-12。定向叙述性核验，不是系统综述。机器已检查元数据与所列窄范围支持位置；所有文献仍待具名人类复核。\n",
"| Evidence ID | Bibkey | 文献与年份 | 已打开版本 | 出版状态 |","|---|---|---|---|---|"]
for a in details:
    rows.append(f'| {a["evidence_id"]} | {a["bibkey"]} | [{a["title"]}]({a["arxiv_url"]}), {a["year"]} | {a["arxiv_version_opened"]} | {a["publication_state"]} |')
for a in details:
    rows.extend(["",f'## {a["evidence_id"]}: {a["title"]}',"",
       "- 作者："+ "; ".join(a["authors"]),
       "- 支持命题："+a["supported_claim"],
       "- 定位："+a["locator"],
       "- 不可推出："+a["does_not_support"],
       "- 实际打开程度："+a["opened_extent"],
       "- 交叉核验："+a["crosscheck"],
       "- 限制："+a["caveats"],
       "- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。"])
(ROOT/"citation_audit.md").write_text("\n".join(rows)+"\n",encoding="utf-8")
manifest=[]
for p in sorted((ROOT/"raw").glob("*")):
    manifest.append({"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"bytes":p.stat().st_size})
(ROOT/"raw_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"entries":len(out),"records":len(details),"human_pending":sum(x["human_verification"]["state"]=="pending" for x in details),"keys":keys}))

