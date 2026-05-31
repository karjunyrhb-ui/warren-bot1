"""
Movers Swing Scanner
- Bursa: scrapes klsescreener.com markets page for Top Gainers(30)/Active(30)/Losers(10)
- US: pulls Yahoo screeners day_gainers/most_actives/day_losers
Applies EMA5/10 + support + bullish-candle swing scan to each mover.
Sends separate Telegram messages per market. 100% free.
"""
import os, re, time, json, requests
import yfinance as yf
from datetime import datetime, timezone

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT  = os.environ["TELEGRAM_CHAT_ID"]
UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# ── EMA / candle / scan helpers ───────────────────────────────────────────────
def ema(s, span): return s.ewm(span=span, adjust=False).mean()

def detect_candle(o,h,l,c,po,pc):
    body=abs(c-o); rng=h-l if h>l else 1e-9
    low_w=min(o,c)-l; up_w=h-max(o,c); pats=[]
    if pc<po and c>o and c>=po and o<=pc: pats.append("bullish engulfing")
    if low_w>2*body and up_w<body and body/rng<0.4: pats.append("hammer")
    if body/rng<0.1: pats.append("doji")
    return pats

def swing_score(df):
    if df is None or df.empty or len(df) < 30: return None
    cl=df["Close"]; hi=df["High"]; lo=df["Low"]; op=df["Open"]
    price=float(cl.iloc[-1]); e5=float(ema(cl,5).iloc[-1]); e10=float(ema(cl,10).iloc[-1])
    above = price>e5 and price>e10
    stacked = e5>e10
    support=float(lo.tail(20).min()); dist=(price-support)/support*100 if support else 99
    pats=detect_candle(float(op.iloc[-1]),float(hi.iloc[-1]),float(lo.iloc[-1]),
                       float(cl.iloc[-1]),float(op.iloc[-2]),float(cl.iloc[-2]))
    d=cl.diff(); g=d.clip(lower=0).tail(14).mean(); ls=(-d.clip(upper=0)).tail(14).mean()
    rsi=100-100/(1+g/ls) if ls!=0 else 50.0
    sc=0; rs=[]
    if above: sc+=25; rs.append("above EMA5/10")
    if stacked: sc+=15; rs.append("EMAs stacked")
    if dist<=3: sc+=30; rs.append("at support")
    elif dist<=6: sc+=20; rs.append("near support")
    elif dist<=10: sc+=10; rs.append("approaching support")
    if pats: sc+=20; rs.append("+".join(pats))
    if 40<=rsi<=65: sc+=10; rs.append("RSI healthy")
    elif rsi>70: sc-=10; rs.append("overbought")
    return {"price":round(price,3),"e5":round(e5,3),"e10":round(e10,3),
            "dist":round(dist,1),"rsi":round(rsi,1),"patterns":pats,
            "above":above,"score":max(0,sc),"reasons":", ".join(rs)}

# ── Bursa: scrape klsescreener markets page ───────────────────────────────────
def fetch_bursa_movers():
    url="https://www.klsescreener.com/v2/markets"
    r=requests.get(url, headers=UA, timeout=20)
    html=r.text
    # The page lists each row as an HTML anchor: <a href="/v2/stocks/view/CODE">NAME</a>
    # Works whether served as HTML or markdown-style links.
    def section(name):
        # chunk from this heading to the next section heading
        m=re.search(re.escape(name)+r"(.*?)(Top Gainers %|Top Losers %|Top Turnover|Top Losers|Top Gainers|Bursa Index)",
                    html[html.find(name)+len(name):], re.S)
        chunk = m.group(1) if m else ""
        # match both [NAME](.../view/CODE) and href="/v2/stocks/view/CODE">NAME<
        pairs = re.findall(r'\[([A-Z0-9&\.\-]+)\]\([^)]*?/stocks/view/([0-9A-Z]+)\)', chunk)
        if not pairs:
            pairs = [(n,c) for c,n in re.findall(r'/stocks/view/([0-9A-Z]+)"[^>]*>\s*([A-Z0-9&\.\-]+)\s*<', chunk)]
        return pairs
    g=section("Top Gainers")[:30]
    a=section("Top Active")[:30]
    l=section("Top Losers")[:10]
    seen={}
    for name,code in g: seen.setdefault((code,name),[]).append("gainer")
    for name,code in a: seen.setdefault((code,name),[]).append("active")
    for name,code in l: seen.setdefault((code,name),[]).append("loser")
    # keep only plain numeric Bursa codes (filters out warrants/PA/structured like 1163PA, 0270C8)
    out=[]
    for (code,name),tags in seen.items():
        if not code.isdigit():
            continue
        out.append((code,name,",".join(tags)))
    return out

def fetch_us_movers():
    base="https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    out={}
    for scr,tag,lim in [("day_gainers","gainer",30),("most_actives","active",30),("day_losers","loser",10)]:
        try:
            r=requests.get(base,params={"scrIds":scr,"count":lim},headers=UA,timeout=20).json()
            quotes=r["finance"]["result"][0]["quotes"]
            for q in quotes[:lim]:
                sym=q.get("symbol"); nm=q.get("shortName",sym)
                if not sym: continue
                out.setdefault((sym,nm),[]).append(tag)
        except Exception as e:
            print("  US screener warn",scr,e)
    return [(s,n,",".join(t)) for (s,n),t in out.items()]

def send(msg):
    r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                    json={"chat_id":CHAT,"text":msg[:4000],"parse_mode":"HTML"},timeout=15)
    if not r.ok: print("  TG error:",r.text)

def emoji(sc): return "\U0001F7E2" if sc>=75 else "\U0001F7E1" if sc>=55 else "\u26AA"
TAGEMO={"gainer":"\U0001F4C8","active":"\U0001F525","loser":"\U0001F4C9"}

def run(name, flag, movers, yf_suffix):
    print(f"\n== {name}: {len(movers)} movers ==")
    rows=[]
    for code,nm,tags in movers:
        yt=code+yf_suffix
        print("  ",yt,end=" ",flush=True)
        try:
            df=yf.Ticker(yt).history(period="6mo")
            r=swing_score(df)
        except Exception as e:
            r=None; print("err",e)
        if not r: print("-"); continue
        print("sc=%d"%r["score"])
        r.update({"code":code,"name":nm,"tags":tags}); rows.append(r)
        time.sleep(0.3)
    # only show ones in uptrend (above EMAs), ranked
    rows=[r for r in rows if r["above"]]
    rows.sort(key=lambda x:x["score"],reverse=True)
    now=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    L=[f"{flag} <b>{name} Movers Swing Scan</b>\n\U0001F4C5 {now}",
       "<i>Today's movers, filtered to uptrend + support + candle</i>\n"]
    top=rows[:12]
    if not top: L.append("No movers in a clean uptrend right now.")
    for r in top:
        tg="".join(TAGEMO.get(t,"") for t in r["tags"].split(","))
        cand=("\U0001F56F "+", ".join(r["patterns"])) if r["patterns"] else ""
        L.append("%s%s <b>%s</b> %s \u00b7 <b>%d/100</b>\n   %.1f%% above support | RSI %.1f %s\n   <i>%s</i>"
                 %(emoji(r["score"]),tg,r["name"],r["code"],r["score"],r["dist"],r["rsi"],cand,r["reasons"]))
    prime=[r["name"] for r in rows if r["score"]>=75]
    if prime: L.append("\n\U0001F3AF <b>Prime</b>: "+", ".join(prime))
    L.append("\n\U0001F4C8 gainer \u00b7 \U0001F525 active \u00b7 \U0001F4C9 loser")
    L.append("<i>Candidates only \u2014 confirm on chart. Not advice.</i>")
    send("\n".join(L))
    print(f"  sent top {len(top)}")

def main():
    market=os.environ.get("MARKET","BOTH").upper()
    print("Movers Scanner —",datetime.now().strftime("%Y-%m-%d %H:%M"),"market=",market)
    if market in ("MY","BOTH"):
        try: run("Bursa MY","\U0001F1F2\U0001F1FE",fetch_bursa_movers(),".KL")
        except Exception as e: print("Bursa failed:",e); send("\u26A0\uFE0F Bursa movers scan failed (source may have changed).")
    if market in ("US","BOTH"):
        try: run("US","\U0001F1FA\U0001F1F8",fetch_us_movers(),"")
        except Exception as e: print("US failed:",e); send("\u26A0\uFE0F US movers scan failed.")
    print("\nDone.")

if __name__=="__main__":
    main()
