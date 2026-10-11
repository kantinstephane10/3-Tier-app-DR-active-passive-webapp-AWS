#!/usr/bin/env python3
"""Render reports/security/*.json as a console table and reports/security/index.html for Jenkins."""
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/security'
ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
# Jenkins serves published HTML with a CSP that blocks CSS, so colour comes from HTML attributes.
COLOURS = {'CRITICAL': '#f4b6b6', 'HIGH': '#f9d3a8', 'MEDIUM': '#fbeaa5', 'LOW': '#d7e9f7'}
COLUMNS = [('Severity', 'severity'), ('Phase', 'phase'), ('Tool', 'tool'), ('Check', 'check_id'),
           ('Title', 'title'), ('File', 'file'), ('Line', 'line'), ('Resource', 'resource')]


def load(reports=REPORTS):
    findings = []
    for path in sorted(reports.glob('*.json')):
        if path.name in ('summary.json', 'approval.json'):
            continue
        phase = json.loads(path.read_text())
        findings += [dict(f, phase=phase['phase']) for f in phase['findings']]
    findings.sort(key=lambda f: (ORDER.index(f['severity']) if f['severity'] in ORDER else 0, f['phase'], f['check_id'], str(f.get('file', ''))))
    summary = json.loads((reports / 'summary.json').read_text()) if (reports / 'summary.json').exists() else {}
    return findings, summary


def cell(finding, key):
    return str(finding.get(key, '') or '')


def console_table(findings, summary):
    counts = summary.get('counts', {})
    lines = ['Security scan: ' + '  '.join(f'{s}={counts.get(s, 0)}' for s in ORDER) +
             f"  (critical findings needing approval: {summary.get('critical_count', 0)})"]
    if not findings:
        return '\n'.join(lines + ['No findings.'])
    columns = [c for c in COLUMNS if c[1] != 'title'] + [('Title', 'title')]
    rows = [[cell(f, key)[:60] for _, key in columns] for f in findings]
    widths = [max(len(title), *(len(r[i]) for r in rows)) for i, (title, _) in enumerate(columns)]
    rule = '+' + '+'.join('-' * (w + 2) for w in widths) + '+'
    fmt = lambda values: '| ' + ' | '.join(v.ljust(w) for v, w in zip(values, widths)) + ' |'
    return '\n'.join(lines + [rule, fmt([t for t, _ in columns]), rule] + [fmt(r) for r in rows] + [rule])


def html_report(findings, summary):
    e = html.escape
    counts = summary.get('counts', {})
    parts = ['<!doctype html><html><head><meta charset="utf-8"><title>Security scan</title></head><body>',
             '<h1>Security scan</h1>',
             f"<p>Phases scanned: {e(', '.join(summary.get('phases', [])) or 'none')}. "
             f"Findings needing approval before APPLY: <b>{summary.get('critical_count', 0)}</b>. "
             'LOW, MEDIUM and HIGH findings continue automatically.</p>',
             '<table border="1" cellpadding="6" cellspacing="0"><tr><th>Severity</th><th>Count</th></tr>']
    parts += [f'<tr><td bgcolor="{COLOURS[s]}">{s}</td><td align="right">{counts.get(s, 0)}</td></tr>' for s in ORDER]
    parts.append('</table><h2>Findings</h2>')
    if not findings:
        parts.append('<p>No findings.</p>')
    else:
        parts.append('<table border="1" cellpadding="6" cellspacing="0"><tr>' +
                     ''.join(f'<th>{t}</th>' for t, _ in COLUMNS) + '<th>Fix</th></tr>')
        for f in findings:
            check = e(cell(f, 'check_id'))
            if f.get('url', '').startswith('https://'):
                check = f'<a href="{e(f["url"])}">{check}</a>'
            row = [f'<td bgcolor="{COLOURS.get(f["severity"], "#ffffff")}"><b>{e(f["severity"])}</b></td>']
            row += [f'<td>{check}</td>' if key == 'check_id' else f'<td>{e(cell(f, key))}</td>' for _, key in COLUMNS[1:]]
            row.append(f'<td>{e(cell(f, "resolution"))}</td>')
            parts.append('<tr>' + ''.join(row) + '</tr>')
        parts.append('</table>')
    parts.append('<p>Code snippets and secret values are never included in this report.</p></body></html>')
    return '\n'.join(parts)


def main(reports=REPORTS):
    if not reports.is_dir():
        print('No security reports yet.')
        return
    findings, summary = load(reports)
    (reports / 'index.html').write_text(html_report(findings, summary), encoding='utf-8')
    print(console_table(findings, summary))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else REPORTS)
