import os, json, time
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from flask import Flask, jsonify, make_response, request

app = Flask(__name__)
ALLOWED_ORIGINS = {"https://crtanalysiswithmimx.netlify.app", "https://mimfx-crt-scanner.netlify.app"}
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "MIM-FX-CRT-Scanner/1.0"})

@app.after_request
def cors(response):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def preflight(path): return make_response("", 204)

@app.get("/")
def home():
    return jsonify({"service":"MIM FX CRT Analyzer API","status":"online","data_sources":["Yahoo Finance chart feed (FX/crypto/indices where available)","Deriv public market-data WebSocket"],"warning":"Feeds are third-party/public data sources and may differ from broker candles."})

@app.get("/health")
def health(): return jsonify({"ok":True})

def yahoo_symbol(symbol):
    s = symbol.upper().replace("/", "").replace("_", "")
    special = {"BTCUSD":"BTC-USD","ETHUSD":"ETH-USD","XAUUSD":"GC=F","XAGUSD":"SI=F","US30":"^DJI","NAS100":"^NDX","SPX500":"^GSPC"}
    if s in special: return special[s]
    if len(s)==6 and s.isalpha(): return s+"=X"
    if "-" in symbol: return symbol
    return s

def get_yahoo_candles(symbol, interval, range_):
    ticker = yahoo_symbol(symbol)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/"+quote(ticker, safe="=^.-")
    r = HTTP.get(url, params={"interval":interval,"range":range_}, timeout=12)
    r.raise_for_status()
    data = r.json()["chart"]
    if data.get("error") or not data.get("result"): raise ValueError("No Yahoo Finance candles for "+symbol)
    result=data["result"][0]; q=result["indicators"]["quote"][0]; ts=result.get("timestamp",[])
    candles=[]
    for i,t in enumerate(ts):
        vals=[q.get(k,[])[i] if i<len(q.get(k,[])) else None for k in ("open","high","low","close")]
        if all(v is not None for v in vals):
            candles.append({"time":t,"open":float(vals[0]),"high":float(vals[1]),"low":float(vals[2]),"close":float(vals[3])})
    if len(candles)<30: raise ValueError("Insufficient candle history for "+symbol)
    return candles, ticker

def get_deriv_candles(symbol, granularity, count=300):
    # Deriv's public market-data WebSocket; no trading/account authorization is requested.
    try:
        import websocket
    except ImportError as e: raise ValueError("Deriv WebSocket dependency unavailable") from e
    ws=websocket.create_connection("wss://ws.derivws.com/websockets/v3?app_id=1089", timeout=12)
    try:
        ws.send(json.dumps({"ticks_history":symbol,"adjust_start_time":1,"count":count,"end":"latest","granularity":granularity,"style":"candles"}))
        deadline=time.time()+12
        while time.time()<deadline:
            msg=json.loads(ws.recv())
            if "error" in msg: raise ValueError(msg["error"].get("message","Deriv data error"))
            if "candles" in msg:
                return [{"time":int(c["epoch"]),"open":float(c["open"]),"high":float(c["high"]),"low":float(c["low"]),"close":float(c["close"])} for c in msg["candles"]], symbol
        raise ValueError("Deriv candle request timed out")
    finally: ws.close()

TIMEFRAMES={"W1":("1wk","2y",604800),"D1":("1d","1y",86400),"H4":("1h","60d",14400),"H2":("1h","60d",7200),"H1":("1h","60d",3600),"M30":("30m","60d",1800),"M15":("15m","60d",900)}
def fetch(symbol, tf, source):
    if source=="DERIV":
        gran={"W1":604800,"D1":86400,"H4":14400,"H2":7200,"H1":3600,"M30":1800,"M15":900}[tf]
        return get_deriv_candles(symbol,gran)
    interval,period,_=TIMEFRAMES[tf]
    # Yahoo does not support 4h bars directly; aggregate hourly candles into requested intervals.
    candles,ticker=get_yahoo_candles(symbol,interval,period)
    if tf in ("H4","H2"):
        step=4 if tf=="H4" else 2
        out=[]
        for i in range(0,len(candles)-step+1,step):
            chunk=candles[i:i+step]
            if len(chunk)!=step: continue
            out.append({"time":chunk[0]["time"],"open":chunk[0]["open"],"high":max(x["high"] for x in chunk),"low":min(x["low"] for x in chunk),"close":chunk[-1]["close"]})
        candles=out
    return candles,ticker

def body_bos(candles, lookback=12):
    if len(candles)<lookback+2:return None
    prev=candles[-lookback-1:-1]; last=candles[-1]
    prior_high=max(c["high"] for c in prev); prior_low=min(c["low"] for c in prev)
    if last["close"]>prior_high and last["close"]>last["open"]: return {"direction":"BULLISH","level":prior_high,"close":last["close"]}
    if last["close"]<prior_low and last["close"]<last["open"]: return {"direction":"BEARISH","level":prior_low,"close":last["close"]}
    return None

def crt_setup(candles):
    # Conservative CRT candidate: sweep a prior range edge then close back inside it.
    if len(candles)<20:return None
    ref=candles[-2]
    window=candles[-20:-2]
    top=max(c["high"] for c in window); bottom=min(c["low"] for c in window)
    last=candles[-1]
    if last["high"]>top and last["close"]<top and last["close"]<last["open"]:
        direction="BEARISH"; edge=top
    elif last["low"]<bottom and last["close"]>bottom and last["close"]>last["open"]:
        direction="BULLISH"; edge=bottom
    else:return None
    # Candidate key-level proximity: prior range boundary, FVG/imbalance (3-candle gap), QM-like swing.
    key=[]
    if abs(last["close"]-edge) <= max(last["high"]-last["low"],edge*0.0005): key.append("CRT range edge rejection")
    a,b=candles[-3],candles[-1]
    if direction=="BULLISH" and b["low"]>a["high"]: key.append("Bullish FVG / imbalance")
    if direction=="BEARISH" and b["high"]<a["low"]: key.append("Bearish FVG / imbalance")
    if not key: key.append("Range-edge rejection")
    return {"direction":direction,"range_level":round(edge,8),"key_levels":key,"candle_time":last["time"]}

@app.get("/api/markets")
def markets():
    source=request.args.get("source","FXCM").upper()
    symbols=request.args.get("symbols","EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,XAUUSD,BTCUSD,ETHUSD").split(",")
    tf=request.args.get("timeframe","D1").upper()
    if tf not in TIMEFRAMES:return jsonify({"connected":False,"markets":[],"message":"Unsupported timeframe"}),400
    result=[]; errors=[]
    for symbol in symbols[:40]:
        symbol=symbol.strip().upper()
        try:
            candles,provider=fetch(symbol,tf,"DERIV" if source=="DERIV" else "FX")
            result.append({"symbol":symbol,"provider_symbol":provider,"timeframe":tf,"last_price":candles[-1]["close"],"candles":candles[-300:]})
        except Exception as e: errors.append({"symbol":symbol,"error":str(e)[:180]})
    return jsonify({"connected":bool(result),"source":source,"markets":result,"errors":errors,"message":"Live candles retrieved from available public feed." if result else "No candles retrieved. Check feed availability or provider symbol."}), (200 if result else 503)

@app.get("/api/scan")
def scan():
    source=request.args.get("source","FXCM").upper()
    selected=request.args.get("timeframes","W1,D1,H4").upper().split(",")
    symbols=request.args.get("symbols","EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,XAUUSD,BTCUSD,ETHUSD").split(",")
    setups=[]; errors=[]
    for symbol in symbols[:40]:
        symbol=symbol.strip().upper()
        for tf in [x for x in selected if x in ("W1","D1","H4")]:
            try:
                candles,_=fetch(symbol,tf,"DERIV" if source=="DERIV" else "FX")
                candidate=crt_setup(candles)
                if not candidate: continue
                confirm={"W1":["D1"],"D1":["H4","H2","H1"],"H4":["H1","M30","M15"]}[tf]
                confirmed=[]
                for lower in confirm:
                    try:
                        low_candles,_=fetch(symbol,lower,"DERIV" if source=="DERIV" else "FX")
                        bos=body_bos(low_candles)
                        if bos and bos["direction"]==candidate["direction"]: confirmed.append({"timeframe":lower,**bos})
                    except Exception as e: errors.append({"symbol":symbol,"timeframe":lower,"error":str(e)[:100]})
                if not confirmed: continue
                setups.append({"symbol":symbol,"source":source,"crt_timeframe":tf,"direction":candidate["direction"],"key_levels":candidate["key_levels"],"range_level":candidate["range_level"],"confirmations":confirmed,"quality":"Body-close BOS + range-edge rejection","candle_time":candidate["candle_time"]})
            except Exception as e: errors.append({"symbol":symbol,"timeframe":tf,"error":str(e)[:120]})
    return jsonify({"connected":bool(setups) or not errors,"source":source,"setups":setups,"errors":errors,"scanned_symbols":symbols[:40],"message":"Scan complete. No qualifying CRTs found." if not setups else "Scan complete."})

@app.get("/api/fxcm/status")
def fxcm_status():
    return jsonify({"connected":False,"sdk_available":False,"credentials_configured":False,"message":"This build uses a public third-party candle adapter for FX instruments, not authenticated FXCM broker data. Candle prices may differ from FXCM TradingView feed."})

if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
