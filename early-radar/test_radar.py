import json,time,os,sqlite3,radar
from radar import *
R=[]
def T(name,cond,ev): R.append((name,"PASS" if cond else "FAIL",ev));print(("PASS" if cond else "FAIL"),name,"|",ev)
os.path.exists("test.db") and os.remove("test.db"); radar.DB="test.db"; c=db()
OK=lambda n:chk(n,"PASS","fixture","fx")
good=[OK("mint_authority"),OK("freeze_authority"),OK("rugcheck_risks")]
mk={"status":"OK","liq_usd":20000,"pair_age_h":2,"fetched_at":utc()}
M="So11111111111111111111111111111111111111112"
# B/mint validation
T("B1 valid mint accepted",b58_valid(M),M)
T("B2 invalid mints rejected",not any(b58_valid(x) for x in["abc","0OIl"*10,"","x"*50,None,"So1111111111111111111111111111111111111111"]),"6 bad inputs")
T("B3 link refused for bad mint",link_ok("abc","gmgn") is None and link_ok(M,"gmgn").endswith(M),"link_ok")
# dedupe
a=ingest(c,"fx","1",M,None,"u",{});b=ingest(c,"fx","1",M,None,"u",{})
T("B4 idempotent ingest",a and not b,"second insert ignored")
# D/E decisions
s,r=decide(M,good,mk);T("E1 all pass -> QUALIFIED w/ reasons",s=="QUALIFIED CANDIDATE" and len(r)>=3,r)
s,r=decide(M,[chk("mint_authority","FAIL","mintAuthority=X","fx")]+good[1:],mk);T("D1 critical FAIL -> SECURITY REJECTED",s=="SECURITY REJECTED",r)
s,r=decide(M,[chk("freeze_authority","UNKNOWN","rpc down","fx")]+good,mk);T("D2 UNKNOWN critical -> DATA INCOMPLETE",s=="DATA INCOMPLETE",r)
s,r=decide(M,good,{"status":"NO_PAIR","reason":"none"});T("D3 no pair -> DATA INCOMPLETE",s=="DATA INCOMPLETE",r)
s,r=decide(M,good,mk,age_s=500);T("D4 stale market -> DATA INCOMPLETE",s=="DATA INCOMPLETE",r)
s,r=decide(M,good,dict(mk,liq_usd=100));T("D5 low liq -> LIQUIDITY INSUFFICIENT",s=="LIQUIDITY INSUFFICIENT",r)
s,r=decide(M,good,dict(mk,pair_age_h=200));T("D6 old pair -> SIGNAL EXPIRED",s=="SIGNAL EXPIRED",r)
s,r=decide("bad",good,mk);T("D7 invalid mint -> DATA INCOMPLETE",s=="DATA INCOMPLETE",r)
s,r=decide(M,[chk("mint_authority","FAIL","x","fx")],dict(mk,liq_usd=10**9));T("D8 huge liquidity cannot override security FAIL",s=="SECURITY REJECTED",s)
# F alert + dedupe
x=alert(c,M,"QUALIFIED CANDIDATE",["r"],mk);y=alert(c,M,"QUALIFIED CANDIDATE",["r"],mk)
T("F1 alert logged then deduped",x=="LOGGED" and y=="DEDUPED",(x,y))
body=c.execute("select detail from alerts").fetchone()[0];T("F2 alert has reasons+valid links",M in body and "dexscreener.com/solana/"+M in body,body.replace("\n"," | "))
# A: failure handling
radar.CFG["deadline_s"]=2;radar.CFG["retries"]=1
t=time.time();j,m=fetch(c,"bad_host","https://nonexistent.invalid/x");T("A1 DNS failure -> None, error recorded, bounded",j is None and m["error"] and time.time()-t<12,m)
j,m=fetch(c,"http404","https://api.dexscreener.com/nope-nothing");T("A2 404 not retried, reported",j is None and m["status"]==404 and m["attempts"]==1,m)
j,m=fetch(c,"geckoterminal_429","https://api.geckoterminal.com/api/v2/networks/solana/new_pools")
for _ in range(8): j,m=fetch(c,"geckoterminal_429","https://api.geckoterminal.com/api/v2/networks/solana/new_pools")
T("A3 rate-limit 429 retried w/ backoff then reported (real GT limit)",j is None and m["status"]==429 and m["attempts"]==2,m)
n=c.execute("select count(*) from requests where attempt>1").fetchone()[0];T("A4 retry attempts logged",n>=1,f"{n} retry rows")
# A: outage injection through security()/market()
radar.CFG["retries"]=0
orig=radar.fetch
radar.fetch=lambda *a,**k:(None,{"status":0,"latency_ms":1,"error":"injected_outage","fetched_at":utc(),"attempts":1})
chs=security(c,M);mm=market(c,M);radar.fetch=orig
s,r=decide(M,chs,mm);T("A5 total provider outage -> DATA INCOMPLETE, no signal",s=="DATA INCOMPLETE" and all(x["status"]=="UNKNOWN" for x in chs),r[:2])
# live E2E on known real tokens
radar.CFG["retries"]=2;radar.CFG["deadline_s"]=10
chs=security(c,M);T("C1 live RPC authority check on wSOL runs",any(x["check"]=="mint_authority" for x in chs),[(x["check"],x["status"]) for x in chs])
mm=market(c,M);T("C2 live market fetch returns pair + liquidity + fetched_at",mm["status"]=="OK" and mm["liq_usd"] and mm["fetched_at"],{k:mm.get(k) for k in("status","liq_usd","pair_age_h","fetched_at")})
s,r=decide(M,chs,mm);T("E2 live wSOL not a fresh launch -> not QUALIFIED",s!="QUALIFIED CANDIDATE",(s,r[:1]))
print("\nSUMMARY",sum(1 for x in R if x[1]=="PASS"),"/",len(R),"PASS")
json.dump(R,open("test_results.json","w"),indent=1,default=str)
# STEP 3 holder/LP fixture tests via injected report
import radar as R_
def fake(rep):
    return lambda c,src,url,data=None,hdr=None:((json.loads(json.dumps(rep)),{"status":200,"latency_ms":1,"error":None,"fetched_at":utc(),"attempts":1}) if "report" in url else (json.loads(data and json.dumps({"result":{"value":{"owner":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA","data":{"parsed":{"type":"mint","info":{"mintAuthority":None,"freezeAuthority":None,"supply":"1000"}}}}}}) or None),{"status":200,"latency_ms":1,"error":None,"fetched_at":utc(),"attempts":1}))
base={"risks":[],"markets":[{"lp":{"base":500.0,"lpLockedPct":100,"lpLockedUSD":9000,"quoteUSD":9000}}],"topHolders":[{"pct":50,"uiAmount":500.0,"decimals":6},{"pct":5,"uiAmount":50},{"pct":3,"uiAmount":30}],"totalHolders":100,"lockers":{}}
def run_rep(rep):
    o=R_.fetch;R_.fetch=fake(rep);r={x["check"]:x["status"] for x in R_.security(c,M)};R_.fetch=o;return r
r=run_rep(base);T("S1 pool vault excluded, lp 100% -> holder PASS, lp PASS",r["holder_concentration"]=="PASS" and r["lp_lock"]=="PASS",r)
b2=json.loads(json.dumps(base));b2["topHolders"][1]["pct"]=40;r=run_rep(b2);T("S2 non-pool whale 40% -> holder FAIL",r["holder_concentration"]=="FAIL",r)
b3=json.loads(json.dumps(base));b3["markets"][0]["lp"]["lpLockedPct"]=0;r=run_rep(b3);T("S3 LP unlocked -> lp_lock FAIL",r["lp_lock"]=="FAIL",r)
b4=json.loads(json.dumps(base));del b4["markets"][0]["lp"]["lpLockedPct"];r=run_rep(b4);T("S4 lock data missing -> UNKNOWN (never assumed locked)",r["lp_lock"]=="UNKNOWN",r)
b5={"risks":[],"markets":[]};r=run_rep(b5);T("S5 no holder/market data -> both UNKNOWN",r["holder_concentration"]=="UNKNOWN" and r["lp_lock"]=="UNKNOWN",r)
chs=[chk("lp_lock","UNKNOWN","x","fx")]+good;s_,r_=decide(M,chs,mk);T("S6 UNKNOWN lp_lock blocks signal",s_=="DATA INCOMPLETE",r_)
print("SUMMARY2",sum(1 for x in R if x[1]=="PASS"),"/",len(R));json.dump(R,open("test_results.json","w"),indent=1,default=str)
