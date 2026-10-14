#!/usr/bin/env python3
"""One-time lossless recovery of deployed but uncommitted divergent ledgers."""
import json,gzip,pathlib,urllib.request,zipfile,tarfile,io,os,hashlib,datetime
ROOT=pathlib.Path('radar-r2');MARK=ROOT/'recovery-20261014.json'
if MARK.exists():
 print('Recovery already committed; skip');raise SystemExit(0)
runs=[{'id': 38520368243, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38520368243'}, {'id': 38517396189, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38517396189'}, {'id': 38513902164, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38513902164'}, {'id': 38510522178, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38510522178'}, {'id': 38507425969, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38507425969'}, {'id': 38504530587, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38504530587'}, {'id': 38501836771, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38501836771'}, {'id': 38499020826, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38499020826'}, {'id': 38495348422, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38495348422'}, {'id': 38491925435, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38491925435'}, {'id': 38487492054, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38487492054'}, {'id': 38484896762, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38484896762'}, {'id': 38481887511, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38481887511'}, {'id': 38478789208, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38478789208'}, {'id': 38475112521, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38475112521'}, {'id': 38471444805, 'url': 'https://github.com/jegankumarthevar/sspl-dashboard/actions/runs/38471444805'}]
base=json.loads((ROOT/'server-ledger.json').read_text());basebudget=dict(base['engineState'].get('evidenceBudget',{}));
def compact(v):
 p=v['engineState']['autoPaper'];return {'events':v['events'],'processedRuns':v['processedRuns'],'lastRun':v['lastRun'],'engineState':{'autoPaper':p,'tokens':{o['mint']:v['engineState']['tokens'][o['mint']] for o in p['limitPolicy']['orders']}}}
versions=[compact(base)];del base;manifest=[];archive=ROOT/'recovery-archive';archive.mkdir(exist_ok=True)
def get(url):
 req=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Accept':'application/vnd.github+json'})
 return urllib.request.urlopen(req,timeout=60).read()
# Include any old-workflow runs that completed while repair files were being installed.
current=json.loads(get('https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs?per_page=100'))['workflow_runs']
runs=[{'id':r['id'],'url':r['html_url']} for r in current if r.get('path')=='.github/workflows/radar-server.yml' and r['created_at']>'2026-10-13T21:00:00Z' and str(r['id'])!=os.environ.get('GITHUB_RUN_ID') and r['status']=='completed']
for run in reversed(runs):
 rid=str(run['id']);arts=json.loads(get('https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+rid+'/artifacts'))['artifacts']
 art=next(a for a in arts if a['name']=='github-pages')
 z=zipfile.ZipFile(io.BytesIO(get(art['archive_download_url'])));t=tarfile.open(fileobj=io.BytesIO(z.read('artifact.tar')))
 m=next(m for m in t.getmembers() if m.name.endswith('radar-r2/server-ledger.json'));raw=t.extractfile(m).read();v=json.loads(raw)
 if v['lastRun']['id']!=rid:raise RuntimeError('Artifact/run mismatch '+rid)
 (archive/(rid+'.json.gz')).write_bytes(gzip.compress(raw,compresslevel=9,mtime=0));versions.append(compact(v))
 manifest.append({'run':rid,'url':run['url'],'artifactId':art['id'],'sha256':hashlib.sha256(raw).hexdigest(),'events':len(v['events'])})
p=v['engineState']['autoPaper'];events={};orders={};seen=[];processed=[];budgets={}
for old in versions:
 for e in old['events']:
  if e['id'] in events and e!=events[e['id']]:raise RuntimeError('Conflicting event '+e['id'])
  events[e['id']]=e
 for o in old['engineState']['autoPaper']['limitPolicy']['orders']:
  prev=orders.get(o['id']);rank={'PENDING':0,'FILLED':1,'EXPIRED':1}
  if prev and rank[o['status']]<rank[prev['status']]:continue
  orders[o['id']]=o
 for x in old['engineState']['autoPaper']['seen']:
  if x not in seen:seen.append(x)
 for x in old['processedRuns']:
  if x not in processed:processed.append(x)
 for o in old['engineState']['autoPaper']['limitPolicy']['orders']:
  if o['mint'] not in v['engineState']['tokens']:v['engineState']['tokens'][o['mint']]=old['engineState']['tokens'][o['mint']]
# Every divergent artifact has no fills/trades. Do not invent counterfactual fills.
if any(x['engineState']['autoPaper']['positions'] or x['engineState']['autoPaper']['trades'] for x in versions):raise RuntimeError('Unexpected fills require separate accounting recovery')
v['events']=sorted(events.values(),key=lambda e:(e['timestamp'],e['id']));p['limitPolicy']['orders']=list(orders.values());p['seen']=seen;v['processedRuns']=processed
budgets[basebudget.get('day')]=basebudget.get('used',0)
for x in versions[1:]:
 b=x['lastRun'].get('strictEvidence',{});day=b.get('day');budgets[day]=budgets.get(day,0)+b.get('runUsed',0)
day=datetime.datetime.now(datetime.timezone.utc).date().isoformat();b=v['engineState'].setdefault('evidenceBudget',{});b['day']=day;b['used']=budgets.get(day,0);b['total']=basebudget.get('total',0)+sum(x['lastRun'].get('strictEvidence',{}).get('runUsed',0) for x in versions[1:])
v['recovery']={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':'GitHub post-scan deployment artifacts','gap':'Pending orders were not carried forward after commit failures. No retroactive fills inferred.','originalIdsPreserved':True,'budgetsByDay':budgets,'runs':manifest}
MARK.write_text(json.dumps(v['recovery'],indent=2)+'\n');(ROOT/'server-ledger.json').write_text(json.dumps(v,separators=(',',':'))+'\n');(ROOT/'server-ledger.json.gz').write_bytes(gzip.compress(json.dumps(v,separators=(',',':')).encode(),compresslevel=9,mtime=0))
print(json.dumps({'events':len(v['events']),'orders':[(o['name'],o['status']) for o in p['limitPolicy']['orders']],'processedRuns':len(processed),'budgets':budgets}))
