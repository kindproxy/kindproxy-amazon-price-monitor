# Amazon Price Monitoring with Playwright and Residential Proxies

A runnable Python example showing how to monitor a public Amazon product price with **Playwright** and a **KindProxy residential proxy**. It extracts the visible one-time purchase price, checks the ASIN, records the delivery ZIP shown by Amazon, and compares prices across runs **only when the detected ZIP and other comparison keys match**.

> **Demo scope:** Amazon page structure and displayed prices vary by region, session, and product. This example does not sign in, change delivery locations, solve CAPTCHAs, or bypass access controls. Follow the target site's terms and use responsible request rates.

## Features

- Chromium browser automation with an authenticated HTTP/HTTPS residential proxy
- Main product price extraction (using `Decimal` for accurate comparisons)
- Product ASIN and final-host checks
- Read-only detection of the delivery ZIP (never modifies it)
- Append-only observations in `output/observations.jsonl`
- Latest comparable price in `output/baseline.json`
- `first_observation`, `unchanged`, `up`, and `down` results
- Optional screenshot debugging; no proxy credentials in output
- Avoids comparing prices when delivery ZIP is unknown

## Requirements

- Python 3.10+
- A working KindProxy residential proxy with HTTP/HTTPS authentication
- Playwright Chromium and its system dependencies

## Quick start

```bash
git clone https://github.com/kindproxy/kindproxy-amazon-price-monitor.git
cd kindproxy-amazon-price-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install --with-deps chromium
cp .env.example .env
```

Edit `.env` to provide your proxy username and password. **Do not commit `.env`.** Then run:

```bash
python monitor.py
```

On Windows, activate the environment with `.venv\\Scripts\\activate` and use `copy .env.example .env`.

## Configuration

| Variable | Purpose |
|---|---|
| `KP_PROXY_SERVER` | HTTP proxy gateway URL |
| `KP_PROXY_USERNAME` | Proxy username, including any provider-specific session parameters |
| `KP_PROXY_PASSWORD` | Proxy password |
| `AMAZON_URL` | Product URL containing `/dp/ASIN` or `/gp/product/ASIN` |
| `CONTEXT_KEY` | Your own stable product/variant/purchase-type identifier; do not hard-code a ZIP |
| `PRICE_CONTAINER_SELECTOR` | CSS selector for the visible main price |
| `VERIFIED_CURRENCY` | Operator-asserted currency; `USD` for this Amazon.com demo |
| `VERIFIED_SELLER` | Operator-asserted seller; **not** verified from the page |
| `DEBUG` | Set to `1` to save `output/debug-amazon.png` |
| `NAVIGATION_TIMEOUT_MS` | Navigation timeout in milliseconds |
| `OUTPUT_DIR` | Output folder (default `output`) |

**Sticky vs. rotating:** A sticky residential session can help keep the observed region consistent across runs. Rotating proxies can yield different delivery ZIPs; the script keeps comparisons separate by detected ZIP. The proxy credentials determine the session behavior—there is no separate `ROTATING` setting in the script.

## Example output

The following example is based on two successful test runs for ASIN `B0GF9MJY9W`. The price is illustrative and may change:

```json
{
  "status": "success",
  "asin": "B0GF9MJY9W",
  "price": "8.98",
  "currency": "USD",
  "delivery_zip": "19507",
  "delivery_zip_changed_by_script": false,
  "change": "unchanged",
  "previous_price": "8.98",
  "price_delta": "0.00",
  "seller_verified_from_page": false
}
```

The first successful run in a given comparison context returns `first_observation`. A subsequent run with the same product, currency, ZIP, offer type, and `CONTEXT_KEY` can return `unchanged`, `up`, or `down`. If the ZIP cannot be detected, the script records the observation but does not compare it to the baseline.

## Output files

```text
output/
├── observations.jsonl   # All runs, including errors
├── baseline.json        # Latest comparable price by context
└── debug-amazon.png     # Optional; only when DEBUG=1
```

These files are excluded from Git because screenshots and runtime output can contain session-specific information.

## Limitations

- Amazon may change CSS selectors or show regional, promotional, subscription, or alternate offers. The script extracts the visible main price but does **not** fully validate seller, selected variant, or purchase type from the page.
- `VERIFIED_SELLER` is a user assertion, **not** proof of the current offer seller. `offer_type` is currently labeled `one_time` by configuration of this demo, not verified from the page.
- USD identification relies on the configured assertion plus the page's `$` symbol and Amazon.com host.
- ASIN checks are useful guards, not comprehensive offer validation.
- Price changes are only compared within the same detected ZIP and configured context; region alone cannot guarantee identical offers.
- CAPTCHA or access-denied pages are not circumvented. The script records missing page/price errors instead.
- This is a single-product demonstration, not a production monitoring service. Add seller/variant checks, scheduling, alerts, retries, and storage appropriate to your use case before production use.

## Learn more

[KindProxy Residential Proxies](https://www.kindproxy.com/) — Residential proxy solutions for browser automation, testing, and data collection.

## License

MIT. See [LICENSE](LICENSE).
