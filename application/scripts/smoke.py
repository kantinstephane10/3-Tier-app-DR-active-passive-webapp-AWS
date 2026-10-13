#!/usr/bin/env python3
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
import uuid
import sys

def smoke(base, region, release, active, allow_loopback=False):
    local = allow_loopback and base == 'http://127.0.0.1'
    if not base.startswith('https://') and not local:
        raise ValueError('Smoke URL must use HTTPS')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    cookie = None
    def request(path, payload=None, headers=None):
        nonlocal cookie
        data = json.dumps(payload).encode() if payload is not None else None
        headers = dict(headers or {})
        # Production browser cookies remain Secure. This synthetic test explicitly
        # forwards its own guest cookie only to loopback on the SSM-managed web host.
        if local and cookie:
            headers['Cookie'] = cookie
        req = urllib.request.Request(base.rstrip('/') + path, data=data, headers=headers)
        try:
            with opener.open(req, timeout=15) as response:
                if local and response.headers.get('Set-Cookie'):
                    cookie = response.headers['Set-Cookie'].split(';')[0]
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    status, runtime = request('/api/status')
    assert status == 200 and runtime['region'] == region and runtime['release'] == release, 'Wrong region/release'
    assert runtime['writable'] is active, 'Unexpected write mode'
    status, _ = request('/health/ready')
    assert status == (200 if active else 503), 'Readiness mismatch'
    status, session = request('/api/session')
    assert status == 200
    headers = {'Content-Type': 'application/json', 'X-CSRF-Token': session['csrfToken'], 'Idempotency-Key': str(uuid.uuid4())}
    payload = {'items': [{'productId': 'sticker-pack', 'quantity': 1}]}
    status, first = request('/api/orders', payload, headers)
    if not active:
        assert status == 503, 'Standby accepted a write'
        print('Standby smoke passed: catalog reachable, writes rejected')
        return
    assert status == 201 and first['order']['totalCents'] == 1200, 'Checkout failed'
    status, replay = request('/api/orders', payload, headers)
    assert status == 200 and replay['order']['id'] == first['order']['id'], 'Retry duplicated an order'
    for attempt in range(20):
        status, detail = request('/api/orders/' + first['order']['id'])
        if status == 200 and detail['order']['status'] == 'FULFILLED':
            print('Active smoke passed: database write, idempotent retry and worker fulfillment')
            return
        time.sleep(2)
    raise RuntimeError('Worker did not fulfill the smoke order')

if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[3] not in ['active', 'standby']:
        raise SystemExit('Usage: kantin-smoke REGION RELEASE active|standby')
    smoke('http://127.0.0.1', sys.argv[1], sys.argv[2], sys.argv[3] == 'active', allow_loopback=True)
