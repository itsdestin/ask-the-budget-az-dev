# Generates ../subpage-fiscal-notes.html (the live Fiscal Notes page) from:
#   - base.html  : the pristine page chrome (header/hero/footer) — DO NOT point this at the generated page.
#   - live/*.html : one cached copy of azjlbc.gov/fiscal-notes/?Year=YYYY per session (the source data).
# Design: filter sidebar (search + chamber switch + session list) -> per-session card directory.
# "All" chamber = one merged list (no chamber headers); CSS Sort control (bill# / title, asc/desc);
# a small JS block does live text filtering + the "search all sessions" scope toggle. See BUILD.md.
import re, glob, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, '..', 'subpage-fiscal-notes.html')   # the live page this generates
base = open(os.path.join(HERE, 'base.html'), encoding='utf-8', newline='').read()
NL = '\r\n' if '\r\n' in base else '\n'

# ---------------- parse live pages ----------------
PAIR = re.compile(
    r'>([A-Z]{2,4}\s?\d+)</a></div>\s*<div class="divTableCell"[^>]*>\s*'
    r'<a href="([^"]+)"[^>]*?>(.*?)</a>', re.S)
def spaced(no):
    m=re.match(r'([A-Z]+)\s?(\d+)', no); return m.group(1)+' '+m.group(2)

DATA={}
for fp in glob.glob(os.path.join(HERE, 'live', '*.html')):
    y=int(os.path.basename(fp)[:4])
    s=open(fp, encoding='utf-8', errors='replace').read()
    rows=[]; seen=set()
    for no,href,desc in PAIR.findall(s):
        if '/fiscal/' not in href: continue
        no=no.strip(); desc=re.sub(r'\s+',' ',desc).strip()
        key=(no,href)
        if key in seen: continue
        seen.add(key)
        rows.append((spaced(no),desc,href.replace('&amp;','&')))
    if rows: DATA[y]=rows
YEARS=sorted(DATA, reverse=True)
def ch(no): return 'H' if no[0]=='H' else 'S'
def hc(y): return sum(1 for r in DATA[y] if ch(r[0])=='H')
def sc(y): return sum(1 for r in DATA[y] if ch(r[0])=='S')
def tot(y): return len(DATA[y])
def ordinal(n):
    suf = 'th' if 10 <= n%100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')
    return str(n)+suf
def leg_session(y):
    # AZ: odd year = 1st Regular, even year = 2nd Regular; 57th Legislature = 2025-2026.
    if y%2==1: leg=44+(y-1999)//2; sess='1st Reg. Session'
    else:      leg=44+(y-2000)//2; sess='2nd Reg. Session'
    return '%s Legislature, %s (%d)'%(ordinal(leg),sess,y)
print('years:',len(YEARS),'total bills:',sum(tot(y) for y in YEARS))

SRCH_IC='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>'
CHEV='<svg class="sb-chev" viewBox="0 0 10 6" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m1 1 4 4 4-4"/></svg>'

def numkey(no): return (int(re.search(r'\d+',no).group()), no)

def bill(rec, na,nd,ta,td):
    no,desc,url=rec
    cls='b-h' if ch(no)=='H' else 'b-s'
    nid=no.replace(' ',''); num=re.search(r'\d+',no).group()
    return ('<a class="fbill %s" data-no="%s" data-num="%s" style="--na:%d;--nd:%d;--ta:%d;--td:%d" href="%s" target="_blank" rel="noopener">'
            '<span class="fbill-no">%s</span><span class="fbill-desc">%s</span>'
            '<span class="fbill-dl">PDF</span></a>')%(cls,nid,num,na,nd,ta,td,url,no,desc)

def sortctl():
    cur=('<span class="sortcur sc-na">Bill Number (Low to High)</span><span class="sortcur sc-nd">Bill Number (High to Low)</span>'
         '<span class="sortcur sc-ta">Bill Title (A to Z)</span><span class="sortcur sc-td">Bill Title (Z to A)</span>')
    menu=('<div class="sortmenu">'+NL+
          '              <label for="fnS-na" class="sortopt o-na">Bill number &mdash; low to high</label>'+NL+
          '              <label for="fnS-nd" class="sortopt o-nd">Bill number &mdash; high to low</label>'+NL+
          '              <label for="fnS-ta" class="sortopt o-ta">Bill title &mdash; A to Z</label>'+NL+
          '              <label for="fnS-td" class="sortopt o-td">Bill title &mdash; Z to A</label>'+NL+
          '            </div>')
    return ('<div class="sortctl" tabindex="0">'+NL+
            '            <span class="sortbtn">Sort: %s %s</span>'%(cur,CHEV)+NL+
            '            '+menu+NL+'          </div>')

def year_group(y):
    rows=DATA[y]
    nrank={id(r):i for i,r in enumerate(sorted(rows, key=lambda r:numkey(r[0])))}
    trank={id(r):i for i,r in enumerate(sorted(rows, key=lambda r:r[1].lower()))}
    N=len(rows)
    dom=sorted(rows, key=lambda r:numkey(r[0]))   # default DOM order = bill# asc
    blines=NL.join('          '+bill(r, nrank[id(r)], N-1-nrank[id(r)], trank[id(r)], N-1-trank[id(r)]) for r in dom)
    meta=('<span class="yg-meta"><span class="ym-all">%d Fiscal Notes</span>'
          '<span class="ym-h">%d House Notes</span><span class="ym-s">%d Senate Notes</span></span>')%(tot(y),hc(y),sc(y))
    return ('<section class="yg y%d" data-year="%d">'%(y,y)+NL+
            '        <div class="yg-head">'+NL+
            '          <div class="yg-ttl"><span class="yg-yr">%s</span>%s</div>'%(leg_session(y),meta)+NL+
            '          '+sortctl()+NL+
            '        </div>'+NL+
            '        <div class="fnlist">'+NL+blines+NL+'        </div>'+NL+'      </section>')

ROW_CSS = """
  .fnlist{display:flex;flex-direction:column;}
  .fbill{display:flex;align-items:center;gap:14px;padding:11px 18px;border-bottom:1px solid var(--line);color:inherit;transition:background .14s;}
  .fbill:hover{background:#fafafe;text-decoration:none;}
  .fbill-no{flex:0 0 auto;font-size:12.5px;font-weight:800;color:#fff;background:var(--navy);border-radius:var(--r-pill);padding:4px 12px;letter-spacing:.01em;min-width:78px;text-align:center;}
  .fbill:hover .fbill-no{background:var(--az-gold-d);}
  .fbill-desc{flex:1;min-width:0;font-size:14px;font-weight:600;color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
  .fbill-dl{flex:0 0 auto;font-size:11.5px;font-weight:800;color:var(--ink-3);background:var(--canvas);border:1px solid var(--line);border-radius:var(--r-pill);padding:5px 12px;white-space:nowrap;}
  .fbill-dl::before{content:"\\2193";margin-right:5px;font-weight:800;}
  .fbill:hover .fbill-dl{border-color:var(--az-gold);color:var(--az-gold-d);}
  .yg-head{display:flex;align-items:center;gap:12px;padding:15px 18px;border-bottom:1px solid var(--line);}
  .yg-ttl{display:flex;flex-direction:column;gap:2px;min-width:0;}
  .yg-yr{font-size:18px;font-weight:800;color:var(--navy);}
  .yg-meta{font-size:12.5px;font-weight:700;color:var(--ink-3);}
  .ym-h,.ym-s{display:none;}
  main .wrap.fnwrap{display:block;grid-template-columns:none;padding:28px 22px 22px;}
"""
SORT_CSS = """
  /* sort control (CSS-only menu) */
  .sortctl{position:relative;margin-left:auto;flex:0 0 auto;outline:0;}
  .sortbtn{display:inline-flex;align-items:center;gap:7px;cursor:pointer;font-size:12.5px;font-weight:800;color:var(--ink-2);background:var(--canvas);border:1px solid var(--line);border-radius:var(--r-pill);padding:7px 13px;white-space:nowrap;transition:.14s;}
  .sortctl:hover .sortbtn,.sortctl:focus-within .sortbtn{border-color:var(--az-gold);color:var(--az-gold-d);}
  .sb-chev{width:10px;height:6px;opacity:.7;transition:transform .2s;}
  .sortctl:hover .sb-chev,.sortctl:focus-within .sb-chev{transform:rotate(180deg);}
  .sortcur{display:none;}
  .sortmenu{position:absolute;top:100%;right:0;margin-top:6px;min-width:228px;background:#fff;border:1px solid var(--line);border-radius:var(--r-md);box-shadow:var(--shadow);padding:6px;z-index:30;opacity:0;visibility:hidden;transform:translateY(5px);transition:opacity .15s,transform .15s,visibility .15s;}
  .sortctl:hover .sortmenu,.sortctl:focus-within .sortmenu{opacity:1;visibility:visible;transform:translateY(0);}
  .sortopt{display:block;font-size:13.5px;font-weight:700;color:var(--ink-2);padding:9px 12px;border-radius:var(--r-sm);cursor:pointer;white-space:nowrap;}
  .sortopt:hover{background:var(--canvas);color:var(--navy);}
"""
SIDEBAR_CSS = """
  .fnlayout{display:grid;grid-template-columns:248px 1fr;gap:var(--gap);align-items:start;}
  .fnside{background:#fff;border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow-sm);padding:8px;position:sticky;top:100px;}
  .fnside .fgrp{padding:8px 8px 14px;}
  .fnside .fgrp+.fgrp{border-top:1px solid var(--line);}
  .fnside .flbl{font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);padding:6px 8px 8px;}
  .fside-search{display:flex;align-items:center;gap:8px;background:var(--canvas);border:1px solid var(--line);border-radius:var(--r-pill);padding:8px 12px;margin:2px 4px 6px;}
  .fside-search svg{width:16px;height:16px;color:var(--ink-3);}
  .fside-search input{border:0;background:transparent;outline:0;font-family:inherit;font-size:13.5px;flex:1;min-width:0;color:var(--ink);}
  .clr-x{flex:0 0 auto;display:none;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;border:1px solid var(--line);background:#fff;color:var(--ink-2);cursor:pointer;padding:0;transition:background .14s,color .14s,border-color .14s,transform .08s;}
  .clr-x:hover{background:var(--navy-100);color:var(--navy);border-color:var(--navy);}
  .clr-x:active{transform:scale(.88);}
  .clr-x svg{width:13px;height:13px;}
  .clr-x.show{display:inline-flex;}
  .chswitch{display:grid;grid-template-columns:1fr 1fr 1fr;gap:3px;background:var(--canvas);border:1px solid var(--line);border-radius:var(--r-pill);padding:4px;margin:0 4px;}
  .chseg{cursor:pointer;text-align:center;font-size:13px;font-weight:800;color:var(--ink-2);border-radius:var(--r-pill);padding:8px 4px;transition:.13s;}
  .chseg:hover{color:var(--az-gold-d);}
  .yscroll{max-height:330px;overflow-y:auto;padding-right:2px;}
  .frow{display:flex;align-items:center;justify-content:space-between;gap:8px;cursor:pointer;font-size:14px;font-weight:700;color:var(--ink-2);border:1px solid transparent;border-radius:var(--r-md);padding:8px 12px;transition:.13s;}
  .frow:hover{background:var(--navy-100);color:var(--navy);}
  .frow-n{font-size:11px;font-weight:800;background:var(--canvas);border:1px solid var(--line);border-radius:var(--r-pill);padding:1px 8px;color:var(--ink-3);}
  .fnmain{display:flex;flex-direction:column;gap:var(--gap);min-width:0;}
  .yg{background:#fff;border:1px solid var(--line);border-radius:var(--r-lg);box-shadow:var(--shadow-sm);overflow:hidden;}
  .allbar{display:flex;justify-content:center;padding:2px 0;}
  .allbtn{display:inline-flex;align-items:center;gap:9px;cursor:pointer;font-size:13.5px;font-weight:800;color:var(--az-gold-d);background:#fff;border:1px solid var(--az-gold-100);border-radius:var(--r-pill);padding:11px 20px;box-shadow:var(--shadow-sm);transition:.14s;}
  .allbtn:hover{border-color:var(--az-gold);background:var(--az-gold-100);}
  .allbtn svg{width:16px;height:16px;flex:0 0 auto;}
  .all-off,.all-on{display:inline-flex;align-items:center;gap:9px;}
  .all-on{display:none;}
  @media (max-width:860px){ .fnlayout{grid-template-columns:1fr;} .fnside{position:static;} }
"""

SCRIPT = r'''<script>
/* Live filter for the fiscal-note browser — the one scripted feature on this page (like the search page).
   Default: filters within the SELECTED session only. The "Search all legislative sessions" pill (#fnAll)
   widens the scope to every session, shown as separate stacked cards with only that session's matches.
   Matches bill-number PREFIX ("12" -> 12xx; "2015"/"HB 2015"/"HB2015" all hit HB2015) or a title keyword,
   respecting the chamber switch. Pure CSS can't filter arbitrary typed text. */
(function(){
  var box=document.querySelector('.fside-search input'); if(!box) return;
  var allChk=document.getElementById('fnAll');
  var groups=[].slice.call(document.querySelectorAll('.fnmain .yg')).map(function(g){
    return {g:g, year:g.getAttribute('data-year'),
      bills:[].slice.call(g.querySelectorAll('.fbill')).map(function(b){
        return {el:b, no:b.getAttribute('data-no'), num:b.getAttribute('data-num'),
                desc:(b.querySelector('.fbill-desc').textContent||'').toLowerCase(),
                h:b.className.indexOf('b-h')>-1};
      })};
  });
  function sel(name){ var r=document.querySelector('input[name='+name+']:checked'); return r?r.id.slice(r.id.indexOf('-')+1):''; }
  function clearInline(){ groups.forEach(function(G){ G.g.style.display=''; G.bills.forEach(function(b){ b.el.style.display=''; }); }); }
  function render(){
    var q=box.value.trim();
    if(!q){ allChk.checked=false; clearInline(); return; }   // no input -> always revert to the selected session
    var all=allChk.checked;
    var sy=sel('m3y'), ch=sel('m3c');
    var hasLetter=/[a-z]/i.test(q), digits=q.replace(/[^0-9]/g,''), qid=q.toUpperCase().replace(/\s+/g,''), low=q.toLowerCase();
    groups.forEach(function(G){
      if(!all && G.year!==sy){ G.g.style.display='none'; return; }  // scoped: only the selected session
      var any=false;
      G.bills.forEach(function(b){
        var okCh = ch==='all' || (ch==='house'? b.h : !b.h);
        var okQ = !q || (hasLetter ? (b.no.indexOf(qid)===0 || b.desc.indexOf(low)>-1)
                                   : (digits!=='' && b.num.indexOf(digits)===0));
        var ok=okCh&&okQ;
        b.el.style.display = ok ? '' : 'none';
        if(ok) any=true;
      });
      G.g.style.display = any ? 'block' : 'none';   /* 'block' (not '') to override the year-filter CSS hide */
    });
  }
  box.addEventListener('input', render);
  var cx=box.parentNode.querySelector('.clr-x');
  function togX(){ if(cx) cx.classList.toggle('show', box.value.length>0); }
  box.addEventListener('input', togX);
  if(cx) cx.addEventListener('click', function(){ box.value=''; togX(); box.focus(); render(); });
  allChk.addEventListener('change', render);
  [].forEach.call(document.querySelectorAll('input[name=m3c]'), function(r){ r.addEventListener('change', render); });
  [].forEach.call(document.querySelectorAll('input[name=m3y]'), function(r){ r.addEventListener('change', function(){ allChk.checked=false; render(); }); });
})();
</script>'''

def build():
    yradios=NL.join('  <input type="radio" class="fnr" name="m3y" id="fnY-%d"%s>'%(y,' checked' if y==YEARS[0] else '') for y in YEARS)
    cradios=('  <input type="radio" class="fnr" name="m3c" id="fnC-all" checked>'+NL+
             '  <input type="radio" class="fnr" name="m3c" id="fnC-house">'+NL+
             '  <input type="radio" class="fnr" name="m3c" id="fnC-senate">')
    sradios=('  <input type="radio" class="fnr" name="m3s" id="fnS-na" checked>'+NL+
             '  <input type="radio" class="fnr" name="m3s" id="fnS-nd">'+NL+
             '  <input type="radio" class="fnr" name="m3s" id="fnS-ta">'+NL+
             '  <input type="radio" class="fnr" name="m3s" id="fnS-td">')
    achk='  <input type="checkbox" class="fnr" id="fnAll">'
    allbar=('<div class="allbar">'+NL+
            '          <label for="fnAll" class="allbtn">'+NL+
            '            <span class="all-off">'+SRCH_IC+' Search all legislative sessions</span>'+NL+
            '            <span class="all-on">&#8617; Search only the selected session</span>'+NL+
            '          </label>'+NL+'        </div>')
    ylist=NL.join('            <label for="fnY-%d" class="frow"><span>%d</span><span class="frow-n">%d</span></label>'%(y,y,tot(y)) for y in YEARS)
    chswitch=('          <div class="chswitch">'+NL+
              '            <label for="fnC-all" class="chseg">All</label>'+NL+
              '            <label for="fnC-house" class="chseg">House</label>'+NL+
              '            <label for="fnC-senate" class="chseg">Senate</label>'+NL+'          </div>')
    groups=NL.join('        '+year_group(y) for y in YEARS)

    css=['  .fnr{position:absolute;width:1px;height:1px;margin:-1px;clip:rect(0 0 0 0);overflow:hidden;}']
    # year filter
    for y in YEARS: css.append('  #fnY-%d:checked ~ .fnlayout .fnmain .yg:not(.y%d){display:none;}'%(y,y))
    # chamber filter (per-bill) + meta-count toggle
    css.append('  #fnC-house:checked ~ .fnlayout .fnmain .b-s{display:none;}')
    css.append('  #fnC-senate:checked ~ .fnlayout .fnmain .b-h{display:none;}')
    css.append('  #fnC-house:checked ~ .fnlayout .ym-all,#fnC-senate:checked ~ .fnlayout .ym-all{display:none;}')
    css.append('  #fnC-house:checked ~ .fnlayout .ym-h{display:inline;}')
    css.append('  #fnC-senate:checked ~ .fnlayout .ym-s{display:inline;}')
    # sort: order vars + current-label + active option
    css.append('  #fnS-na:checked ~ .fnlayout .fnmain .fbill{order:var(--na);}')
    css.append('  #fnS-nd:checked ~ .fnlayout .fnmain .fbill{order:var(--nd);}')
    css.append('  #fnS-ta:checked ~ .fnlayout .fnmain .fbill{order:var(--ta);}')
    css.append('  #fnS-td:checked ~ .fnlayout .fnmain .fbill{order:var(--td);}')
    css.append('  #fnS-na:checked ~ .fnlayout .sc-na,#fnS-nd:checked ~ .fnlayout .sc-nd,#fnS-ta:checked ~ .fnlayout .sc-ta,#fnS-td:checked ~ .fnlayout .sc-td{display:inline;}')
    for k in ['na','nd','ta','td']:
        css.append('  #fnS-%s:checked ~ .fnlayout .o-%s{background:var(--az-gold-100);color:var(--az-gold-d);}'%(k,k))
    # active states
    for y in YEARS:
        css.append('  #fnY-%d:checked ~ .fnlayout .frow[for=fnY-%d]{background:var(--az-gold);color:#fff;border-color:var(--az-gold);}'%(y,y))
        css.append('  #fnY-%d:checked ~ .fnlayout .frow[for=fnY-%d] .frow-n{background:rgba(255,255,255,.25);color:#fff;}'%(y,y))
    for c in ['all','house','senate']:
        css.append('  #fnC-%s:checked ~ .fnlayout .chseg[for=fnC-%s]{background:var(--navy);color:#fff;}'%(c,c))
    # search-all toggle pill state
    css.append('  #fnAll:checked ~ .fnlayout .all-off{display:none;}')
    css.append('  #fnAll:checked ~ .fnlayout .all-on{display:inline-flex;}')
    css.append('  #fnAll:checked ~ .fnlayout .allbtn{color:var(--navy);border-color:var(--navy-100);background:var(--navy-100);}')
    css = NL.join(css)+NL+ROW_CSS+SORT_CSS+SIDEBAR_CSS

    main=('  <div class="wrap fnwrap">'+NL+yradios+NL+cradios+NL+sradios+NL+achk+NL+
          '    <div class="fnlayout">'+NL+
          '      <aside class="fnside">'+NL+
          '        <div class="fgrp"><label class="fside-search">%s<input type="text" placeholder="Bill # or keyword…"><button type="button" class="clr-x" aria-label="Clear search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></label></div>'%SRCH_IC+NL+
          '        <div class="fgrp"><div class="flbl">Chamber</div>'+NL+chswitch+NL+'        </div>'+NL+
          '        <div class="fgrp"><div class="flbl">Legislative Session</div>'+NL+'          <div class="yscroll">'+NL+ylist+NL+'          </div>'+NL+'        </div>'+NL+
          '      </aside>'+NL+
          '      <div class="fnmain">'+NL+groups+NL+'        '+allbar+NL+'      </div>'+NL+'    </div>'+NL+'  </div>')
    s=base
    s=s.replace('</style>',css+NL+'</style>',1)
    s=re.sub(r'(?m)^<main>[\s\S]*?^</main>','<main>'+NL+main+NL+'</main>',s,count=1)  # ^-anchored so a <main> in a comment can't match
    # remove the "57th Legislature…" chip from the hero (leave the "House & Senate bills" chip)
    s=re.sub(r'\s*<span class="chip"><svg[\s\S]*?</svg>\s*\d+th Legislature[\s\S]*?</span>','',s,count=1)
    s=s.replace('</body>', SCRIPT+NL+'</body>', 1)
    return s

open(OUT,'w',encoding='utf-8',newline='').write(build())
print('wrote', os.path.normpath(OUT), '('+str(os.path.getsize(OUT))+' bytes)')
