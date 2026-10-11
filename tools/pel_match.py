import openpyxl, json, re, datetime, collections, sys
"""Match products.json against Ofgem's BUS Product Eligibility List.
Usage:  python3 tools/pel_match.py <path to BUS-external-PEL.xlsx> "<PEL page 'last updated' date>"
Writes bus-pel.json, which build.py reads. Re-run whenever Ofgem publishes a new PEL."""
import os
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEL=sys.argv[1]
PEL_DATE=sys.argv[2] if len(sys.argv)>2 else ''
PROD=os.path.join(ROOT,'products.json')
TODAY=datetime.datetime.now()
wb=openpyxl.load_workbook(PEL,read_only=True)
rows=[r for r in wb['PEL'].iter_rows(values_only=True)][2:]
rows=[r for r in rows if r and r[0]]
def norm(s): return re.sub(r'[^A-Z0-9*]','',str(s).upper())
def variants(tok):
    out={tok}
    while True:
        new=set()
        for t in out:
            m=re.search(r'\(([^()]*)\)',t)
            if m:
                new.add(t[:m.start()]+m.group(1)+t[m.end():]); new.add(t[:m.start()]+t[m.end():])
            else: new.add(t)
        if new==out: break
        out=new
    return out
SPLIT=re.compile(r'\s*(?:\+|,|;|&|\band\b|\bwith\b)\s*',re.I)
def tokens(s):
    s=str(s or '')
    s=re.sub(r'(?i)\b(indoor|outdoor|hydro\w*|cylinder|tank|unit|module|box)\b[: ]*','',s)
    toks=[]
    for t in SPLIT.split(s):
        t=t.strip()
        if not t: continue
        for v in variants(t):
            n=norm(v)
            if len(n)>=4: toks.append(n)
    return toks
def tokre(n):
    if '*' in n and len(n.replace('*',''))<5: return 'skip'
    if '*' in n: return re.compile('^'+re.escape(n).replace(r'\*','[A-Z0-9]{0,4}')+'$')
    return None
pel=[]
exact=collections.defaultdict(list); wild=[]
for r in rows:
    cert,tech,name,model,mfr,frm,until=r[:7]
    if tech and 'biomass' in str(tech).lower(): continue
    valid = until is None or (isinstance(until,datetime.datetime) and until>=TODAY)
    e=dict(cert=str(cert).strip(),tech=tech,name=name,model=model,mfr=mfr,until=until.date().isoformat() if isinstance(until,datetime.datetime) else None,valid=valid)
    idx=len(pel); pel.append(e)
    toks=set(tokens(model))|set(tokens(name))
    full={norm(v) for s in (model,name) for v in variants(str(s or '').strip().rstrip(','))}
    e['toks']=toks|full
    for t in e['toks']:
        rx=tokre(t)
        if rx=='skip': continue
        if rx: wild.append((rx,idx))
        else: exact[t].append(idx)
GENERIC=re.compile(r'^\d+(KW|K|L|LTR)?$|^(MONOBLOC|SPLIT|STANDARD)$')
def lookup(n):
    if len(n)<5 or GENERIC.match(n) or not re.search(r'\d',n): return set()
    hits=set(exact.get(n,[]))
    for rx,i in wild:
        if rx.match(n): hits.add(i)
    return hits
prods=json.load(open(PROD))
res={}
for p in prods:
    codes=[p.get('product_code')]+(p.get('aliases') or [])
    codes=[c for c in codes if c and str(c).strip() and str(c)!='None']
    hits=set()
    for c in codes:
        n=norm(c)
        if len(n)>=4: hits|=lookup(n)
        parts=[norm(x) for x in SPLIT.split(str(c)) if len(norm(x))>=4]
        if len(parts)>1:
            sets=[lookup(x) for x in parts]
            hits|=set.intersection(*sets)
    method='code'
    if not hits and p.get('mcs_cert'):
        cn=norm(p['mcs_cert'])
        hits={i for i,e in enumerate(pel) if norm(e['cert'])==cn}
        method='cert'
    if hits:
        allc={norm(c) for c in codes}
        hs=sorted([pel[i] for i in hits],key=lambda e:(not (allc & e['toks']), e['cert']))
        val=[h for h in hs if h['valid']]
        res[p['id']]=dict(status='eligible' if val else 'expired',
            cert=(val or hs)[0]['cert'],until=max([h['until'] or '9999' for h in (val or hs)]),
            pel_model=(val or hs)[0]['model'],pel_mfr=(val or hs)[0]['mfr'],pel_name=(val or hs)[0]['name'],tech=(val or hs)[0]['tech'],n=len(hs),method=method)
out={"pel_file":os.path.basename(PEL),"pel_updated":PEL_DATE,"matched_on":TODAY.strftime('%Y-%m-%d'),
     "items":{str(k):{"cert":v["cert"],"until":(None if v["until"] in (None,"9999") else v["until"]),
                      "pel_model":v["pel_model"],"method":v["method"]} for k,v in res.items() if v["status"]=="eligible"}}
json.dump(out,open(os.path.join(ROOT,'bus-pel.json'),'w'),indent=1,ensure_ascii=False)
print(f"{len(pel)} PEL rows; {len(out['items'])} products matched -> bus-pel.json")
