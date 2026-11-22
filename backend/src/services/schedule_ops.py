"""Trial estimation and confirmation around the deterministic allocator.

Trials freeze one published report's estimate for every waiting order.  They
never touch shift capacity.  Confirmation is the only place capacity is
consumed, and it is safe to retry: a trial owns at most one confirmation.
"""
from src.models import audit, reports, scheduling
from src.constants.domain import Status
from src.services.comparison import predict
from src.services.reports import require_result
from src.services.scheduling import CONFIRMED_ELSEWHERE, allocate, reconcile, summarise
from src.utils.errors import Problem


def _item(row, estimate):
    return {'code': row['code'], 'title': row['title'], 'deadline': row['deadline'],
            'hours': estimate['hours'], 'model': estimate['model'],
            'outside_range': estimate['outside_range']}


def preview(db, report_id, actor):
    report = reports.get_report(db, report_id, published_only=False)
    if report['status'] != Status.PUBLISHED:
        raise Problem(409, '只能使用已发布的比选报告试估')
    result = require_result(report)
    pending = scheduling.list_pending(db)
    if not pending:
        raise Problem(409, '没有待排工单可试估')
    shifts = scheduling.list_shifts(db)
    committed = scheduling.committed_hours(db)
    items = [_item(row, predict(result, row)) for row in pending]
    allocations, _ = allocate(items, shifts, committed)
    for item in items:
        choice = allocations[item['code']]
        item['shift_id'] = choice['shift_id']
        item['reason'] = choice['reason']
    trial = scheduling.insert_trial(db, report, items, actor)
    audit.record(db, actor, 'schedule.trial', trial['id'])
    return trial_detail(db, trial['id'])


def trial_detail(db, trial_id):
    trial = scheduling.get_trial(db, trial_id)
    if not trial:
        raise Problem(404, '试估记录不存在')
    confirmation = scheduling.confirmation_for_trial(db, trial_id)
    frozen = {item['code']: item for item in scheduling.trial_items(db, trial_id)}
    # Once confirmed, show the placement actually written to the shift roster,
    # which may differ from the preview when capacity changed in between.
    items = (scheduling.confirmation_items(db, confirmation['id']) if confirmation else None)
    if items is None:
        items = scheduling.trial_items(db, trial_id)
    else:
        for item in items:
            origin = frozen.get(item['code'], {})
            item['model'] = origin.get('model', trial['model'])
            item['outside_range'] = origin.get('outside_range', [])
    allocations = {item['code']: item for item in items}
    return {'trial': trial, 'items': items,
            'summary': summarise(items, allocations),
            'confirmation_id': confirmation['id'] if confirmation else None}


def _candidates(db, items):
    """Drop orders another confirmation already placed, with a clear reason."""
    taken = scheduling.scheduled_codes(db)
    candidates, blocked = [], []
    for item in items:
        row = {'code': item['code'], 'title': item['title'], 'deadline': item['deadline'],
               'hours': item['hours'], 'shift_id': item['shift_id']}
        (blocked if item['code'] in taken else candidates).append(row)
    return candidates, {row['code'] for row in blocked}


def confirm(db, trial_id, actor):
    trial = scheduling.get_trial(db, trial_id, for_update=True)
    if not trial:
        raise Problem(404, '试估记录不存在')
    existing = scheduling.confirmation_for_trial(db, trial_id)
    if existing:
        # A retry must not deduct the same hours twice; return the first result.
        return confirmation_detail(db, existing['id'])

    db.execute('SELECT pg_advisory_xact_lock(5210)')
    scheduling.lock_shifts(db)
    items = scheduling.trial_items(db, trial_id)
    candidates, blocked = _candidates(db, items)
    committed = scheduling.committed_hours(db)
    allocations, _ = reconcile(candidates, scheduling.list_shifts(db), committed)

    rows = []
    for item in items:
        row = {'code': item['code'], 'title': item['title'], 'deadline': item['deadline'],
               'hours': item['hours'], 'recomputed': False}
        if item['code'] in blocked:
            row.update(shift_id=None, reason=CONFIRMED_ELSEWHERE)
        else:
            choice = allocations[item['code']]
            row.update(shift_id=choice['shift_id'], reason=choice['reason'])
            if choice['shift_id'] != item['shift_id']:
                row['recomputed'] = True
        rows.append(row)

    confirmation = scheduling.insert_confirmation(db, trial_id, rows, actor)
    audit.record(db, actor, 'schedule.confirm', confirmation['id'])
    return confirmation_detail(db, confirmation['id'])


def confirmation_detail(db, confirmation_id):
    confirmation = scheduling.get_confirmation(db, confirmation_id)
    if not confirmation:
        raise Problem(404, '排班确认记录不存在')
    items = scheduling.confirmation_items(db, confirmation_id)
    scheduled = [item for item in items if item['shift_id']]
    return {'confirmation': confirmation, 'items': items,
            'summary': {'orders': len(items), 'scheduled': len(scheduled),
                        'unscheduled': len(items) - len(scheduled),
                        'hours': sum(item['hours'] for item in scheduled)}}


def board(db):
    shifts = scheduling.list_shifts(db)
    pending = scheduling.list_pending(db)
    return {
        'shifts': [{**shift, 'remaining_hours': shift['capacity_hours'] - shift['confirmed_hours']}
                   for shift in shifts],
        'pending': pending,
        'assignments': scheduling.assignments(db),
        'unscheduled': scheduling.unscheduled_items(db),
    }
