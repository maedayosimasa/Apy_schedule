"""日本の祝日ユーティリティ（アプリ全体で共有）。"""
from datetime import date, timedelta

_cache: dict = {}


def jp_holidays(year: int) -> dict:
    """日本の祝日を {date: 名称} で返す（振替休日・国民の休日含む）。"""
    if year in _cache:
        return _cache[year]

    def nth_wd(y, m, wd, n):
        first = date(y, m, 1)
        return first + timedelta(days=(wd - first.weekday()) % 7 + 7 * (n - 1))

    def vernal(y):
        if y <= 1979:
            d = int(20.8357 + 0.242194 * (y - 1980)) - (y - 1983) // 4
        elif y <= 2099:
            d = int(20.8431 + 0.242194 * (y - 1980)) - (y - 1980) // 4
        else:
            d = int(21.851  + 0.242194 * (y - 1980)) - (y - 1980) // 4
        return date(y, 3, d)

    def autumn(y):
        if y <= 1979:
            d = int(23.2588 + 0.242194 * (y - 1980)) - (y - 1983) // 4
        elif y <= 2099:
            d = int(23.2488 + 0.242194 * (y - 1980)) - (y - 1980) // 4
        else:
            d = int(24.2488 + 0.242194 * (y - 1980)) - (y - 1980) // 4
        return date(y, 9, d)

    base = {
        date(year,  1,  1): '元日',
        nth_wd(year, 1, 0, 2): '成人の日',
        date(year,  2, 11): '建国記念の日',
        date(year,  2, 23): '天皇誕生日',
        vernal(year):        '春分の日',
        date(year,  4, 29): '昭和の日',
        date(year,  5,  3): '憲法記念日',
        date(year,  5,  4): 'みどりの日',
        date(year,  5,  5): 'こどもの日',
        nth_wd(year, 7, 0, 3): '海の日',
        date(year,  8, 11): '山の日',
        nth_wd(year, 9, 0, 3): '敬老の日',
        autumn(year):        '秋分の日',
        nth_wd(year, 10, 0, 2): 'スポーツの日',
        date(year, 11,  3): '文化の日',
        date(year, 11, 23): '勤労感謝の日',
    }

    result = dict(base)

    for d in sorted(base):
        if d.weekday() == 6:
            sub = d + timedelta(days=1)
            while sub in result:
                sub += timedelta(days=1)
            result[sub] = '振替休日'

    sorted_h = sorted(result)
    for i in range(len(sorted_h) - 1):
        d0, d1 = sorted_h[i], sorted_h[i + 1]
        if (d1 - d0).days == 2:
            mid = d0 + timedelta(days=1)
            if mid.weekday() != 6 and mid not in result:
                result[mid] = '国民の休日'

    _cache[year] = result
    return result


def get_holiday(d: date) -> str:
    """祝日名を返す。祝日でなければ空文字。"""
    return jp_holidays(d.year).get(d, '')
