"""Solana Early-Entry Radar MVP (STEP 2). Post-launch detection only. Free keyless sources. No wallets/keys/trades."""
import json,time,sqlite3,urllib.request,urllib.error,datetime as dt,hashlib
CFG={"max_top1_pct":30,"max_top10_pct":60,"min_lp_locked_pct":90,"min_liq_usd":5000,"max_market_age_s":120,"max_pair_age_h":24,"deadline_s":10,"retries":2}
DB="radar.db"
A58="123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TOKEN_PROGS={"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":"spl-token","TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb":"token-2022"}
def utc(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
def db():
    c=sqlite3.connect(DB)
    c.executescript("""create table if not exists requests(ts,source,url,status,latency_ms,attempt,error);
    create table if not exists events(id primary key,ts,source,source_id,mint,source_created_at,url,payload);
    create table if not exists decisions(ts,mint,state,score,reasons,checks);
    create table if not exists alerts(ts,mint,kind,channel,delivered,detail);""");return c
def b58_valid(s):
    if not isinstance(s,str) or not 32<=len(s)<=44 or any(ch not in A58 for ch in s): return False
    n=0
    for ch in s: n=n*58+A58.index(ch)
    b=n.to_bytes((n.bit_length()+7)//8,"big"); pad=len(s)-len(s.lstrip("1"))
    return len(b"\0"*pad+b)==32
def fetch(c,source,url,data=None,hdr=None):
    """A: bounded deadline, retry w/ backoff on 429/5xx/timeouts, every attempt logged. Returns (json|None, meta)."""
    h={"User-Agent":"Mozilla/5.0","Accept":"application/json"};h.update(hdr or {})
    last=None
    for a in range(1,CFG["retries"]+2):
        t=time.time();st=0;err=None;j=None
        try:
            r=urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h),timeout=CFG["deadline_s"]);st=r.status;j=json.loads(r.read())
        except urllib.error.HTTPError as e: st=e.code;err=f"http {e.code}"
        except Exception as e: err=type(e).__name__
        lat=int((time.time()-t)*1000)
        c.execute("insert into requests values(?,?,?,?,?,?,?)",(utc(),source,url[:120],st,lat,a,err));c.commit()
        last={"status":st,"latency_ms":lat,"error":err,"fetched_at":utc(),"attempts":a}
        if st==200 and j is not None: return j,last
        if st in(429,500,502,503,504,0) and a<=CFG["retries"]: time.sleep(1.5*a);continue
        break
    return None,last
def ingest(c,source,sid,mint,created,url,payload):
    eid=hashlib.sha256(f"{source}|{sid}".encode()).hexdigest()[:24]
    cur=c.execute("insert or ignore into events values(?,?,?,?,?,?,?,?)",(eid,utc(),source,sid,mint,created,url,json.dumps(payload)[:4000]));c.commit()
    return cur.rowcount==1
def discover(c):
    """B: detect launches from post-launch feeds. Stage label is LAUNCH DETECTED, never pre-launch."""
    out={};feeds={}
    j,m=fetch(c,"raydium_launchlab","https://launch-mint-v1.raydium.io/get/list?sort=new&size=20&mintType=default&platformId=PlatformWhiteList&includeNsfw=false");feeds["raydium_launchlab"]=m
    for r in ((j or {}).get("data") or {}).get("rows",[]):
        ca=r.get("createAt");out.setdefault(r["mint"],{"name":r.get("name"),"symbol":r.get("symbol"),"src":"raydium_launchlab","created":ca,"links":{"website":r.get("website"),"twitter":r.get("twitter"),"telegram":r.get("telegram")},"url":"https://raydium.io/launchpad/token/?mint="+r["mint"]})
    j,m=fetch(c,"dex_profiles","https://api.dexscreener.com/token-profiles/latest/v1");feeds["dex_profiles"]=m
    for r in (j or []):
        if r.get("chainId")=="solana": out.setdefault(r["tokenAddress"],{"name":None,"symbol":None,"src":"dex_profiles","created":None,"links":r.get("links"),"url":r.get("url")})
    j,m=fetch(c,"rugcheck_new","https://api.rugcheck.xyz/v1/stats/new_tokens");feeds["rugcheck_new"]=m
    for r in (j or []):
        out.setdefault(r["mint"],{"name":None,"symbol":r.get("symbol"),"src":"rugcheck_new","created":r.get("createAt"),"links":None,"url":"https://rugcheck.xyz/tokens/"+r["mint"]})
    new=0
    for mint,d in out.items():
        d["mint_format_valid"]=b58_valid(mint)
        if not d["mint_format_valid"]: continue
        new+=ingest(c,d["src"],mint,mint,d["created"],d["url"],d)
    return out,feeds,new
def chk(name,status,evidence,provider,critical=True,limits=""):
    return {"check":name,"status":status,"evidence":evidence,"provider":provider,"observed_at":utc(),"critical":critical,"limits":limits}
def security(c,mint):
    """C: independent checks. UNKNOWN allowed; never inferred PASS."""
    out=[]
    rpc=json.dumps({"jsonrpc":"2.0","id":1,"method":"getAccountInfo","params":[mint,{"encoding":"jsonParsed"}]}).encode()
    j,m=fetch(c,"solana_rpc","https://api.mainnet-beta.solana.com",rpc,{"Content-Type":"application/json"})
    v=((j or {}).get("result") or {}).get("value")
    if j is None: out+= [chk(n,"UNKNOWN",f"rpc unavailable {m['error']}","solana_rpc") for n in("mint_exists","mint_authority","freeze_authority")]
    elif v is None: out.append(chk("mint_exists","FAIL","account not found on chain","solana_rpc"))
    else:
        prog=TOKEN_PROGS.get(v.get("owner")); p=(v.get("data") or {}).get("parsed") or {}
        ok= prog and p.get("type")=="mint"
        out.append(chk("mint_exists","PASS" if ok else "FAIL",f"owner={v.get('owner')} type={p.get('type')}","solana_rpc"))
        if ok:
            i=p["info"]
            out.append(chk("mint_authority","PASS" if i.get("mintAuthority") is None else "FAIL",f"mintAuthority={i.get('mintAuthority')}","solana_rpc"))
            out.append(chk("freeze_authority","PASS" if i.get("freezeAuthority") is None else "FAIL",f"freezeAuthority={i.get('freezeAuthority')}","solana_rpc"))
            ext=i.get("extensions") or []
            names=[e.get("extension") for e in ext]
            BENIGN={"metadataPointer","tokenMetadata","immutableOwner"}
            RISKY={"transferFeeConfig","transferHook","permanentDelegate","defaultAccountState","nonTransferable","pausableConfig","confidentialTransferMint"}
            r=[n for n in names if n in RISKY];u=[n for n in names if n not in RISKY and n not in BENIGN]
            stt="FAIL" if r else ("UNKNOWN" if u else "PASS")
            out.append(chk("token_program",stt,f"{prog} extensions={names} risky={r} unreviewed={u}","solana_rpc",True,"risky extension list is a conservative config, not proof of malice"))
    j,m=fetch(c,"rugcheck",f"https://api.rugcheck.xyz/v1/tokens/{mint}/report")
    if j is None:
        for n in("rugcheck_risks","holder_concentration","lp_lock"): out.append(chk(n,"UNKNOWN",f"rugcheck unavailable {m['error']} status={m['status']}","rugcheck"))
        return out
    risks=j.get("risks") or [];bad=[r for r in risks if r.get("level") in("danger","critical")]
    out.append(chk("rugcheck_risks","FAIL" if bad else "PASS",f"danger risks={[r.get('name') for r in bad]} all={[r.get('name') for r in risks]}","rugcheck",True,"single third-party scanner; not proof of safety"))
    mk=[x for x in (j.get("markets") or []) if isinstance(x.get("lp"),dict)]
    pools=[float(x["lp"]["base"]) for x in mk if x["lp"].get("base") is not None]
    hs=j.get("topHolders")
    if not hs: out.append(chk("holder_concentration","UNKNOWN","no topHolders in report","rugcheck"))
    else:
        real=[h for h in hs if not any(abs(float(h.get("uiAmount") or 0)-p)<=0.01*max(p,1) for p in pools)]
        t1=real[0]["pct"] if real else 0;t10=sum(h["pct"] for h in real[:10]);ins=sum(h["pct"] for h in hs if h.get("insider"))
        bad_h=t1>CFG["max_top1_pct"] or t10>CFG["max_top10_pct"]
        out.append(chk("holder_concentration","FAIL" if bad_h else "PASS",f"top1={t1:.1f}% top10={t10:.1f}% (pool vaults excluded: {len(hs)-len(real)}), insider-flagged={ins:.1f}%, holders={j.get('totalHolders')}","rugcheck",True,"pool-vault exclusion matched by reserve amount; scanner top-holder list only; wallet clustering not verified"))
    if not mk: out.append(chk("lp_lock","UNKNOWN","no market/LP data in report","rugcheck"))
    else:
        best=max(mk,key=lambda x:x["lp"].get("lpLockedUSD") or x["lp"].get("quoteUSD") or 0)["lp"]
        pct=best.get("lpLockedPct")
        if pct is None: out.append(chk("lp_lock","UNKNOWN","lpLockedPct missing","rugcheck"))
        else: out.append(chk("lp_lock","PASS" if pct>=CFG["min_lp_locked_pct"] else "FAIL",f"lpLockedPct={pct} lockedUSD={best.get('lpLockedUSD')} lockers={(list(j['lockers'].keys())[:2] if isinstance(j.get('lockers'),dict) else (len(j['lockers']) if isinstance(j.get('lockers'),list) else None))}","rugcheck",True,"lock/burn as reported by RugCheck; not independently verified on-chain; unlock dates unknown"))
    return out
def market(c,mint):
    j,m=fetch(c,"dex_pairs",f"https://api.dexscreener.com/latest/dex/tokens/{mint}")
    if j is None: return {"status":"UNKNOWN","reason":f"dexscreener unavailable {m['error']}","fetched_at":m["fetched_at"]}
    ps=[p for p in (j.get("pairs") or []) if p.get("chainId")=="solana" and (p.get("baseToken") or {}).get("address")==mint]
    if not ps: return {"status":"NO_PAIR","reason":"no Solana pair for this mint on Dexscreener","fetched_at":m["fetched_at"]}
    p=max(ps,key=lambda x:(x.get("liquidity") or {}).get("usd") or 0)
    age_h=(time.time()*1000-p["pairCreatedAt"])/3.6e6 if p.get("pairCreatedAt") else None
    return {"status":"OK","fetched_at":m["fetched_at"],"fetch_age_s":0,"liq_usd":(p.get("liquidity") or {}).get("usd"),"price_usd":p.get("priceUsd"),"fdv":p.get("fdv"),"pair_age_h":age_h,"pair":p.get("pairAddress"),"dex":p.get("dexId"),"txns_h1":(p.get("txns") or {}).get("h1"),"url":p.get("url")}
def link_ok(mint,kind):
    if not b58_valid(mint): return None
    return {"dexscreener":f"https://dexscreener.com/solana/{mint}","gmgn":f"https://gmgn.ai/sol/token/{mint}"}[kind]
def decide(mint,checks,mkt,age_s=0):
    """D+E: hard gates first; reasons always; default NO signal."""
    R=[];st=None
    if not b58_valid(mint): return "DATA INCOMPLETE",["invalid mint format"]
    fails=[x for x in checks if x["status"]=="FAIL" and x["critical"]]
    unk=[x for x in checks if x["status"]=="UNKNOWN" and x["critical"]]
    if fails: return "SECURITY REJECTED",[f"{x['check']} FAIL: {x['evidence']}" for x in fails]
    if unk: return "DATA INCOMPLETE",[f"{x['check']} UNKNOWN: {x['evidence']}" for x in unk]
    if mkt["status"]!="OK": return "DATA INCOMPLETE",[f"market {mkt['status']}: {mkt.get('reason')}"]
    if age_s>CFG["max_market_age_s"]: return "DATA INCOMPLETE",[f"market data stale {age_s}s > {CFG['max_market_age_s']}s"]
    if (mkt["liq_usd"] or 0)<CFG["min_liq_usd"]: return "LIQUIDITY INSUFFICIENT",[f"liquidity ${mkt['liq_usd']} < ${CFG['min_liq_usd']}"]
    if mkt["pair_age_h"] is None or mkt["pair_age_h"]>CFG["max_pair_age_h"]: return "SIGNAL EXPIRED",[f"pair age {mkt['pair_age_h']} h > {CFG['max_pair_age_h']} h (not fresh launch)"]
    return "QUALIFIED CANDIDATE",["all critical security checks PASS","market verified","liquidity ok","fresh pair","NOT a prediction; post-launch detection only"]
def alert(c,mint,state,reasons,mkt):
    kind=state;
    if c.execute("select 1 from alerts where mint=? and kind=?",(mint,kind)).fetchone(): return "DEDUPED"
    body=f"{state} {mint}\n"+"; ".join(reasons)+f"\nDexscreener: {link_ok(mint,'dexscreener')}\nGMGN: {link_ok(mint,'gmgn')}"
    c.execute("insert into alerts values(?,?,?,?,?,?)",(utc(),mint,kind,"dashboard_log",1,body));c.commit()
    return "LOGGED"
def run(limit=15):
    c=db();out,feeds,new=discover(c);rows=[]
    import itertools
    bysrc={}
    for m,d in out.items(): bysrc.setdefault(d['src'],[]).append(m)
    order=[m for grp in itertools.zip_longest(*bysrc.values()) for m in grp if m]
    for mint in order[:limit]:
        if not out[mint].get("mint_format_valid"): continue
        t0=time.time()
        try: chs=security(c,mint)
        except Exception as e: chs=[chk('security_engine','UNKNOWN',f'unexpected provider shape: {type(e).__name__}','internal')]
        try: mk=market(c,mint)
        except Exception as e: mk={'status':'UNKNOWN','reason':f'market parse error {type(e).__name__}','fetched_at':utc()}
        age=int(time.time()-t0)
        st,rs=decide(mint,chs,mk,0)
        c.execute("insert into decisions values(?,?,?,?,?,?)",(utc(),mint,st,None,json.dumps(rs),json.dumps(chs)));c.commit()
        a=alert(c,mint,st,rs,mk) if st=="QUALIFIED CANDIDATE" else "n/a"
        rows.append({"mint":mint,"src":out[mint]["src"],"state":st,"reasons":rs,"liq":mk.get("liq_usd"),"alert":a})
    return feeds,new,rows
if __name__=="__main__":
    f,n,r=run();print(json.dumps({"feeds":f,"new_events":n},indent=1))
    from collections import Counter;print(Counter(x["state"] for x in r))
    for x in r: print(x["state"],x["mint"][:10],x["src"],x["liq"],x["reasons"][0][:90],x["alert"])
