import os
from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify({
        "service": "MIM FX CRT Analyzer API",
        "status": "online",
        "message": "Backend is running. FXCM market-data adapter is not configured yet."
    })

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/api/fxcm/status")
def fxcm_status():
    # Do not claim a broker connection until a compatible ForexConnect runtime
    # and broker-issued credentials have actually been configured.
    required = ["FXCM_USERNAME", "FXCM_PASSWORD", "FXCM_CONNECTION"]
    missing = [key for key in required if not os.getenv(key)]
    try:
        import forexconnect  # noqa: F401
        sdk_available = True
    except Exception:
        sdk_available = False

    return jsonify({
        "connected": False,
        "sdk_available": sdk_available,
        "credentials_configured": len(missing) == 0,
        "missing_environment_variables": missing,
        "message": (
            "FXCM SDK is available, but a live session has not been implemented or verified."
            if sdk_available else
            "ForexConnect SDK is not installed in this runtime. Its published Python package targets older Python versions, so compatibility must be solved before enabling live FXCM data."
        )
    }), 200

@app.get("/api/markets")
def markets():
    return jsonify({
        "connected": False,
        "source": "FXCM",
        "markets": [],
        "message": "Live market data is not enabled yet; no prices or signals are being fabricated."
    }), 503

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
