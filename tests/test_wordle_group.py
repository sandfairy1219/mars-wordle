
"""wordle_group.py 파서·집계·요약 검증 (합성 데이터). 실행: python3 tests/test_wordle_group.py"""
import importlib.util, os, sys, json, tempfile

spec = importlib.util.spec_from_file_location("wg", "/home/ubuntu/.hermes/scripts/wordle_group.py")
wg = importlib.util.module_from_spec(spec); spec.loader.exec_module(wg)

# --- 1) 파서 ---
cases = [
    ("오늘의 워들 #1944 2026-10-14 3/6\n\n🟩🟨⬛⬛🟩", (1944, "3")),
    ("오늘의 워들 #1944 4/6\n🟩🟩", (1944, "4")),
    ("Wordle 2026-10-14 X/6\n\n🟨", None),                 # 번호 없음 → 거부(날짜만으론 매칭 안 함)
    ("Wordle #1940 X/6", (1940, "X")),
    ("아무 말 #12 3/6", None),                              # 워들 표시 없음 → 거부
    ("오늘의 워들 #1944 5/6 (스샷)", (1944, "5")),
    ("#1944 결과 6/6", None),                                # 워들/그리드 표시 없음
    ("Wordle No. 1940 4/6", (1940, "4")),
    ("", None), (None, None),
]
ok = 0
for text, exp in cases:
    got = wg.parse_result(text)
    assert got == exp, f"파서 실패: {text!r} → {got} != {exp}"
    ok += 1
print(f"OK 파서 {ok}케이스")

# --- 1-1) 귀속 정규식: 신형 멘션 / 구형 👤 ---
cases2 = [
    ("오늘의 워들 #1944 2026-10-14 3/6\n<@1035334701612793876>\n🟩🟩🟩🟩🟩", "1035334701612793876", None),
    ("오늘의 워들 #1944 3/6\n<@!1360683448020373619>\n🟩🟩🟩🟩🟩", "1360683448020373619", None),
    ("오늘의 워들 #1944 3/6\n👤 999000000000000001 (연동테스트)\n🟩🟩🟩🟩🟩", "999000000000000001", "연동테스트"),
]
for text, exp_id, exp_name in cases2:
    got_id = wg.ID_RE.search(text)
    got_name = wg.NAME_RE.search(text)
    assert (got_id.group(1) if got_id else None) == exp_id, f"ID 추출 실패: {text!r}"
    assert (got_name.group(1).strip() if got_name else None) == exp_name, f"이름 추출 실패: {text!r}"
# 그리드 추출(⬜→⬛ 정규화, 5칸 줄만)
g = wg.extract_grid("오늘의 워들 #1944 3/6\n<@1>\n🟩🟨⬛⬛🟩\n🟩🟩⬜⬜🟩\n\n잡담")
assert g == "🟩🟨⬛⬛🟩\n🟩🟩⬛⬛🟩", g
print("OK 귀속·그리드 추출")

# --- 1-2) 붙여넣기 경로: 멘션·ID 없이 점수+그리드만 있어도 파싱(귀속은 작성자 계정) ---
plain = share_like = "오늘의 워들 #1944 2026-10-14 5/6\n\n🟩⬛⬛🟩🟩\n🟩🟩🟩🟩🟩"
assert wg.parse_result(plain) == (1944, "5"), wg.parse_result(plain)
assert wg.ID_RE.search(plain) is None, "ID 없어야 정상"
print("OK 붙여넣기 경로 파싱")


# --- 2) 집계/요약/연속 ---
wg.DB = tempfile.mkdtemp() + "/t.db"
conn = wg.db()
people = {"u1": "sp", "u2": "지쿠", "u3": "뚱쿠", "u4": "okok", "u5": "brnyc"}
data = [
    # n=1941: 3명, 최고 3/6  → 연속 유지
    (1941, "u1", "3"), (1941, "u2", "4"), (1941, "u3", "X"),
    # n=1942: 2명, 최고 2/6
    (1942, "u1", "2"), (1942, "u2", "5"),
    # n=1943: 3명, 👑 3/6 두 명, 1명 실패
    (1943, "u1", "3"), (1943, "u2", "3"), (1943, "u4", "X"),
    # n=1944: 1명(오늘)
    (1944, "u5", "4"),
]
for n, uid, sc in data:
    conn.execute("INSERT OR REPLACE INTO results(n,user_id,user_name,score,day,ts) VALUES(?,?,?,?,?,?)",
                 (n, uid, people[uid], sc, "2026-10-0%d" % (n - 1940), "2026-10-11T00:00:00"))
conn.commit()
conf = wg.cfg()
print("streak(1943):", wg.group_streak(conn, 1943), "(3 기대)")
assert wg.group_streak(conn, 1943) == 3
print("streak(1942):", wg.group_streak(conn, 1942), "(2 기대)")
assert wg.group_streak(conn, 1942) == 2
print("streak(1940):", wg.group_streak(conn, 1940), "(0 기대 — 기록없음)")
assert wg.group_streak(conn, 1940) == 0
s = wg.summary(conn, 1943, conf)
print("--- 요약문 ---\n" + s)
assert "👑 3/6: <@u1> <@u2>" in s, s
assert s.index("3/6") < s.index("X/6"), "정렬 오류"
assert s.startswith("🔥 우리 그룹 3일 연속!"), s
# 기록 없는 날
s0 = wg.summary(conn, 1910, conf)
assert "기록이 없어" in s0, s0
print("OK 집계·요약·연속")
print("✅ wordle_group 전부 통과")
