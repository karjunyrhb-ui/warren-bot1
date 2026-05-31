import os,json,time,requests,yfinance as yf
from datetime import datetime,timezone
TOKEN=os.environ["TELEGRAM_TOKEN"];CHAT=os.environ["TELEGRAM_CHAT_ID"]
WL={"US":[("KO","Coca-Cola"),("AAPL","Apple"),("MCO","Moody's"),("AXP","American Express"),("JNJ","J&J"),("BRK-B","Berkshire")],
"HK":[("0388.HK","HK Exchanges"),("0700.HK","Tencent"),("1299.HK","AIA"),("0005.HK","HSBC"),("9988.HK","Alibaba")],
"MY":[("MAYBANK.KL","Maybank"),("PBBANK.KL","Public Bank"),("TENAGA.KL","Tenaga"),("PCHEM.KL","Petronas Chem"),("HARTA.KL","Hartalega")]}
def grab(t):
 try:
  s=yf.Ticker(t);i=s.info;h=s.history(period="1y")
  if h.empty or len(h)<50:return None
  c=h["Close"];p=float(c.iloc[-1]);m50=float(c.tail(50).mean());m200=float(c.tail(200).mean()) if len(c)>=200 else float(c.mean())
  tr="UPTREND" if p>m50>m200 else "DOWNTREND" if p<m50<m200 else "RECOVERING" if p>m200 else "WEAK"
  roe=round((i.get("returnOnEquity") or 0)*100,1);nm=round((i.get("profitMargins") or 0)*100,1)
  pe=round(i.get("trailingPE") or 0,1);de=round(i.get("debtToEquity") or 0,2);pv=round((p-m200)/m200*100,1)
  mo=0;nt=[]
  if roe>20:mo+=25;nt.append("excellent ROE")
  elif roe>12:mo+=15;nt.append("good ROE")
  if nm>20:mo+=25;nt.append("wide margins")
  elif nm>10:mo+=15;nt.append("decent margins")
  if 0<pe<25:mo+=15;nt.append("fair value")
  if de<100:mo+=20;nt.append("low debt")
  elif de<200:mo+=10
  if tr in("UPTREND","RECOVERING"):mo+=15
  ts={"UPTREND":100,"RECOVERING":70,"WEAK":40,"DOWNTREND":10}[tr]
  return{"roe":roe,"nm":nm,"pe":pe,"de":de,"pv":pv,"tr":tr,"sc":round(mo*0.6+ts*0.4),"nt":", ".join(nt) or "limited moat"}
 except Exception as e:print("  warn",t,e);return None
def send(msg):
 r=requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",json={"chat_id":CHAT,"text":msg,"parse_mode":"HTML"},timeout=10)
 if not r.ok:print("  TG error:",r.text)
TE={"UPTREND":"\U0001F4C8","RECOVERING":"\U0001F504","WEAK":"\u26A0\uFE0F","DOWNTREND":"\U0001F4C9"}
res=[]
for mk,sts in WL.items():
 print("--",mk,"--")
 for t,nm in sts:
  print("  ",t,end=" ",flush=True);d=grab(t)
  if not d:print("skip");continue
  print("sc=%d %s"%(d["sc"],d["tr"]));res.append((t,nm,mk,d))
res.sort(key=lambda x:x[3]["sc"],reverse=True)
now=datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
L=["\U0001F3A9 <b>Warren's Buffett Screen</b>\n\U0001F4C5 "+now+"\n","\U0001F3C6 <b>Top 3:</b>"]
for i,(t,nm,mk,d) in enumerate(res[:3]):
 L.append("%s <b>%s</b> %s [%s]\n   %s %s \u00b7 %d/100 \u00b7 %s"%(["\U0001F947","\U0001F948","\U0001F949"][i],t,nm,mk,TE[d["tr"]],d["tr"],d["sc"],d["nt"]))
buys=[t for t,_,_,d in res if d["sc"]>=75];holds=[t for t,_,_,d in res if 55<=d["sc"]<75];av=[t for t,_,_,d in res if d["sc"]<55]
if buys:L.append("\n\U0001F7E2 <b>Buy zone</b>: "+", ".join(buys))
if holds:L.append("\U0001F7E1 <b>Watch</b>: "+", ".join(holds))
if av:L.append("\U0001F534 <b>Avoid</b>: "+", ".join(av))
L.append("\n<i>Screened on moat, balance sheet, value & trend</i>")
send("\n".join(L))
print("\nDone. Sent",len(res),"stocks to Telegram.")
