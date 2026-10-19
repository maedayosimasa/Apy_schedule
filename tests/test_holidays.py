"""holidays.py の単体テスト。"""
from datetime import date
import pytest
from holidays import jp_holidays, get_holiday


# ── 固定祝日 ─────────────────────────────────────────────────────────────────

class TestFixedHolidays:
    def test_new_year(self):
        assert jp_holidays(2026)[date(2026, 1, 1)] == "元日"

    def test_foundation_day(self):
        assert date(2026, 2, 11) in jp_holidays(2026)

    def test_emperors_birthday(self):
        assert date(2026, 2, 23) in jp_holidays(2026)

    def test_showa_day(self):
        assert date(2026, 4, 29) in jp_holidays(2026)

    def test_constitution_day(self):
        assert date(2026, 5, 3) in jp_holidays(2026)

    def test_greenery_day(self):
        assert date(2026, 5, 4) in jp_holidays(2026)

    def test_childrens_day(self):
        assert date(2026, 5, 5) in jp_holidays(2026)

    def test_mountain_day(self):
        assert date(2026, 8, 11) in jp_holidays(2026)

    def test_culture_day(self):
        assert date(2026, 11, 3) in jp_holidays(2026)

    def test_labor_thanksgiving(self):
        assert date(2026, 11, 23) in jp_holidays(2026)


# ── 第N月曜日系祝日 ───────────────────────────────────────────────────────────

class TestNthMondayHolidays:
    def test_coming_of_age_2026(self):
        # 1月第2月曜 = 1/12
        assert date(2026, 1, 12) in jp_holidays(2026)

    def test_marine_day_2026(self):
        # 7月第3月曜 = 7/20
        assert date(2026, 7, 20) in jp_holidays(2026)

    def test_respect_for_aged_2026(self):
        # 9月第3月曜 = 9/21
        assert date(2026, 9, 21) in jp_holidays(2026)

    def test_sports_day_2026(self):
        # 10月第2月曜 = 10/12
        assert date(2026, 10, 12) in jp_holidays(2026)


# ── 春分・秋分 ────────────────────────────────────────────────────────────────

class TestEquinox:
    def test_vernal_equinox_2026(self):
        h = jp_holidays(2026)
        # 2026年の春分の日
        march_dates = [d for d in h if d.month == 3]
        assert len(march_dates) >= 1
        assert any(h[d] == "春分の日" for d in march_dates)

    def test_autumnal_equinox_2026(self):
        h = jp_holidays(2026)
        sep_dates = [d for d in h if d.month == 9]
        assert any(h[d] == "秋分の日" for d in sep_dates)


# ── 振替休日 ──────────────────────────────────────────────────────────────────

class TestSubstituteHoliday:
    def test_substitute_when_holiday_is_sunday(self):
        # 2025-02-23 (天皇誕生日) が日曜 → 翌月曜 2025-02-24 が振替休日
        h = jp_holidays(2025)
        assert date(2025, 2, 23).weekday() == 6   # 日曜確認
        assert h.get(date(2025, 2, 24)) == "振替休日"

    def test_no_substitute_when_not_sunday(self):
        # 2026-02-23 が月曜 → 振替なし
        assert date(2026, 2, 23).weekday() == 0   # 月曜確認
        h = jp_holidays(2026)
        assert h.get(date(2026, 2, 24)) != "振替休日"


# ── 国民の休日 ────────────────────────────────────────────────────────────────

class TestNationalHoliday:
    def test_national_holiday_between_two_holidays(self):
        # 祝日に挟まれた平日（国民の休日）が存在する年を確認
        # 2032年: 9/20(月=敬老の日), 9/21(火=国民の休日), 9/22(水=秋分の日)のようなケース
        # 2009年: 9/22(秋分の日), 9/21(敬老の日), 9/22 ... 確認が複雑なので
        # 2031年の秋分の日周辺を確認
        found = False
        for y in range(2009, 2035):
            h = jp_holidays(y)
            for d, name in h.items():
                if name == "国民の休日":
                    found = True
                    break
            if found:
                break
        assert found, "2009-2034 の範囲で国民の休日が見つかりませんでした"


# ── get_holiday ───────────────────────────────────────────────────────────────

class TestGetHoliday:
    def test_holiday_returns_name(self):
        assert get_holiday(date(2026, 1, 1)) == "元日"

    def test_non_holiday_returns_empty(self):
        assert get_holiday(date(2026, 1, 2)) == ""

    def test_saturday_is_not_holiday(self):
        # 土曜は祝日ではない
        assert date(2026, 1, 3).weekday() == 5   # 土曜確認
        assert get_holiday(date(2026, 1, 3)) == ""

    def test_sunday_is_not_holiday(self):
        assert date(2026, 1, 4).weekday() == 6   # 日曜確認
        assert get_holiday(date(2026, 1, 4)) == ""


# ── キャッシュ ────────────────────────────────────────────────────────────────

class TestCache:
    def test_cached_result_is_same_object(self):
        from holidays import _cache
        jp_holidays(2026)
        assert 2026 in _cache
        r1 = jp_holidays(2026)
        r2 = jp_holidays(2026)
        assert r1 is r2

    def test_different_years_are_independent(self):
        h2025 = jp_holidays(2025)
        h2026 = jp_holidays(2026)
        assert h2025 is not h2026


# ── 極端な年（カバレッジ補完）────────────────────────────────────────────────

class TestExtremeYears:
    def test_pre_1980_vernal(self):
        # 1979年以前の春分の日計算式（line 18）
        h = jp_holidays(1975)
        march = [d for d in h if d.month == 3]
        assert any(h[d] == "春分の日" for d in march)

    def test_post_2099_vernal(self):
        # 2100年以降の春分の日計算式（line 22）
        h = jp_holidays(2100)
        march = [d for d in h if d.month == 3]
        assert any(h[d] == "春分の日" for d in march)

    def test_pre_1980_autumn(self):
        # 1979年以前の秋分の日計算式（line 27）
        h = jp_holidays(1975)
        sep = [d for d in h if d.month == 9]
        assert any(h[d] == "秋分の日" for d in sep)

    def test_post_2099_autumn(self):
        # 2100年以降の秋分の日計算式（line 31）
        h = jp_holidays(2100)
        sep = [d for d in h if d.month == 9]
        assert any(h[d] == "秋分の日" for d in sep)
