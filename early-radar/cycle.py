"""One scan cycle for the 24h trial. Fail-closed. Logs cycle result, source latency, outcomes. Telegram via env TG_BOT_TOKEN / TG_CHAT_ID (never logged)."""
import os,json,time,sqlite3,urllib.request,urllib.parse,sys
import radar
from radar import *
def tg_send(c,mint,text):
    tok=os.environ.get("TG_BOT_TOKEN");chat=os.environ.get("TG_CHAT_ID")
    if not tok or not chat:
        c.execute("insert into alerts values(?,?,?,?,?,?)",(utc(),mint,"TG_ATTEMPT","telegram",0,"NOT_CONFIGURED: secrets missing"));c.commit();return False
    try:
        d=urllib.parse.urlencode({"chat_id":chat,"text":text[:3500],"disable_web_page_preview":"true"}).encode()
        r=json.loads(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage",d,timeout=15).read())
        ok=bool(r.get("ok"));mid=(r.get("result") or {}).get("message_id")
        c.execute("insert into alerts values(?,?,?,?,?,?)",(utc(),mint,"TG_ATTEMPT","telegram",1 if ok else 0,f"ok={ok} message_id={mid}"));c.commit();return ok
    except Exception as e:
        c.execute("insert into alerts values(?,?,?,?,?,?)",(utc(),mint,"TG_ATTEMPT","telegram",0,f"error={type(e).__name__}"));c.commit();return False
def init(c):
    c.executescript("""create table if not exists cycles(start,end,ok,new_events,decisions,qualified,error,max_src_latency_ms,non200);
    create table if not exists outcomes(mint,entry_ts,entry_price,price_15m,price_1h,price_6h,max_price,min_price,liq_entry,note);""")
def track_outcomes(c):
    now=time.time()
    for mint,ets,ep,p15,p1,p6,mx,mn in c.execute("select mint,entry_ts,entry_price,price_15m,price_1h,price_6h,max_price,min_price from outcomes").fetchall():
        age=now-dt.datetime.fromisoformat(ets).timestamp()
        mk=market(c,mint)
        if mk["status"]!="OK" or not mk.get("price_usd"): continue
        p=float(mk["price_usd"])
        c.execute("update outcomes set max_price=max(coalesce(max_price,0),?),min_price=min(coalesce(min_price,1e99),?) where mint=?",(p,p,mint))
        for col,th in(("price_15m",900),("price_1h",3600),("price_6h",21600)):
            if age>=th and c.execute(f"select {col} from outcomes where mint=?",(mint,)).fetchone()[0] is None:
                c.execute(f"update outcomes set {col}=? where mint=?",(p,mint))
        c.commit()
def main():
    c=db();init(c);st=utc();err=None;ok=1;rows=[];new=0
    try:
        feeds,new,rows=radar.run(limit=int(os.environ.get("SCAN_LIMIT","15")))
        if any(f.get("status")!=200 for f in feeds.values()): ok=0;err="feed_failure:"+",".join(k for k,f in feeds.items() if f.get("status")!=200)
        for r in rows:
            if r["state"]=="QUALIFIED CANDIDATE" and r["alert"]=="LOGGED":
                mk=market(c,r["mint"]);c.execute("insert into outcomes values(?,?,?,?,?,?,?,?,?,?)",(r["mint"],utc(),mk.get("price_usd"),None,None,None,mk.get("price_usd"),mk.get("price_usd"),mk.get("liq_usd"),"post-launch detection; paper reference only"))
                body=c.execute("select detail from alerts where mint=? and kind='QUALIFIED CANDIDATE'",(r["mint"],)).fetchone()[0]
                tg_send(c,r["mint"],"EARLY RADAR (paper/test, not advice)\n"+body+f"\nliq=${mk.get('liq_usd')} detected={utc()}")
        track_outcomes(c)
    except Exception as e: ok=0;err=type(e).__name__+":"+str(e)[:120]
    q=sum(1 for r in rows if r["state"]=="QUALIFIED CANDIDATE")
    mx,n2=c.execute("select max(latency_ms),sum(status!=200) from requests where ts>=?",(st,)).fetchone()
    c.execute("insert into cycles values(?,?,?,?,?,?,?,?,?)",(st,utc(),ok,new,len(rows),q,err,mx,n2));c.commit()
    print(json.dumps({"start":st,"ok":ok,"new":new,"decisions":len(rows),"qualified":q,"err":err,"max_latency_ms":mx,"non200":n2}))
if __name__=="__main__": main()
