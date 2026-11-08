#!/usr/bin/env python3
"""Собирает отчёт report.html с графиками из analysis.json и recommendations.json (его пишет Claude).

  python3 build_report.py work/ [--title "Что ИИ нашёл в моей выписке"]

recommendations.json:
{
  "headline": "≈ 180–220 тыс. ₽",                 # итог одной цифрой
  "headline_note": "столько можно вернуть за год",
  "monthly_saving": 12500,                         # для графика «во что превратится» (₽ в месяц)
  "good": ["…", "…"],                              # что у человека хорошо
  "insights": [{"big": "136 раз", "label": "в одну пекарню", "small": "…"}],   # 4–6 плиток
  "recs": [{"title": "…", "text": "что не так → что сделать → первый шаг", "effect": "до 40 тыс."}],
  "data_note": "что взято, что убрано, допущения"
}
Отчёт — один файл без внешних зависимостей, открывается в браузере офлайн. Никуда не выкладывается.
"""
import argparse, html, json
from pathlib import Path

TEMPLATE = r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#0B0C10;--surface:#14161D;--line:#262A35;--ink:#F2F0EA;--ink2:#B9BCC6;--muted:#7D8290;--acc:#F5A524;--acc2:#FFD60A;--accsoft:rgba(245,165,36,.16);--bad:#E5484D}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#F7F5F0;--surface:#FFFFFF;--line:#E6E2D8;--ink:#17181C;--ink2:#4A4E59;--muted:#7A7F8C;--acc:#C77A00;--acc2:#9A6400;--accsoft:rgba(199,122,0,.12);--bad:#C62F34}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 16px 80px}
.tag{display:inline-block;font:600 12px/1 ui-monospace,Menlo,monospace;letter-spacing:.12em;color:var(--acc);text-transform:uppercase;border:1px solid var(--accsoft);background:var(--accsoft);padding:6px 10px;border-radius:999px}
h1{font-size:clamp(30px,5vw,46px);line-height:1.08;margin:16px 0 8px;letter-spacing:-.02em}h2{font-size:22px;margin:0 0 4px}.sub{color:var(--ink2);margin:0 0 18px}
.lead{color:var(--ink2);font-size:17px;max-width:760px}
.hero{background:linear-gradient(135deg,var(--accsoft),transparent 60%),var(--surface);border:1px solid var(--line);border-radius:22px;padding:26px;margin:18px 0 6px}
.hero .n{font-size:clamp(44px,8vw,72px);font-weight:800;letter-spacing:-.04em;color:var(--acc2);line-height:1}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:24px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:18px;padding:18px}
.tile .n{font-size:36px;font-weight:800;letter-spacing:-.03em;color:var(--acc2);line-height:1.05}.tile .l{font-weight:600;margin-top:6px}.tile .s{color:var(--muted);font-size:14px;margin-top:4px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:20px;padding:22px;margin:18px 0}
svg text{fill:var(--muted);font:12px -apple-system,Inter,sans-serif}svg .lab{fill:var(--ink2);font-weight:600}svg .val{fill:var(--ink);font-weight:700}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--bg);padding:8px 10px;border-radius:10px;font-size:13px;font-weight:600;opacity:0;transition:opacity .1s;z-index:9;max-width:260px}
.list{margin:0;padding-left:20px}.list li{margin:6px 0}
.recs{list-style:none;padding:0;margin:0;counter-reset:r}.recs li{counter-increment:r;display:grid;grid-template-columns:36px 1fr auto;gap:12px;padding:14px 0;border-top:1px solid var(--line)}
.recs li:first-child{border-top:0}.recs li:before{content:counter(r);width:28px;height:28px;border-radius:9px;background:var(--accsoft);color:var(--acc);font-weight:800;display:grid;place-items:center}
.recs b{display:block}.recs span{color:var(--ink2);font-size:14px}.recs .eff{font-weight:800;color:var(--acc2);white-space:nowrap}
.note{color:var(--muted);font-size:13px;margin-top:10px}.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--ink2);font-size:13px;margin-bottom:8px}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px}
</style></head><body><div class="wrap">
<span class="tag" id="tag"></span><h1>__TITLE__</h1><p class="lead" id="lead"></p>
<div class="hero"><div class="n" id="hero"></div><div style="font-weight:700;font-size:20px;margin-top:8px" id="heroNote"></div></div>
<div class="grid" id="tiles"></div>
<div class="card" id="goodCard"><h2>Что хорошо</h2><ul class="list" id="good"></ul></div>
<div class="card"><h2 id="mTitle"></h2><p class="sub" id="mSub"></p><div id="c_month"></div></div>
<div class="card"><h2>Когда я трачу деньги</h2><p class="sub">Каждая клетка — сколько покупок было в этот час этого дня недели. Чем ярче, тем чаще</p><div id="c_heat"></div></div>
<div class="card"><h2>Мелкие траты по часам</h2><p class="sub" id="hSub"></p><div id="c_hour"></div></div>
<div class="card"><h2>Куда уходят деньги</h2><p class="sub">Настоящие траты по категориям за период</p><div id="c_cats"></div><p class="note" id="catNote"></p></div>
<div class="card" id="debtCard"><h2>Долг по кредитке</h2><p class="sub" id="dSub"></p><div class="legend"><span><i style="background:var(--acc)"></i>задолженность</span><span><i style="background:var(--bad);border-radius:50%"></i>списаны проценты</span></div><div id="c_debt"></div></div>
<div class="card" id="fvCard"><h2 id="fvTitle"></h2><p class="sub" id="fvSub"></p><div id="c_fv"></div><p class="note">Условный расчёт: ставки со временем меняются.</p></div>
<div class="card"><h2>Что делать — по убыванию денег</h2><ul class="recs" id="recs"></ul></div>
<div class="card"><h2>Как считали</h2><p class="sub" id="dataNote" style="margin:0"></p></div>
<p class="note">Разбор сделан локально по выпискам. Это инструмент для самостоятельного анализа, а не финансовая рекомендация.</p>
</div><div class="tip" id="tip"></div>
<script>window.onerror=(m,s,l,c)=>{document.querySelector('.wrap').insertAdjacentHTML('afterbegin','<pre style="color:#E5484D;white-space:pre-wrap">Ошибка отчёта: '+m+' (строка '+l+':'+c+')</pre>')}</script>
<script>
const A=__ANALYSIS__, R=__RECS__;
const rub=v=>Math.round(v).toLocaleString('ru-RU')+' ₽', num=v=>Math.round(v).toLocaleString('ru-RU'), k=v=>Math.round(v/1000)+' тыс';
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim(), $=id=>document.getElementById(id), tip=$('tip');
function hover(el,h){el.addEventListener('mousemove',e=>{tip.innerHTML=h;tip.style.opacity=1;tip.style.left=Math.min(e.clientX+14,innerWidth-270)+'px';tip.style.top=(e.clientY+14)+'px'});el.addEventListener('mouseleave',()=>tip.style.opacity=0)}
const NS='http://www.w3.org/2000/svg';function svg(w,h){const s=document.createElementNS(NS,'svg');s.setAttribute('viewBox',`0 0 ${w} ${h}`);s.style.width='100%';s.style.height='auto';return s}
function el(t,a,p){const e=document.createElementNS(NS,t);for(const x in a)e.setAttribute(x,a[x]);p&&p.appendChild(e);return e}
function txt(p,x,y,s,c,an){const t=el('text',{x,y,'text-anchor':an||'start'},p);if(c)t.setAttribute('class',c);t.textContent=s;return t}
function nice(mx){const p=Math.pow(10,Math.floor(Math.log10(mx||1)));const f=mx/p;return (f<=1?1:f<=2?2:f<=2.5?2.5:f<=5?5:10)*p}
function bars(id,labels,vals,hi,fmt){const W=900,H=280,L=60,B=34,T=24,R0=10,mx=nice(Math.max(...vals)*1.1),s=svg(W,H),pw=(W-L-R0)/vals.length;
 for(let i=0;i<=4;i++){const g=mx*i/4,y=H-B-(H-B-T)*g/mx;el('line',{x1:L,x2:W-R0,y1:y,y2:y,stroke:css('--line')},s);txt(s,L-8,y+4,g?k(g):'0','','end')}
 vals.forEach((x,i)=>{const h=(H-B-T)*x/mx,X=L+i*pw+pw*.18,w=pw*.64,y=H-B-h,on=hi(i,x);if(h<=0)return;
 const r=el('path',{d:`M${X},${H-B}V${y+Math.min(4,h)}q0,-4 4,-4h${w-8}q4,0 4,4V${H-B}Z`,fill:on?css('--acc2'):css('--acc'),opacity:on?1:.75},s);hover(r,fmt(i,x));
 txt(s,X+w/2,H-B+18,labels[i],'','middle');if(on)txt(s,X+w/2,y-8,k(x),'val','middle')});$(id).appendChild(s)}

const MN=['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
$('tag').textContent=A.scale>1?`Демо · суммы уменьшены в ${A.scale} раза`:'Личное · не для публикации';
const p=A.period;$('lead').textContent=`${new Date(p.start).toLocaleDateString('ru-RU')} — ${new Date(p.end).toLocaleDateString('ru-RU')} · ${p.days} дней · ${num(A.operations)} операций. Переводы между своими счетами, вклады, погашение кредитки и наличные убраны (${rub(A.turnover_removed_total)} оборота) — ниже только настоящие траты.`;
$('hero').textContent=R.headline||'';$('heroNote').textContent=R.headline_note||'';
const tp=A.top_places[0], leak=A.categories.filter(c=>A.leak_groups.includes(c.name)), leakSum=leak.reduce((s,c)=>s+c.total,0);
const tiles=R.insights&&R.insights.length?R.insights:[
 [num(leakSum/p.days)+' ₽','в день на кафе, доставку и такси',rub(leakSum)+' за период'],
 tp?[tp.count+' раз',tp.merchant,rub(tp.total)+' · средний чек '+rub(tp.avg_check)+' · чаще всего в '+tp.peak_hour+':00']:null,
 A.credit&&A.credit.interest_total?[rub(A.credit.interest_total),'процентов по кредитке',A.credit.grace?'при льготном периоде '+A.credit.grace.toLowerCase():'']:null,
 A.idle.total?[rub(A.idle.total),'в среднем лежали без процентов','≈ '+rub(A.idle.lost_at_rate)+' недополучено под '+A.idle.rate+'%']:null,
 [A.no_spend_days+' дней','из '+p.days+' — без единой покупки',''],
].filter(Boolean).map(t=>Array.isArray(t)?{big:t[0],label:t[1],small:t[2]}:t);
$('tiles').innerHTML=tiles.map(t=>`<div class="tile"><div class="n">${t.big}</div><div class="l">${t.label}</div><div class="s">${t.small||''}</div></div>`).join('');
if(R.good&&R.good.length)$('good').innerHTML=R.good.map(g=>`<li>${g}</li>`).join('');else $('goodCard').remove();

// месяцы: главная «утечка» или все траты
const mc=leak[0], ms=A.months, mv=mc?ms.map(m=>mc.by_month[m]||0):ms.map(m=>A.spend_by_month[m]||0);
$('mTitle').textContent=(mc?mc.name[0].toUpperCase()+mc.name.slice(1):'Траты')+' по месяцам';
const mx=Math.max(...mv), mi=mv.indexOf(mx), mf=mv.find(v=>v>0)||1;$('mSub').textContent=mx>mf*1.5?`Пик — ${MN[+ms[mi].slice(5)-1]}: в ${(mx/mf).toFixed(1).replace('.',',')} раза больше, чем в первом месяце`:'Помесячно за период';
bars('c_month',ms.map((m,i)=>MN[+m.slice(5)-1]+(i==ms.length-1?'*':'')),mv,(i,x)=>x>=mx*.8||i==0,(i,x)=>`${ms[i]}: ${rub(x)}`);

(()=>{const D=['пн','вт','ср','чт','пт','сб','вс'],W=900,cw=(W-40)/24,ch=28,s=svg(W,ch*7+30),m=Math.max(...A.heat.flat());
A.heat.forEach((row,d)=>{txt(s,30,d*ch+ch/2+4,D[d],'lab','end');row.forEach((c,h)=>{const r=el('rect',{x:40+h*cw+1,y:d*ch+1,width:cw-2,height:ch-2,rx:4,fill:c?css('--acc'):css('--line'),'fill-opacity':c?.12+.88*c/m:.35},s);hover(r,`${D[d]}, ${h}:00 — ${c} покуп.`)})});
for(let h=0;h<24;h+=3)txt(s,40+h*cw+cw/2,7*ch+18,h+':00','','middle');$('c_heat').appendChild(s)})();

(()=>{const v=A.leak_hour_hist,W=900,H=220,L=40,B=30,T=16,m=Math.max(...v),s=svg(W,H),pw=(W-L-10)/24;const pk=v.indexOf(m);
$('hSub').textContent=`${A.leak_groups.join(', ')}. Пик — в ${pk}:00`;
v.forEach((x,i)=>{if(!x)return;const h=(H-B-T)*x/m,X=L+i*pw+pw*.15,w=pw*.7,y=H-B-h,on=x>=m*.7;const r=el('path',{d:`M${X},${H-B}V${y+Math.min(4,h)}q0,-4 4,-4h${w-8}q4,0 4,4V${H-B}Z`,fill:on?css('--acc2'):css('--acc'),opacity:on?1:.7},s);hover(r,`${i}:00 — ${x} покупок`);if(on)txt(s,X+w/2,y-6,i+':00','val','middle')});
el('line',{x1:L,x2:W-10,y1:H-B,y2:H-B,stroke:css('--line')},s);for(let h=0;h<24;h+=3)txt(s,L+h*pw+pw/2,H-B+18,h+':00','','middle');$('c_hour').appendChild(s)})();

(()=>{let c=A.categories.map(x=>[x.name,x.total,0]);if(A.people_total)c.push(['переводы людям',A.people_total,1]);if(A.unclear.total)c.push(['без получателя (уточнить)',A.unclear.total,2]);
c.sort((a,b)=>b[1]-a[1]);c=c.slice(0,14);const W=900,rh=32,L=300,H=c.length*rh+10,m=c[0][1],s=svg(W,H);
c.forEach(([n,v,t],i)=>{const y=i*rh+6,w=(W-L-110)*v/m;txt(s,L-12,y+18,n,'lab','end');const r=el('rect',{x:L,y:y+4,width:Math.max(w,3),height:rh-12,rx:4,fill:t==2?css('--muted'):css('--acc'),opacity:t==1?.45:(t==2?.6:.9)},s);hover(r,`${n}: ${rub(v)}`);txt(s,L+w+8,y+18,k(v),'val')});
$('c_cats').appendChild(s);if(A.unclear.count)$('catNote').textContent=`«Без получателя» — ${A.unclear.count} платежей: оплаты в приложении банка, суть не видна по выписке.`})();

(()=>{const C=A.credit;if(!C||!C.debt||!C.debt.length){$('debtCard').remove();return}
$('dSub').textContent=C.interest_total?`Списано процентов: ${rub(C.interest_total)}${C.rate?' · ставка '+C.rate:''}${C.grace?' · льготный период '+C.grace.toLowerCase():''}`:'Проценты не начислялись — кредитка используется правильно';
const pts=C.debt.map(([d,v])=>[new Date(d),v]),W=900,H=280,L=64,B=30,T=20,R0=16,t0=new Date(A.period.start),t1=new Date(A.period.end),mx=nice(Math.max(...pts.map(x=>x[1]))*1.1);
const X=t=>L+(W-L-R0)*(t-t0)/(t1-t0),Y=v=>H-B-(H-B-T)*v/mx,s=svg(W,H);
for(let i=0;i<=3;i++){const g=mx*i/3;el('line',{x1:L,x2:W-R0,y1:Y(g),y2:Y(g),stroke:css('--line')},s);txt(s,L-8,Y(g)+4,g?k(g):'0','','end')}
let d=`M${X(t0)},${Y(0)}`;pts.forEach(([t,v])=>{d+=`H${X(t)}V${Y(v)}`});d+=`H${X(t1)}`;el('path',{d:d+`V${Y(0)}Z`,fill:css('--acc'),'fill-opacity':.12},s);el('path',{d,fill:'none',stroke:css('--acc'),'stroke-width':2},s);
(C.interest||[]).forEach(([dt,v])=>{const t=new Date(dt);let dv=0;pts.forEach(([pt,pv])=>{if(pt<=t)dv=pv});const c=el('circle',{cx:X(t),cy:Y(dv),r:7,fill:css('--bad'),stroke:css('--surface'),'stroke-width':2},s);hover(c,`${t.toLocaleDateString('ru-RU')}: проценты ${rub(v)}`);if(v>=C.interest_total*.25)txt(s,X(t),Y(dv)-14,'−'+num(v)+' ₽','val','middle')});
A.months.forEach(m=>{const t=new Date(m+'-01');if(t>=t0)txt(s,X(t)+16,H-B+18,MN[+m.slice(5)-1],'','middle')});$('c_debt').appendChild(s)})();

(()=>{const ms=R.monthly_saving,rate=A.saving_rate/100;if(!ms){$('fvCard').remove();return}
$('fvTitle').textContent=`Во что превратится «${num(ms)} ₽ в месяц»`;$('fvSub').textContent=`Если откладывать эту сумму под ${A.saving_rate}% годовых`;
const fv=y=>{const i=rate/12,n=12*y;return ms*((1+i)**n-1)/i},v=[...Array(11).keys()].map(y=>[y,fv(y)]),W=900,H=260,L=70,B=30,T=30,R0=24,mx=nice(v[10][1]*1.1);
const X=i=>L+(W-L-R0)*i/10,Y=x=>H-B-(H-B-T)*x/mx,s=svg(W,H),f=x=>x>=1e6?(x/1e6).toFixed(2).replace('.',',')+' млн ₽':k(x)+' ₽';
for(let i=0;i<=3;i++){const g=mx*i/3;el('line',{x1:L,x2:W-R0,y1:Y(g),y2:Y(g),stroke:css('--line')},s);txt(s,L-8,Y(g)+4,g?(g>=1e6?(g/1e6).toFixed(1)+' млн':k(g)):'0','','end')}
const d=v.map(([y,x],i)=>(i?'L':'M')+X(y)+','+Y(x)).join('');el('path',{d:d+`L${X(10)},${Y(0)}L${X(0)},${Y(0)}Z`,fill:css('--acc'),'fill-opacity':.14},s);el('path',{d,fill:'none',stroke:css('--acc2'),'stroke-width':2.5},s);
v.forEach(([y,x])=>{const c=el('circle',{cx:X(y),cy:Y(x),r:y==10?7:4,fill:css('--acc2'),stroke:css('--surface'),'stroke-width':2},s);hover(c,`через ${y} лет: ${rub(x)}`);txt(s,X(y),H-B+18,y?y+' г':'сейчас','','middle')});
txt(s,X(10)-6,Y(v[10][1])-14,f(v[10][1]),'val','end');$('c_fv').appendChild(s)})();

$('recs').innerHTML=(R.recs||[]).map(r=>`<li><div><b>${r.title}</b><span>${r.text||''}</span></div><div class="eff">${r.effect||''}</div></li>`).join('');
$('dataNote').textContent=R.data_note||'';
</script></body></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work')
    ap.add_argument('--title', default='Что ИИ нашёл в моей выписке')
    a = ap.parse_args()
    W = Path(a.work)
    A = json.load(open(W / 'analysis.json'))
    recs_path = W / 'recommendations.json'
    R = json.load(open(recs_path)) if recs_path.exists() else {}
    page = (TEMPLATE.replace('__TITLE__', html.escape(a.title))
            .replace('__ANALYSIS__', json.dumps(A, ensure_ascii=False))
            .replace('__RECS__', json.dumps(R, ensure_ascii=False)))
    (W / 'report.html').write_text(page)
    print(W / 'report.html')


if __name__ == '__main__':
    main()
