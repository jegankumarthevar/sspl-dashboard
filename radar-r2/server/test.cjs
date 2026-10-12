'use strict';
const assert=require('node:assert/strict'),e=require('./engine.cjs'),r=require('./runner.cjs');let count=0;function t(name,fn){fn();count++;console.log('PASS',name)}
const mint='So11111111111111111111111111111111111111112';function setup(){e.initialize();const s=e.getState();const at=Date.now();s.tokens[mint]={mint,pair:mint,fields:{price:e.field(1,'FIXTURE',at),symbol:e.field('ISOLATED FIXTURE','FIXTURE',at),liquidity:e.field(100000,'FIXTURE',at)},risk:{mandatoryPassed:true},score:{total:90},earlyEvidence:[]};return s}function sig(s,id='test'){const x={id,mint,at:Date.now(),risk:{mandatoryPassed:true},score:{total:90},policyVersion:'ISOLATED'};e.autoQualifiedEvaluations.add(x);return x}
t('baseline $200/$20/6',()=>{setup();assert.equal(e.autoLedger().cash,200);assert.equal(e.autoLedger().entry,20);assert.equal(e.autoLedger().maxPositions,6)});
t('missing qualification identity rejected',()=>{const s=setup();assert.equal(e.continuousPaper.accept({...sig(s),id:'copy'}),false)});
t('mandatory unknown rejected even score90',()=>{const s=setup();s.tokens[mint].risk.mandatoryPassed=false;assert.equal(e.continuousPaper.accept(sig(s)),false)});
t('score below75 rejected',()=>{const s=setup(),x=sig(s);x.score.total=74;assert.equal(e.continuousPaper.accept(x),false)});
t('fees and slippage exact',()=>{const s=setup();assert(e.continuousPaper.accept(sig(s)));assert.equal(e.autoLedger().cash,179.94);assert.equal(e.autoLedger().positions[0].entry,1.01)});
t('same signal ID idempotent',()=>{const s=setup(),x=sig(s);assert(e.continuousPaper.accept(x));assert.equal(e.continuousPaper.accept(x),false)});
t('duplicate mint prevented',()=>{const s=setup();e.continuousPaper.accept(sig(s));assert.equal(e.continuousPaper.accept(sig(s,'new')),false)});
t('stale price rejected',()=>{const s=setup();s.tokens[mint].fields.price.observedAt-=121000;assert.equal(e.continuousPaper.accept(sig(s)),false)});
t('cached price rejected',()=>{const s=setup();s.tokens[mint].fields.price.dataState='CACHED';assert.equal(e.continuousPaper.accept(sig(s)),false)});
t('different pool quote rejected',()=>{const s=setup();e.continuousPaper.accept(sig(s));s.tokens[mint].pair='different';assert.equal(e.continuousPaper.quote(mint),null)});
t('TP1.5x exact P&L',()=>{const s=setup();e.continuousPaper.accept(sig(s));s.tokens[mint].fields.price=e.field(1.515,'FIXTURE',Date.now());e.continuousPaper.update();assert.equal(e.autoLedger().trades[0].reason,'TAKE_PROFIT_1.5X_OBSERVED');assert(Math.abs(e.autoLedger().trades[0].pnl-9.5509)<1e-8)});
t('minus50 stop',()=>{const s=setup();e.continuousPaper.accept(sig(s));s.tokens[mint].fields.price=e.field(.505,'FIXTURE',Date.now());e.continuousPaper.update();assert.equal(e.autoLedger().trades[0].reason,'STOP_MINUS_50_PERCENT_OBSERVED')});
t('rug99% collapse fullcost loss',()=>{const s=setup();e.continuousPaper.accept(sig(s));s.tokens[mint].fields.price=e.field(.001,'FIXTURE',Date.now());e.continuousPaper.update();assert.equal(e.autoLedger().trades[0].pnl,-20.06)});
t('zero liquidity fullcost loss',()=>{const s=setup();e.continuousPaper.accept(sig(s));s.tokens[mint].fields.liquidity=e.field(0,'FIXTURE',Date.now());e.continuousPaper.update();assert.equal(e.autoLedger().trades[0].reason,'RUG_PROXY_TOTAL_LOSS')});
t('3 successful omissions proxy',()=>{const s=setup();e.continuousPaper.accept(sig(s));e.autoLedger().positions[0].pairMisses=3;e.autoLedger().positions[0].lastPairCheck=Date.now();e.continuousPaper.update();assert.equal(e.autoLedger().trades[0].pnl,-20.06)});
t('no time limit',()=>{const s=setup();e.continuousPaper.accept(sig(s));e.autoLedger().positions[0].at-=999999999;e.continuousPaper.update();assert.equal(e.autoLedger().positions.length,1)});
t('no $400 freeze',()=>{const s=setup();e.autoLedger().cash=500;assert(e.continuousPaper.accept(sig(s)))});
t('six slot cap',()=>{const s=setup();e.autoLedger().positions=Array.from({length:6},(_,i)=>({mint:'different'+i}));assert.equal(e.continuousPaper.accept(sig(s)),false)});
t('cash requirement includes fee',()=>{const s=setup();e.autoLedger().cash=20;assert.equal(e.continuousPaper.accept(sig(s)),false)});
t('ledger reconciliation',()=>{const s=setup();e.continuousPaper.accept(sig(s));assert(e.continuousPaper.snapshot().reconciled)});
t('imported ledger blocked',()=>{const s=setup();e.autoLedger().imported=true;assert.equal(e.continuousPaper.accept(sig(s)),false)});
t('event ID dedup',()=>{const s=setup();e.continuousPaper.accept(sig(s));const events=[],x=e.autoLedger().positions[0];r.record(events,x,false);r.record(events,x,false);assert.equal(events.length,1);assert.equal(events[0].reason,'BUY')});
t('real risk missing proof blocks',()=>{const s=setup();assert.equal(e.riskEngine.check(s.tokens[mint]).mandatoryPassed,false)});
console.log('TOTAL',count,'PASS; synthetic fixtures only; zero relay POST');
