#!/usr/bin/env python3
"""Разбирает операции из ops.json: отделяет оборот от настоящих трат и считает всё, на чём строятся выводы.

  python3 analyze.py work/ [--self "И. Иван Иванович"] [--rules ../references/category_rules.json]
                     [--saving-rate 13] [--scale 1]

Пишет work/analysis.json. Ничего не отправляет в сеть.
  --self        имя владельца так, как банк пишет его в переводах (можно несколько раз). Из шапки PDF Сбера берётся само.
  --saving-rate ставка накопительного счёта для расчёта «денег без работы», % годовых.
  --scale       поделить все суммы на N (демо-версия для публикации: закономерности те же, суммы меньше).
"""
import argparse, collections, datetime as dt, json, re, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_rules(p):
    r = json.load(open(p))
    comp = lambda xs: [re.compile(x, re.I) for x in xs]
    return {
        'own': comp(r['own_transfer']), 'cash': comp(r['cash']), 'income': comp(r['income']), 'invest': comp(r['invest']),
        'other_bank': comp(r['other_bank']), 'unclear': comp(r['unclear']), 'people': comp(r['people']),
        'cats': [(n, re.compile(x, re.I)) for n, x in r['categories']], 'fallback': r['bank_category_fallback'],
        'deduct': {n: re.compile(x, re.I) for n, x in r['deductible'].items()}, 'leaks': set(r['small_leaks']),
    }


def self_patterns(accounts, extra):
    names = list(extra)
    for a in accounts:
        o = a.get('owner')
        if o and len(o.split()) == 3:
            f, i, ot = o.split()
            names += [f'{f[0]}. {i} {ot}', o]
    return [re.compile(re.escape(n), re.I) for n in names]


def when(o):
    return dt.datetime.strptime(f"{o['date']} {o['time'] or '00:00'}", '%d.%m.%Y %H:%M')


CITY = re.compile(r'\b(MOSCOW|MOSKVA|MOSCOW REG|SANKT-PETERBU\w*|ST PETERSBURG|SPB|KAZAN|EKATERINBURG|NOVOSIBIRSK|RUS|RU|G\.|Г\.)\b', re.I)


def merchant(desc):
    """Название продавца без города, страны, номеров карт — чтобы одно место не дробилось на несколько."""
    d = re.sub(r'\. ?Операция по (карте|счету).*$|Покупка по СБП.*$', '', desc)
    d = re.sub(r'\*{2,}\d+|\d{4,}', '#', d)
    d = CITY.sub(' ', d)
    return re.sub(r'\s+', ' ', d).strip(' .#')[:48]


def classify(o, R, selfp):
    d, c, a = o['description'], o['bank_category'], o['amount']
    if any(p.search(d) for p in selfp):
        return 'own', 'свои переводы'
    if any(p.search(d) for p in R['own']):
        return 'own', 'свои переводы и вклады'
    if any(p.search(d) for p in R['cash']) or c in ('Выдача наличных', 'Внесение наличных'):
        return 'cash', 'наличные'
    if a > 0:
        if any(p.search(d) for p in R['income']) or c.startswith('Возврат'):
            return 'income', 'доход и возвраты'
        if any(p.search(d) for p in R['people']):
            return 'income', 'переводы от людей'
        return 'income', 'прочие поступления'
    if any(p.search(d) for p in R['invest']):
        return 'invest', 'инвестиции'
    if any(p.search(merchant(d)) for p in R['other_bank']):
        return 'other_bank', 'в другие банки (вероятно, свои счета)'
    if any(p.search(d) for p in R['unclear']):
        return 'unclear', 'оплаты без получателя (уточнить)'
    for name, rx in R['cats']:
        if rx.search(d):
            return 'spend', name
    if any(p.search(d) for p in R['people']) or c in ('Перевод с карты', 'Перевод СБП'):
        return 'people', 'переводы людям'
    if c in R['fallback']:
        return 'spend', R['fallback'][c]
    return 'spend', 'прочие покупки'


def daily_avg_balance(ops, start, end):
    ops = sorted([o for o in ops if o.get('balance') is not None], key=when)
    if not ops:
        return None
    bal, i, tot, n, day = ops[0]['balance'] - ops[0]['amount'], 0, 0.0, 0, start
    while day <= end:
        while i < len(ops) and when(ops[i]).date() <= day:
            bal = ops[i]['balance']
            i += 1
        tot += bal
        n += 1
        day += dt.timedelta(1)
    return tot / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work')
    ap.add_argument('--self', action='append', default=[])
    ap.add_argument('--rules', default=str(HERE.parent / 'references' / 'category_rules.json'))
    ap.add_argument('--saving-rate', type=float, default=13.0)
    ap.add_argument('--scale', type=float, default=1.0)
    a = ap.parse_args()
    W = Path(a.work)
    ops = json.load(open(W / 'ops.json'))
    accounts = json.load(open(W / 'accounts.json')) if (W / 'accounts.json').exists() else []
    K = a.scale
    for o in ops:
        o['amount'] = round(o['amount'] / K, 2)
        if o.get('balance') is not None:
            o['balance'] = round(o['balance'] / K, 2)
    R = load_rules(a.rules)
    selfp = self_patterns(accounts, a.self)
    for o in ops:
        o['kind'], o['group'] = classify(o, R, selfp)
        o['merchant'] = merchant(o['description'])
        o['dt'] = when(o)

    start, end = min(o['dt'] for o in ops).date(), max(o['dt'] for o in ops).date()
    days = (end - start).days + 1
    year = 365 / days
    spend = [o for o in ops if o['kind'] == 'spend' and o['amount'] < 0]
    refunds = sum(o['amount'] for o in ops if o['kind'] == 'income' and o['bank_category'].startswith('Возврат'))
    S = lambda xs: round(-sum(o['amount'] for o in xs), 2)
    months = sorted({o['dt'].strftime('%Y-%m') for o in ops})

    # оборот, который не трата
    turnover = collections.defaultdict(float)
    for o in ops:
        if o['kind'] in ('own', 'cash', 'other_bank'):
            turnover[o['group']] += abs(o['amount'])

    # категории
    cats = collections.defaultdict(list)
    for o in spend:
        cats[o['group']].append(o)
    total_spend = S(spend)
    categories = []
    for name, xs in sorted(cats.items(), key=lambda kv: -S(kv[1])):
        by_m = {m: S([o for o in xs if o['dt'].strftime('%Y-%m') == m]) for m in months}
        # рост: первые 3 месяца против последних 3 полных — раскладка на «чаще» и «дороже» (как price × volume)
        full = months[:-1] if len(months) > 3 else months
        first, last = full[:3], full[-3:]
        def stat(ms):
            ys = [o for o in xs if o['dt'].strftime('%Y-%m') in ms]
            n = len(ys) / max(len(ms), 1)
            return n, (S(ys) / len(ys) if ys else 0)
        (n0, c0), (n1, c1) = stat(first), stat(last)
        categories.append(dict(name=name, total=S(xs), count=len(xs), share=round(S(xs) / total_spend * 100, 1),
                               per_month=round(S(xs) / days * 30.4), per_year=round(S(xs) * year), by_month=by_m,
                               trend=dict(first_months=first, last_months=last, visits_per_month=[round(n0, 1), round(n1, 1)],
                                          avg_check=[round(c0), round(c1)],
                                          volume_effect=round((n1 - n0) * c0), price_effect=round((c1 - c0) * n1))))

    # частые места
    by_merchant = collections.defaultdict(list)
    for o in spend:
        by_merchant[o['merchant']].append(o)
    top_places = []
    for m, xs in sorted(by_merchant.items(), key=lambda kv: -len(kv[1]))[:8]:
        hours = collections.Counter(o['dt'].hour for o in xs)
        top_places.append(dict(merchant=m, group=xs[0]['group'], count=len(xs), total=S(xs), avg_check=round(S(xs) / len(xs)),
                               weekend=sum(1 for o in xs if o['dt'].weekday() >= 5), peak_hour=hours.most_common(1)[0][0],
                               every_n_days=round(days / len(xs), 1)))

    # регулярные списания: тот же получатель в 3+ разных месяцах
    recurring = []
    for m, xs in by_merchant.items():
        ms = {o['dt'].strftime('%Y-%m') for o in xs}
        if len(ms) >= 3:
            amounts = [-o['amount'] for o in xs]
            stable = statistics.pstdev(amounts) / statistics.mean(amounts) < 0.25 if len(amounts) > 1 else True
            recurring.append(dict(merchant=m, group=xs[0]['group'], months=len(ms), total=S(xs), per_month=round(S(xs) / len(ms)),
                                  stable_amount=stable, last=max(o['date'] for o in xs)))
    recurring.sort(key=lambda r: (not r['stable_amount'], -r['total']))

    # кредитка: проценты, долг
    credit = None
    cc = [o for o in ops if o['account'] == 'кредитка' or re.search('кредит', o['account'], re.I)]
    if cc:
        interest = []
        for o in cc:
            m = re.search(r'погашение процентов\s+([\d ]+,\d\d)', o['description'], re.I)
            if m:
                interest.append([o['dt'].strftime('%Y-%m-%d'), round(float(m.group(1).replace(' ', '').replace(',', '.')) / K, 2)])
            elif re.search(r'начислен.*процент|проценты по кредит', o['description'], re.I) and o['amount'] < 0:
                interest.append([o['dt'].strftime('%Y-%m-%d'), -o['amount']])
        head = next((h for h in accounts if h.get('account') == 'кредитка'), {})
        limit = float(head['limit'].replace(' ', '').replace(',', '.')) / K if head.get('limit') else None
        debt = []
        if limit:
            for o in sorted(cc, key=when):
                if o.get('balance') is not None:
                    debt.append([o['dt'].strftime('%Y-%m-%d'), round(limit - o['balance'])])
        credit = dict(interest_total=round(sum(v for _, v in interest), 2), interest=interest, rate=head.get('rate'),
                      grace=head.get('grace'), limit=limit, debt=debt,
                      max_debt=max((v for _, v in debt), default=None), current_debt=debt[-1][1] if debt else None,
                      spend_by_month={m: S([o for o in cc if o['amount'] < 0 and o['kind'] == 'spend' and o['dt'].strftime('%Y-%m') == m]) for m in months},
                      repayments=[[o['dt'].strftime('%Y-%m-%d'), o['amount']] for o in sorted(cc, key=when) if o['amount'] > 0])

    # деньги без работы
    idle = {}
    for acc in {o['account'] for o in ops if o['account'] != 'кредитка'}:
        v = daily_avg_balance([o for o in ops if o['account'] == acc], start, end)
        if v is not None:
            idle[acc] = round(v)
    idle_total = sum(idle.values())
    lost = round(idle_total * a.saving_rate / 100 * days / 365)

    # комиссии, вычеты, крупные операции
    fees = [dict(date=o['date'], amount=-o['amount'], merchant=o['merchant']) for o in ops
            if o['amount'] < 0 and re.search(r'комисс|плата за|обслуживан|штраф|пени|sms-?информ', o['description'], re.I)]
    deduct = {}
    for name, rx in R['deduct'].items():
        xs = [o for o in spend if rx.search(o['description'])]
        if xs:
            deduct[name] = dict(total=S(xs), count=len(xs))
    deduct_base = min(sum(v['total'] for v in deduct.values()), 150000 / K)
    top_ops = sorted(spend, key=lambda o: o['amount'])[:10]

    # поведение
    heat = [[0] * 24 for _ in range(7)]
    for o in spend:
        heat[o['dt'].weekday()][o['dt'].hour] += 1
    leak_ops = [o for o in spend if o['group'] in R['leaks']]
    hour_hist = [sum(1 for o in leak_ops if o['dt'].hour == h) for h in range(24)]
    spend_days = {o['date'] for o in spend}
    by_day = collections.defaultdict(float)
    for o in spend:
        by_day[o['date']] += -o['amount']
    max_day = max(by_day.items(), key=lambda kv: kv[1]) if by_day else None

    income = [o for o in ops if o['kind'] == 'income' and o['group'] == 'доход и возвраты' and not o['bank_category'].startswith('Возврат')]
    people_out = [o for o in ops if o['kind'] == 'people' and o['amount'] < 0]
    invest_out = [o for o in ops if o['kind'] == 'invest' and o['amount'] < 0]
    unclear = [o for o in ops if o['kind'] == 'unclear']
    other_bank = [o for o in ops if o['kind'] == 'other_bank']

    out = dict(
        period=dict(start=start.isoformat(), end=end.isoformat(), days=days, to_year=round(year, 3)),
        scale=K, saving_rate=a.saving_rate,
        reconciliation=[dict(file=h['file'], account=h.get('account'), ok=h.get('check', {}).get('ok')) for h in accounts],
        operations=len(ops),
        turnover_removed={k: round(v) for k, v in turnover.items()}, turnover_removed_total=round(sum(turnover.values())),
        income_total=round(sum(o['amount'] for o in income)), refunds=round(refunds),
        spend_total=round(total_spend), spend_per_day=round(total_spend / days), spend_per_year=round(total_spend * year),
        people_total=S(people_out), invest_total=S(invest_out),
        invest_recurring=[r for r in recurring if r['group'] == 'инвестиции'],
        other_bank=dict(total=S(other_bank), banks=collections.Counter(o['merchant'] for o in other_bank).most_common()),
        unclear=dict(total=S(unclear), count=len(unclear),
                     items=[dict(date=o['date'], amount=-o['amount'], merchant=o['merchant']) for o in sorted(unclear, key=lambda o: o['amount'])[:15]]),
        categories=categories, top_places=top_places, recurring=recurring[:40], credit=credit,
        idle=dict(by_account=idle, total=idle_total, lost_at_rate=lost, rate=a.saving_rate),
        fees=fees, deductible=dict(by_type=deduct, base_capped=round(deduct_base), refund_13=round(deduct_base * 0.13)),
        top_operations=[dict(date=o['date'], amount=-o['amount'], merchant=o['merchant'], group=o['group']) for o in top_ops],
        heat=heat, leak_hour_hist=hour_hist, leak_groups=sorted(R['leaks']),
        no_spend_days=days - len(spend_days), max_day=dict(date=max_day[0], amount=round(max_day[1])) if max_day else None,
        months=months,
        spend_by_month={m: S([o for o in spend if o['dt'].strftime('%Y-%m') == m]) for m in months},
    )
    json.dump(out, open(W / 'analysis.json', 'w'), ensure_ascii=False, indent=1, default=str)

    print(f"Период {start:%d.%m.%Y}–{end:%d.%m.%Y} ({days} дн.), операций {len(ops)}")
    print(f"Убрано оборота (не траты): {out['turnover_removed_total']:,} ₽".replace(',', ' '), dict(out['turnover_removed']))
    print(f"Настоящие траты: {out['spend_total']:,} ₽ · переводы людям {out['people_total']:,.0f} · инвестиции {out['invest_total']:,.0f}".replace(',', ' '))
    for c in categories[:8]:
        print(f"  {c['name']:30s} {format(round(c['total']), ',').replace(',', ' '):>12} ₽  {c['share']:>5}%  {c['count']} покупок")
    if unclear:
        print(f"УТОЧНИТЬ: {len(unclear)} операций без получателя на {out['unclear']['total']:,.0f} ₽".replace(',', ' '))
    if credit:
        print(f"Кредитка: проценты {credit['interest_total']:,.0f} ₽, макс. долг {credit['max_debt']}, сейчас {credit['current_debt']}".replace(',', ' '))
    print(f"Деньги без работы: в среднем {idle_total:,} ₽ → недополучено ≈ {lost:,} ₽ под {a.saving_rate}%".replace(',', ' '))
    print(f"→ {W / 'analysis.json'}")


if __name__ == '__main__':
    main()
