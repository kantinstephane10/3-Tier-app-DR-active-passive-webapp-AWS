#!/usr/bin/env python3
import http.cookiejar
import json
import time
import urllib.error
import urllib.request
import uuid

def smoke(base, region, release, active):
    if not base.startswith('https://'):
        raise ValueError('Smoke URL must use HTTPS')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, payload=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(base.rstrip('/') + path, data=data, headers=headers or {})
        try:
            with opener.open(req, timeout=15) as response:
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
