import hashlib
import json

from src.config.database import connect
from src.utils.security import password_hash


ACCOUNTS = [('owner@bridge.test', '林桥', 'owner'), ('analyst@bridge.test', '周岚', 'analyst'),
            ('viewer@bridge.test', '许禾', 'viewer')]
TITLES = ['办事导引', '图书借阅', '就诊签到', '观展须知', '课堂签到', '防汛提示', '场馆换乘', '社区议事']
TOPICS = ['政务服务', '公共图书馆', '社区门诊', '城市展厅', '社区课堂', '轮渡服务']
NOISE = [-0.2, 0.3, 0.0, -0.1, 0.1, -0.3, 0.2, 0.0]


def demo_order(group, index):
    minutes = round(1.5 + 1.1 * index + 0.14 * group, 2)
    shots = 8 + 3 * ((index * 3 + group) % 8) + group
    switches = (index + group * 2) % 4
    shift = 1.55 if group == 6 else 0.10 * (group - 3)
    hours = round(0.5 + 0.45 * minutes + 0.14 * shots + shift + NOISE[index], 2)
    return (f'QY-{group:02d}{index + 1:02d}', f'{TOPICS[group - 1]}｜{TITLES[index]}',
            f'G{group:02d}', minutes, shots, switches, hours)


def seed():
    with connect() as db:
        for email, name, role in ACCOUNTS:
            if not db.execute('SELECT 1 FROM accounts WHERE email=%s', (email,)).fetchone():
                db.execute('INSERT INTO accounts VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING',
                           (email, name, password_hash('Qiaoyu2026!'), role))
        with db.cursor() as cursor:
            cursor.executemany('''INSERT INTO orders (code, title, crew, minutes, shots, switches, hours)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING''',
                [demo_order(group, index) for group in range(1, 7) for index in range(8)])
        db.execute('''INSERT INTO plans (name, alpha, features, created_by)
            VALUES ('接单三项 · v1', 0.10, ARRAY['minutes','shots','switches'], %s),
                   ('时长与镜头 · v2', 0.20, ARRAY['minutes','shots'], %s)
            ON CONFLICT (name) DO NOTHING''', ('analyst@bridge.test', 'analyst@bridge.test'))
        with db.cursor() as cursor:
            cursor.executemany('''INSERT INTO shifts (name, shift_date, capacity_hours, created_by)
                VALUES (%s, %s, %s, %s) ON CONFLICT (shift_date, name) DO NOTHING''',
                [('早班 · 剪辑台 A', '2026-11-24', 8.0, 'analyst@bridge.test'),
                 ('晚班 · 剪辑台 B', '2026-11-26', 8.0, 'analyst@bridge.test'),
                 ('周末加班', '2026-11-28', 12.0, 'analyst@bridge.test')])
            cursor.executemany('''INSERT INTO pending_orders
                (code, title, deadline, minutes, shots, switches, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (code) DO NOTHING''',
                [('QY-0701', '轮渡服务｜夜航指引', '2026-11-25', 5.5, 22, 2, 'analyst@bridge.test'),
                 ('QY-0702', '社区门诊｜接种告知', '2026-11-26', 3.4, 15, 1, 'analyst@bridge.test'),
                 ('QY-0703', '政务窗口｜跨省通办', '2026-11-27', 7.2, 34, 4, 'analyst@bridge.test'),
                 ('QY-0704', '城市展厅｜临时闭馆', '2026-11-24', 2.0, 9, 1, 'analyst@bridge.test')])
        # Stable natural keys and user-editable values make repeat runs directly comparable.
        sets = {table: db.execute(f'SELECT {columns} FROM {table} ORDER BY {order_key}').fetchall()
                for table, columns, order_key in (
                    ('accounts', 'email, role', 'email'), ('orders', '*', 'code'), ('crews', '*', 'code'),
                    ('plans', 'name, alpha, features', 'name'), ('shifts', 'name, shift_date, capacity_hours', 'id'),
                    ('pending_orders', 'code, title, deadline, minutes, shots, switches', 'code'),
                )}
    content = json.dumps(sets, sort_keys=True, ensure_ascii=False, default=str).encode()
    return {'rows': {table: len(rows) for table, rows in sets.items()}, 'keys_and_content_sha256': hashlib.sha256(content).hexdigest()}


if __name__ == '__main__':
    print(json.dumps(seed(), sort_keys=True))
