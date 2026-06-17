# KYC Mock (Eastern Bank demo)

Deploy to Render free tier:
1. Push this folder to a GitHub repo (or a subfolder of your demo repo).
2. Render dashboard -> New -> Blueprint -> point at the repo (render.yaml is auto-detected).
   Or: New -> Web Service -> runtime Python, build `pip install -r requirements.txt`,
   start `uvicorn main:app --host 0.0.0.0 --port $PORT`, plan Free.
3. Note the public URL, e.g. https://eastern-kyc-mock.onrender.com

Smoke test:
    curl -X POST https://<your-url>/v1/verify \
      -H "Content-Type: application/json" \
      -d '{"firstName":"Sarah","lastName":"Lee","email":"sarah@example.com"}'
    # -> {"result":"Fail","declineCode":"ID_MISMATCH",...}

Live demo controls:
    curl -X POST https://<your-url>/admin/mode/manual   # force Manual Review
    curl -X POST https://<your-url>/admin/mode/error    # force 503 (resilience path)
    curl -X POST https://<your-url>/admin/mode/fail     # back to default

Or use email plus-addressing per request: sarah+pass@..., sarah+manual@..., sarah+error@...

Note: Render free tier sleeps after ~15 min idle and cold-starts in ~30-60s.
Hit the health endpoint (GET /) 5 minutes before the demo to warm it up.
