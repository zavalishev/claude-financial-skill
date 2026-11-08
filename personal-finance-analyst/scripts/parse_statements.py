#!/usr/bin/env python3
"""Читает банковские выписки и сводит все операции в один файл ops.json.

  python3 parse_statements.py ВЫПИСКА1.pdf ВЫПИСКА2.csv … --out work/

Поддерживает:
  • PDF-выписки Сбера (СберБанк Онлайн: дебетовые карты, платёжный счёт, кредитка) — через pdftotext -layout;
  • CSV / XLSX любых банков с колонками «дата», «сумма», «описание» (Т-Банк, Альфа, ВТБ, выгрузки приложений).
Для других PDF скрипт честно скажет, что не распознал, — тогда Claude читает такой PDF сам.

Пишет: ops.json (операции), accounts.json (шапки выписок и сверка итогов).
"""
import argparse, csv, json, re, shutil, subprocess, sys
from pathlib import Path

HEAD = re.compile(r'^\s*(\d\d\.\d\d\.\d{4})\s+(\d\d:\d\d)\s+(.+?)\s{2,}(\+?[\d ]+,\d\d)\s+([\d ]+,\d\d)\s*$')
SKIP = ('Продолжение', 'Страница', 'ДАТА ОПЕРАЦИИ', 'Дата обработки', 'и код авторизации', 'Описание операции',
        'Расшифровка', 'Выписка')


def money(s: str) -> float:
    return float(s.replace('\u00a0', '').replace(' ', '').replace('+', '').replace(',', '.'))


def pdf_text(path: Path) -> str:
    if shutil.which('pdftotext'):
        return subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True).stdout
    try:
        import pypdf
    except ImportError:
        sys.exit('Нужен pdftotext (brew install poppler / apt install poppler-utils) или pip install pypdf')
    return '\n'.join(p.extract_text() or '' for p in pypdf.PdfReader(str(path)).pages)


def parse_sber_pdf(path: Path):
    text = pdf_text(path)
    L = text.splitlines()
    head = {'file': path.name, 'bank': 'Сбер', 'format': 'sber-pdf'}
    for key, rx in [('title', r'(Выписка по [^\n]+)'), ('period', r'За период\s+([\d.]+\s*—\s*[\d.]+)'),
                    ('owner', r'Владелец счёта\s*\n\s*([^\n]+?)\s{2,}|Владелец счёта\s*\n\s*([^\n]+)'),
                    ('income', r'Пополнение\s+([\d ]+,\d\d)'), ('outcome', r'Списание\s+([\d ]+,\d\d)'),
                    ('rate', r'Процентная ставка\s+([\d.,]+%)'), ('grace', r'Льготный период\s+([^\n]+)'),
                    ('limit', r'Кредитный лимит\s+([\d ]+,\d\d)')]:
        m = re.search(rx, text)
        if m:
            v = next(g for g in m.groups() if g)
            head[key] = v.strip()
    if 'title' not in head:
        return None, None
    kind = 'кредитка' if 'кредитной' in head['title'] else ('платёжный счёт' if 'платёжному' in head['title'] else 'дебетовая карта')
    head['account'] = kind
    ops, i = [], 0
    while i < len(L):
        m = HEAD.match(L[i])
        if not m:
            i += 1
            continue
        d, t, cat, amt, bal = m.groups()
        desc, j = [], i + 1
        while j < len(L) and not HEAD.match(L[j]) and len(desc) < 3:
            s = L[j].strip()
            if not s or s.startswith(SKIP):
                if desc:
                    break
                j += 1
                continue
            desc.append(re.sub(r'^\d\d\.\d\d\.\d{4}\s+\d+\s+', '', s))
            j += 1
        v = money(amt) * (1 if amt.startswith('+') else -1)
        ops.append(dict(account=kind, file=path.name, date=d, time=t, bank_category=cat.strip(), amount=round(v, 2),
                        balance=money(bal), description=' '.join(desc)))
        i = j
    inc = round(sum(o['amount'] for o in ops if o['amount'] > 0), 2)
    out = round(-sum(o['amount'] for o in ops if o['amount'] < 0), 2)
    head['check'] = {'parsed_income': inc, 'parsed_outcome': out,
                     'ok': ('income' not in head or abs(money(head['income']) - inc) < 1) and
                           ('outcome' not in head or abs(money(head['outcome']) - out) < 1)}
    return ops, head


COLS = {'date': ['дата операции', 'дата', 'date'], 'time': ['время', 'time'],
        'amount': ['сумма операции', 'сумма платежа', 'сумма', 'amount', 'сумма в валюте счёта', 'сумма в рублях'],
        'description': ['описание', 'назначение', 'получатель', 'контрагент', 'description', 'merchant'],
        'category': ['категория', 'category'], 'status': ['статус', 'status']}


def pick(header, names):
    low = [h.strip().lower() for h in header]
    for n in names:
        for i, h in enumerate(low):
            if h == n or h.startswith(n):
                return i
    return None


def rows_from_table(path: Path):
    if path.suffix.lower() in ('.xlsx', '.xls'):
        try:
            import openpyxl
        except ImportError:
            sys.exit('Для Excel нужен pip install openpyxl')
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        return [[('' if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
    raw = path.read_bytes()
    for enc in ('utf-8-sig', 'cp1251'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    dialect = csv.Sniffer().sniff(text[:4000], delimiters=';,\t')
    return list(csv.reader(text.splitlines(), dialect))


def parse_table(path: Path):
    rows = [r for r in rows_from_table(path) if any(c.strip() for c in r)]
    hi = next((k for k, r in enumerate(rows[:15]) if pick(r, COLS['date']) is not None and pick(r, COLS['amount']) is not None), None)
    if hi is None:
        return None, None
    h = rows[hi]
    idx = {k: pick(h, v) for k, v in COLS.items()}
    ops = []
    for r in rows[hi + 1:]:
        try:
            amt = money(r[idx['amount']])
        except (ValueError, IndexError, TypeError):
            continue
        if idx['status'] is not None and r[idx['status']].strip().lower() in ('failed', 'отклонено', 'отменено'):
            continue
        dt = r[idx['date']].strip()
        m = re.match(r'(\d\d)\.(\d\d)\.(\d{4})(?:\s+(\d\d:\d\d))?', dt) or re.match(r'(\d{4})-(\d\d)-(\d\d)(?:[ T](\d\d:\d\d))?', dt)
        if not m:
            continue
        g = m.groups()
        date = f'{g[0]}.{g[1]}.{g[2]}' if len(g[0]) == 2 else f'{g[2]}.{g[1]}.{g[0]}'
        time = g[3] or (r[idx['time']].strip()[:5] if idx['time'] is not None else '00:00')
        ops.append(dict(account=path.stem, file=path.name, date=date, time=time,
                        bank_category=r[idx['category']].strip() if idx['category'] is not None else '',
                        amount=round(amt, 2), balance=None,
                        description=r[idx['description']].strip() if idx['description'] is not None else ''))
    return ops, {'file': path.name, 'format': 'table', 'account': path.stem, 'columns': h}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--out', default='work')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    all_ops, heads = [], []
    for f in map(Path, a.files):
        ops, head = (parse_sber_pdf(f) if f.suffix.lower() == '.pdf' else parse_table(f))
        if ops is None:
            print(f'НЕ РАСПОЗНАН: {f.name} — прочитай его сам и добавь операции в ops.json в том же формате')
            continue
        all_ops += ops
        heads.append(head)
        chk = head.get('check', {})
        print(f"{f.name}: {len(ops)} операций" + (f" · сверка с шапкой: {'OK' if chk.get('ok') else 'НЕ СОШЛОСЬ'}" if chk else ''))
    json.dump(all_ops, open(out / 'ops.json', 'w'), ensure_ascii=False, indent=0)
    json.dump(heads, open(out / 'accounts.json', 'w'), ensure_ascii=False, indent=1)
    print(f'всего {len(all_ops)} операций → {out / "ops.json"}')


if __name__ == '__main__':
    main()
