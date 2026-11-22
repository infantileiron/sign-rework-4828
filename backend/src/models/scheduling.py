from psycopg.errors import UniqueViolation

from src.utils.errors import Problem


def list_shifts(db):
    return db.execute('''SELECT shifts.*, coalesce(sum(items.hours), 0) AS confirmed_hours
        FROM shifts LEFT JOIN schedule_confirmation_items items ON items.shift_id = shifts.id
        GROUP BY shifts.id ORDER BY shifts.shift_date, shifts.id''').fetchall()


def lock_shifts(db):
    """Serialise confirmations: every writer locks the whole roster in id order."""
    return db.execute('SELECT * FROM shifts ORDER BY id FOR UPDATE').fetchall()


def insert_shift(db, form, actor):
    try:
        return db.execute('''INSERT INTO shifts (name, shift_date, capacity_hours, created_by)
            VALUES (%(name)s, %(date)s, %(capacity_hours)s, %(actor)s) RETURNING *''',
            {**form, 'actor': actor}).fetchone()
    except UniqueViolation as exc:
        raise Problem(409, '同一天已有同名班次') from exc


def list_pending(db):
    return db.execute('''SELECT pending_orders.* FROM pending_orders
        WHERE NOT EXISTS (
            SELECT 1 FROM schedule_confirmation_items items
            WHERE items.code = pending_orders.code AND items.shift_id IS NOT NULL)
        ORDER BY deadline, code''').fetchall()


def insert_pending(db, form, actor):
    try:
        return db.execute('''INSERT INTO pending_orders
            (code, title, deadline, minutes, shots, switches, created_by)
            VALUES (%(code)s, %(title)s, %(deadline)s, %(minutes)s, %(shots)s, %(switches)s, %(actor)s)
            RETURNING *''', {**form, 'actor': actor}).fetchone()
    except UniqueViolation as exc:
        raise Problem(409, '待排工单编号已存在') from exc


def committed_hours(db):
    rows = db.execute('''SELECT shift_id, sum(hours) AS hours FROM schedule_confirmation_items
        WHERE shift_id IS NOT NULL GROUP BY shift_id''').fetchall()
    return {row['shift_id']: row['hours'] for row in rows}


def scheduled_codes(db):
    rows = db.execute('''SELECT code FROM schedule_confirmation_items
        WHERE shift_id IS NOT NULL''').fetchall()
    return {row['code'] for row in rows}


def insert_trial(db, report, items, actor):
    trial = db.execute('''INSERT INTO schedule_trials (report_id, report_fingerprint, model, created_by)
        VALUES (%s, %s, %s, %s) RETURNING *''',
        (report['id'], report['fingerprint'], report['result']['winner'], actor)).fetchone()
    with db.cursor() as cursor:
        cursor.executemany('''INSERT INTO schedule_trial_items
            (trial_id, code, title, deadline, hours, model, outside_range, shift_id, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            [(trial['id'], item['code'], item['title'], item['deadline'], item['hours'],
              item['model'], item['outside_range'], item['shift_id'], item['reason'])
             for item in items])
    return trial


def get_trial(db, trial_id, for_update=False):
    suffix = ' FOR UPDATE' if for_update else ''
    return db.execute(f'SELECT * FROM schedule_trials WHERE id = %s{suffix}', (trial_id,)).fetchone()


def trial_items(db, trial_id):
    return db.execute('SELECT * FROM schedule_trial_items WHERE trial_id = %s ORDER BY deadline, code',
                      (trial_id,)).fetchall()


def confirmation_for_trial(db, trial_id):
    return db.execute('''SELECT * FROM schedule_confirmations WHERE trial_id = %s ORDER BY id DESC''',
                      (trial_id,)).fetchone()


def get_confirmation(db, confirmation_id):
    return db.execute('SELECT * FROM schedule_confirmations WHERE id = %s', (confirmation_id,)).fetchone()


def insert_confirmation(db, trial_id, items, actor):
    confirmation = db.execute('''INSERT INTO schedule_confirmations (trial_id, created_by)
        VALUES (%s, %s) RETURNING *''', (trial_id, actor)).fetchone()
    with db.cursor() as cursor:
        cursor.executemany('''INSERT INTO schedule_confirmation_items
            (confirmation_id, code, title, deadline, shift_id, hours, reason, recomputed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            [(confirmation['id'], item['code'], item['title'], item['deadline'], item['shift_id'],
              item['hours'], item['reason'], item['recomputed']) for item in items])
    return confirmation


def confirmation_items(db, confirmation_id):
    return db.execute('''SELECT items.*, shifts.name AS shift_name, shifts.shift_date
        FROM schedule_confirmation_items items LEFT JOIN shifts ON shifts.id = items.shift_id
        WHERE items.confirmation_id = %s ORDER BY items.deadline, items.code''',
        (confirmation_id,)).fetchall()


def assignments(db):
    return db.execute('''SELECT items.confirmation_id, items.code, items.title, items.deadline, items.hours,
            items.shift_id, items.reason, items.recomputed, shifts.name AS shift_name,
            shifts.shift_date, confirmations.created_at
        FROM schedule_confirmation_items items
        JOIN schedule_confirmations confirmations ON confirmations.id = items.confirmation_id
        LEFT JOIN shifts ON shifts.id = items.shift_id
        WHERE items.shift_id IS NOT NULL ORDER BY shifts.shift_date, shifts.id, items.code''').fetchall()


def unscheduled_items(db):
    """The latest explanation recorded for each order still without a slot."""
    return db.execute('''SELECT DISTINCT ON (items.code) items.code, items.title, items.deadline,
            items.hours, items.reason, items.recomputed, items.confirmation_id, confirmations.created_at
        FROM schedule_confirmation_items items
        JOIN schedule_confirmations confirmations ON confirmations.id = items.confirmation_id
        WHERE items.shift_id IS NULL AND NOT EXISTS (
            SELECT 1 FROM schedule_confirmation_items placed
            WHERE placed.code = items.code AND placed.shift_id IS NOT NULL)
        ORDER BY items.code, items.confirmation_id DESC''').fetchall()
