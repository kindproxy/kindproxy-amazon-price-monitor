#!/usr/bin/env python3
"""Amazon price monitoring demo with Playwright and KindProxy.

No ZIP changes, login, CAPTCHA solving, or access-control bypass.
Install: pip install playwright python-dotenv && python -m playwright install chromium
Run: python monitor.py
"""
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv(Path(__file__).resolve().parent / '.env')

def cfg(key, default=''):
    return os.getenv(key, default).strip()

OUT = Path(cfg('OUTPUT_DIR', 'output'))
OUT.mkdir(parents=True, exist_ok=True)
DEBUG = cfg('DEBUG', '0').lower() in ('1', 'true', 'yes')
PRICE_SELECTOR = cfg('PRICE_CONTAINER_SELECTOR', '#corePriceDisplay_desktop_feature_div .priceToPay')
ZIP_SELECTORS = ('#contextualIngressPtLabel_deliveryShortLine', '#contextualIngressPtLabel', '#glow-ingress-block')


def save_debug(page, result, filename='debug-amazon.png'):
    if not DEBUG:
        return
    try:
        path = OUT / filename
        page.screenshot(path=str(path), full_page=True, timeout=10000)
        result['debug_screenshot'] = str(path)
    except Exception as exc:
        result['debug_screenshot_error'] = type(exc).__name__


def get_price(page):
    """Read first visible *main* one-time price; ignore hidden alternate offers."""
    selectors = [PRICE_SELECTOR, '#apex_desktop .priceToPay', '#corePrice_feature_div .priceToPay']
    for selector in dict.fromkeys(selectors):
        locator = page.locator(selector)
        for i in range(min(locator.count(), 12)):
            item = locator.nth(i)
            try:
                if not item.is_visible():
                    continue
                # inner_text avoids the duplicate hidden a-offscreen values.
                raw = item.inner_text(timeout=2000)
                normalized = re.sub(r'\s+', '', raw)
                match = re.search(r'([$€£])([\d,]+(?:\.\d{1,2})?)', normalized)
                if not match:
                    continue
                amount = Decimal(match.group(2).replace(',', ''))
                if amount <= 0:
                    continue
                return {'price': str(amount.quantize(Decimal('0.01'))),
                        'currency_symbol': match.group(1),
                        'price_source': selector, 'raw_price': raw.strip()[:100]}
            except Exception:
                continue
    return None


def get_zip(page):
    evidence = []
    for selector in ZIP_SELECTORS:
        try:
            el = page.locator(selector).first
            if not el.count():
                continue
            txt = ' '.join(el.inner_text(timeout=2000).split())
            if txt:
                evidence.append({'selector': selector, 'text': txt[:150]})
        except Exception:
            continue
    codes = []
    for item in evidence:
        for code in re.findall(r'(?<!\d)\d{5}(?:-\d{4})?(?!\d)', item['text']):
            code = code[:5]
            if code not in codes:
                codes.append(code)
    return codes, evidence


def detect_asin(page, expected):
    candidates = []
    for selector in ('#ASIN', 'input[name="ASIN"]', 'input[name="asin"]'):
        try:
            el = page.locator(selector).first
            if el.count():
                value = el.get_attribute('value')
                if value and re.fullmatch(r'[A-Z0-9]{10}', value):
                    candidates.append(value)
        except Exception:
            pass
    path = urlparse(page.url).path
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', path, re.I)
    if match:
        candidates.append(match.group(1).upper())
    return expected in candidates, sorted(set(candidates))


def load_baseline():
    path = OUT / 'baseline.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def update_history(row):
    """Compare only observations sharing product, currency and detected delivery ZIP."""
    if row['status'] != 'success':
        row['change'] = 'not_compared'
        return
    zip_code = row.get('delivery_zip')
    if not zip_code:
        row['change'] = 'not_compared_location_unknown'
        return
    key = '|'.join((row['asin'], row['currency'], zip_code,
                    row.get('offer_type', 'one_time'), row.get('context_key', '')))
    baseline = load_baseline()
    previous = baseline.get(key)
    current = Decimal(row['price'])
    if previous:
        try:
            old = Decimal(previous['price'])
            row['previous_price'] = str(old)
            row['change'] = 'up' if current > old else ('down' if current < old else 'unchanged')
            row['price_delta'] = str(current - old)
        except (KeyError, InvalidOperation, TypeError):
            row['change'] = 'first_observation'
    else:
        row['change'] = 'first_observation'
    baseline[key] = {'price': row['price'], 'checked_at': row['checked_at']}
    temp = OUT / 'baseline.json.tmp'
    temp.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(OUT / 'baseline.json')


def monitor(page, url, asin):
    row = {'checked_at': datetime.now(timezone.utc).isoformat(),
           'product_url': url, 'asin': asin,
           'context_key': cfg('CONTEXT_KEY'),
           'status': 'unknown', 'price': None, 'currency': None,
           'offer_type': 'one_time', 'change': 'not_compared'}
    response = None
    try:
        try:
            response = page.goto(url, wait_until='domcontentloaded',
                                 timeout=int(cfg('NAVIGATION_TIMEOUT_MS', '60000')))
        except PlaywrightTimeoutError:
            row['navigation_timed_out'] = True
            # Some pages are usable even if DOMContentLoaded times out.
        row['http_status'] = response.status if response else None
        row['final_host'] = urlparse(page.url).hostname
        if row['final_host'] not in ('www.amazon.com', 'amazon.com'):
            row['status'] = 'unexpected_host'
            return row
        try:
            page.locator('#productTitle').first.wait_for(state='visible', timeout=15000)
        except PlaywrightTimeoutError:
            row['status'] = 'navigation_timeout' if row.get('navigation_timed_out') else 'product_page_missing'
            save_debug(page, row)
            return row
        row['title'] = ' '.join(page.locator('#productTitle').first.inner_text().split())[:250]
        verified, detected = detect_asin(page, asin)
        row['detected_asins'] = detected
        if not verified:
            row['status'] = 'asin_mismatch'
            save_debug(page, row)
            return row
        row['detected_delivery_zips'], row['delivery_page_evidence'] = get_zip(page)
        row['delivery_zip'] = (row['detected_delivery_zips'][0]
                               if len(row['detected_delivery_zips']) == 1 else None)
        row['delivery_zip_changed_by_script'] = False
        # These values are user assertions, not proof from the page.
        row['operator_asserted_seller'] = cfg('VERIFIED_SELLER') or None
        row['seller_verified_from_page'] = False
        row['operator_asserted_currency'] = cfg('VERIFIED_CURRENCY') or None
        try:
            page.locator(PRICE_SELECTOR).first.wait_for(state='visible', timeout=12000)
        except PlaywrightTimeoutError:
            pass
        found = get_price(page)
        if not found:
            row['status'] = 'price_missing'
            save_debug(page, row)
            return row
        row.update(found)
        symbol_currency = {'$': 'USD', '€': 'EUR', '£': 'GBP'}.get(found['currency_symbol'])
        asserted = cfg('VERIFIED_CURRENCY').upper()
        # A '$' symbol alone is ambiguous. On amazon.com, allow USD if explicitly asserted.
        if asserted and asserted == symbol_currency and row['final_host'] in ('amazon.com', 'www.amazon.com'):
            row['currency'] = asserted
            row['currency_source'] = 'operator_asserted_with_page_symbol'
        elif found['currency_symbol'] in ('€', '£'):
            row['currency'] = symbol_currency
            row['currency_source'] = 'page_symbol'
        else:
            row['status'] = 'currency_unverified'
            save_debug(page, row)
            return row
        row['status'] = 'success'
        save_debug(page, row)
        return row
    except Exception as exc:
        row['status'] = 'error'
        row['error_type'] = type(exc).__name__
        # Never print proxy URLs or credentials from exception messages.
        save_debug(page, row)
        return row


def main():
    url = cfg('AMAZON_URL', 'https://www.amazon.com/dp/B0GF9MJY9W')
    match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})', url, re.I)
    if not match:
        raise SystemExit('AMAZON_URL must contain /dp/ASIN or /gp/product/ASIN')
    asin = match.group(1).upper()
    proxy_server = cfg('KP_PROXY_SERVER')
    proxy_username = cfg('KP_PROXY_USERNAME')
    proxy_password = cfg('KP_PROXY_PASSWORD')
    if not all((proxy_server, proxy_username, proxy_password)):
        raise SystemExit('Set KP_PROXY_SERVER, KP_PROXY_USERNAME and KP_PROXY_PASSWORD in .env')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, proxy={
            'server': proxy_server, 'username': proxy_username, 'password': proxy_password})
        try:
            context = browser.new_context(locale='en-US', timezone_id='America/New_York')
            try:
                page = context.new_page()
                row = monitor(page, url, asin)
            finally:
                context.close()
        finally:
            browser.close()
    update_history(row)
    with (OUT / 'observations.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
