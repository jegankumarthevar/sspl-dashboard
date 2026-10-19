#!/usr/bin/env python3
"""Bot B server-side snapshot job. Stdlib only, free public APIs, no keys, read-only, paper analysis only.
One run = one poll cycle. State lives in state.json, the app reads snapshot.json.
Every poll is recorded, including misses and failed sources. A gap is recorded when a run is late."""
import json,os,sys,time,urllib.request
DIR=os.path.dirname(os.path.abspath(__file__));STATE=os.path.join(DIR,'state.json');OUT=os.path.join(DIR,'snapshot.json')
STABLE={'So11111111111111111111111111111111111111112','EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v','Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'}
MAX_TRACK=300;TRACK_HOURS=24
def get(u):
    r=urllib.request.Request(u,headers={'User-Agent':'botb-snapshot','Accept':'application/json'})
    return json.load(urllib.request.urlopen(r,timeout=20))
def load():
    try:return json.load(open(STATE))
    except Exception:return {'tokens':{},'runs':0,'gaps':[],'last':None,'errors':[]}
def main():
    now=time.time();st=load();errs=[]
    st.setdefault('run_times',[])
    if st['last']:
        gap=now-st['last'];iv=[b-a for a,b in zip(st['run_times'][-21:],st['run_times'][-20:])]
        med=sorted(iv)[len(iv)//2] if iv else 300
        if gap>max(15*60,3*med):st['gaps'].append({'from':st['last'],'to':now,'min':round(gap/60),'median_prev_s':round(med)});st['gaps']=st['gaps'][-50:]
    try:
        for p in get('https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page=1')['data']:
            m=p['relationships']['base_token']['data']['id'].split('_')[1]
            if m in STABLE or m in st['tokens']:continue
            a=p['attributes'];st['tokens'][m]={'first':now,'name':a.get('name'),'p_first_seen':None,'liq_first_seen':None,'chunk_fail':0,'polls':0,'miss':0,'changes':0,'last':None,'max_valid':1.0,'liq':None,'price':None}
    except Exception as e:errs.append('gecko: '+str(e)[:80])
    cut=now-TRACK_HOURS*3600
    for m in [k for k,v in st['tokens'].items() if v['first']<cut]:del st['tokens'][m]
    if len(st['tokens'])>MAX_TRACK:
        for m in sorted(st['tokens'],key=lambda k:st['tokens'][k]['first'])[:len(st['tokens'])-MAX_TRACK]:del st['tokens'][m]
    ms=list(st['tokens'])
    for i in range(0,len(ms),30):
        chunk=ms[i:i+30];best={}
        try:
            for q in get('https://api.dexscreener.com/tokens/v1/solana/'+','.join(chunk)):
                m=q['baseToken']['address']
                if m in st['tokens'] and (m not in best or ((q.get('liquidity') or {}).get('usd') or 0)>((best[m].get('liquidity') or {}).get('usd') or 0)):best[m]=q
        except Exception as e:
            errs.append('dex chunk %d/%d: %s'%(i//30+1,(len(ms)+29)//30,str(e)[:80]))
            for m in chunk:st['tokens'][m]['polls']+=1;st['tokens'][m]['miss']+=1;st['tokens'][m]['chunk_fail']+=1
            continue
        for m in chunk:
            t=st['tokens'][m];t['polls']+=1;q=best.get(m)
            if q is None or not q.get('priceUsd'):t['miss']+=1;continue
            pr=float(q['priceUsd']);liq=(q.get('liquidity') or {}).get('usd') or 0
            if t['p_first_seen'] is None:t['p_first_seen']=pr;t['liq_first_seen']=liq
            if t['price'] is not None and pr!=t['price']:t['changes']+=1
            t['price']=pr;t['liq']=liq;t['last']=now
            if liq>=max(1000,0.2*(t['liq_first_seen'] or 0)) and t['p_first_seen']>0:t['max_valid']=max(t['max_valid'],pr/t['p_first_seen'])
    st['runs']+=1;st['last']=now;st['run_times']=(st['run_times']+[now])[-60:];st['errors']=(st['errors']+[{'t':now,'e':e} for e in errs])[-30:]
    json.dump(st,open(STATE,'w'))
    toks=[dict(mint=m,**{k:v[k] for k in ('name','first','p_first_seen','liq_first_seen','price','liq','polls','miss','chunk_fail','changes','max_valid','last')}) for m,v in st['tokens'].items()]
    json.dump({'schema':2,'run_times':st['run_times'],'engine':'Bot B snapshot','generated_at':now,'run':st['runs'],'interval_expected_min':5,'paper_only':True,'tokens':toks,'gaps':st['gaps'],'errors_this_run':errs,
      'note':'Multiples are relative to the first price THIS job observed (p_first_seen), not the pool creation price. max_valid counts only while liquidity stayed at least max($1000, 20% of the first observed liquidity). A static price over many polls means a thin pool, not stability.'},open(OUT,'w'))
    print('ok',len(toks),'tokens',len(errs),'errors')
if __name__=='__main__':main()
