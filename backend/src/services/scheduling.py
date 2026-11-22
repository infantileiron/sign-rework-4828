"""Deterministic trial allocation for editing shifts.

The policy lives here without database imports so it can be unit tested:

* an order occupies exactly one shift dated on or before its deadline;
* the number of scheduled orders is maximised first, so a short order that
  fills a leftover gap is never displaced by a large one that blocks it;
* when several arrangements schedule the same number of orders, the one
  placing earlier deadlines wins;
* among equivalent shifts an order takes the tightest fit, and a later shift
  when two are equally tight, which leaves early capacity for orders that
  cannot use later shifts;
* confirming again keeps every still-feasible proposal as it was and only
  re-places the orders that no longer fit, always from the stored trial hours.
"""

EPS = 1e-9

NO_SHIFT = '截止日前没有可用班次'
CAPACITY = '截止日前班次余量不足'
CONFIRMED_ELSEWHERE = '已由其他排班确认'

# Exhaustive search is exact for ordinary rosters.  Larger batches fall back to
# the earliest-deadline / best-fit heuristic so a request never stalls.
EXACT_ORDER_LIMIT = 12
EXACT_NODE_LIMIT = 400_000


def _exact_affordable(order_count):
    return order_count <= EXACT_ORDER_LIMIT


def _rank(order):
    return (order['deadline'], order['hours'], order['code'])


def _shift_date(shift):
    return shift.get('shift_date') if 'shift_date' in shift else shift['date']


def _remaining(shifts, committed):
    return {shift['id']: shift['capacity_hours'] - (committed or {}).get(shift['id'], 0.0)
            for shift in shifts}


def _fits(shift, order, remaining):
    return _shift_date(shift) <= order['deadline'] and remaining[shift['id']] + EPS >= order['hours']


def _reason(order, shifts):
    if not any(_shift_date(shift) <= order['deadline'] for shift in shifts):
        return NO_SHIFT
    return CAPACITY


def _options(order, shifts, remaining):
    eligible = [shift for shift in shifts if _fits(shift, order, remaining)]
    return sorted(eligible, key=lambda shift: (remaining[shift['id']] - order['hours'],
                                               -_shift_date(shift).toordinal(), shift['id']))


def _record(allocations, order, shift, reason):
    allocations[order['code']] = {
        'shift_id': shift['id'] if shift else None,
        'reason': reason if shift is None else None,
        'hours': order['hours'],
    }


def _greedy(orders, shifts, remaining):
    allocations = {}
    for order in sorted(orders, key=_rank):
        options = _options(order, shifts, remaining)
        if options:
            remaining[options[0]['id']] -= order['hours']
            _record(allocations, order, options[0], None)
        else:
            _record(allocations, order, None, _reason(order, shifts))
    return allocations, remaining


def _exact(orders, shifts, remaining):
    """Branch and bound on (count, sorted deadlines) over eligible shifts.

    Returns ``None`` if the node budget is exhausted before any complete leaf,
    so the caller can fall back to the greedy heuristic.
    """
    queue = sorted(orders, key=_rank)
    total = len(queue)
    # Sentinel (1, ()) is worse than any real leaf, whose count term is <= 0,
    # so even an all-unscheduled leaf (count 0) becomes the best candidate.
    best = {'key': (1, ()), 'alloc': None}
    nodes = [0]

    def search(index, count, deadlines, allocations):
        nodes[0] += 1
        if nodes[0] > EXACT_NODE_LIMIT:
            return
        # Cannot beat the current schedule even if every remaining order fits.
        if count + (total - index) < -best['key'][0]:
            return
        if index == total:
            key = (-count, tuple(sorted(deadlines)))
            if key < best['key']:
                best['key'] = key
                best['alloc'] = dict(allocations)
            return
        order = queue[index]
        for shift in _options(order, shifts, remaining):
            remaining[shift['id']] -= order['hours']
            allocations[order['code']] = shift['id']
            search(index + 1, count + 1, deadlines + [order['deadline']], allocations)
            del allocations[order['code']]
            remaining[shift['id']] += order['hours']
            if nodes[0] > EXACT_NODE_LIMIT:
                return
        allocations[order['code']] = None
        search(index + 1, count, deadlines, allocations)
        del allocations[order['code']]

    search(0, 0, [], {})
    if best['alloc'] is None:
        return None

    allocations = {}
    for order in queue:
        shift_id = best['alloc'].get(order['code'])
        shift = next((item for item in shifts if item['id'] == shift_id), None)
        if shift and _fits(shift, order, remaining):
            remaining[shift['id']] -= order['hours']
            _record(allocations, order, shift, None)
        else:
            _record(allocations, order, None, _reason(order, shifts))
    return allocations, remaining


def _optimise(orders, shifts, remaining):
    if not orders:
        return {}, remaining
    if _exact_affordable(len(orders)):
        # Search on a copy so an early abort cannot disturb the caller's map.
        exact = _exact(orders, shifts, dict(remaining))
        if exact is not None:
            return exact
    return _greedy(orders, shifts, remaining)


def allocate(orders, shifts, committed=None, fixed=()):
    """Assign orders to shifts without mutating the inputs.

    ``orders``:  ``{'code', 'hours', 'deadline'}`` mappings.
    ``shifts``:  ``{'id', 'shift_date', 'capacity_hours'}`` mappings.
    ``committed``: hours already confirmed per shift id.
    ``fixed``:   proposals that must be kept if they still fit.

    Returns ``(allocations, remaining)`` where ``allocations`` maps every order
    code to ``{'shift_id', 'reason', 'hours'}`` and ``remaining`` is the
    leftover capacity per shift.
    """
    remaining = _remaining(shifts, committed)
    by_id = {shift['id']: shift for shift in shifts}
    allocations = {}

    for order in sorted(fixed, key=_rank):
        shift = by_id.get(order.get('shift_id'))
        if shift and _fits(shift, order, remaining):
            remaining[shift['id']] -= order['hours']
            _record(allocations, order, shift, None)

    rest = [order for order in orders if order['code'] not in allocations]
    placed, remaining = _optimise(rest, shifts, remaining)
    allocations.update(placed)
    return allocations, remaining


def reconcile(trials, shifts, committed=None):
    """Keep every still-feasible original proposal, re-place the rest.

    ``trials`` carry the frozen estimate: ``{'code', 'title', 'deadline',
    'hours', 'shift_id'}`` where ``shift_id`` is the proposal made by the
    preview.  Trial hours are used as-is; the model is never called again.
    """
    return allocate(trials, shifts, committed, fixed=trials)


def summarise(trials, allocations):
    scheduled = [trial for trial in trials if allocations[trial['code']]['shift_id']]
    return {
        'orders': len(trials),
        'scheduled': len(scheduled),
        'unscheduled': len(trials) - len(scheduled),
        'hours': sum(allocations[trial['code']]['hours'] for trial in scheduled),
    }
