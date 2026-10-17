# MIM FX CRT Analyzer API

A small Flask API scaffold for the MIM FX CRT × MSNR scanner.

## Render settings
- Runtime: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

## Health checks
- `/` — service information
- `/health` — health status
- `/api/fxcm/status` — checks whether ForexConnect and required environment variables are present
- `/api/markets` — intentionally returns HTTP 503 until a real FXCM market-data adapter is implemented and verified

## FXCM integration status
This repository does **not** yet claim to deliver live FXCM prices. ForexConnect's published Python package lists older Python and operating-system requirements, and the sample scripts are not a ready-made web API. We must verify a compatible runtime and a real FXCM demo login before returning live candles.

If broker credentials are later required, configure them as Render environment variables. Never commit passwords, session tokens, or API secrets to GitHub, and never send them in chat.

## Trading logic
CRT/MSNR detection is not implemented in this backend yet. No synthetic prices, fabricated market data, or fake signals are returned.
