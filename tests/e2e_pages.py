#!/usr/bin/env python3
"""배포된 워들 페이지 E2E — 실제 브라우저로 한 판 끝까지 플레이한다.
사용: /home/ubuntu/.venvs/pw/bin/python tests/e2e_pages.py [URL]
"""
import json
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://sandfairy1219.github.io/mars-wordle/"
CHROME = "/usr/bin/google-chrome"


def score(guess, ans):
    out = ["absent"] * 5
    pool = {}
    for i in range(5):
        if guess[i] == ans[i]:
            out[i] = "correct"
    for i in range(5):
        if out[i] != "correct":
            pool[ans[i]] = pool.get(ans[i], 0) + 1
    for i in range(5):
        if out[i] == "correct":
            continue
        if pool.get(guess[i], 0) > 0:
            out[i] = "present"
            pool[guess[i]] -= 1
    return out


def run(pw, width, height, shot=None):
    try:
        b = pw.chromium.launch(headless=True)
    except Exception as e:
        print("default launch failed (%s) -> executable_path" % str(e)[:80])
        b = pw.chromium.launch(headless=True, executable_path=CHROME)
    pg = b.new_page(viewport={"width": width, "height": height})
    errs, cons = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: cons.append(f"{m.type}: {m.text}"))
    # --- 디스코드 연동 경로 검증: players.json/웹훅을 가로채 실제 채널에 안 쏘게 ---
    posted = {}
    pg.route("**/api/webhooks/**", lambda route: (
        posted.update(json.loads(route.request.post_data or "{}")),
        route.fulfill(status=204, body="")))
    FR_DAYS = {"days": [
        {"n": 1944, "date": "2026-10-14", "players": [
            {"name": "친구A", "score": "3", "grid": "🟩🟨⬛⬛🟩\n🟩🟩🟨⬛⬛\n🟩🟩🟩🟩🟩"},
            {"name": "친구B", "score": "3", "grid": "🟨⬛⬛🟩⬛\n🟩🟩🟩🟨⬛\n🟩🟩🟩🟩🟩"},
            {"name": "친구C", "score": "X", "grid": "⬛⬛🟨⬛⬛\n🟨⬛⬛⬛⬛"}]},
        {"n": 1943, "date": "2026-10-13", "players": [{"name": "친구A", "score": "4", "grid": "🟩🟩🟩🟩🟩"}]},
    ]}
    pg.route("**/results.json*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(FR_DAYS, ensure_ascii=False)))
    pg.route("**/api/webhooks/**", lambda route: (
        posted.update(json.loads(route.request.post_data or "{}")),
        route.fulfill(status=204, body="")))
    # OAuth 콜백용 /users/@me 스텁
    pg.route("**/api/v10/users/@me", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"id": "777000000000000042", "username": "tester", "global_name": "테스터"})))
    pg.goto(URL, wait_until="load", timeout=45000)
    pg.wait_for_timeout(4000)

    state = pg.evaluate("({answer, num, source, status, words: WORDSET.size, pz: PUZZLES ? Object.keys(PUZZLES).length : null, meta: document.getElementById('meta').textContent})")
    print("STATE:", state)
    assert state["answer"] and len(state["answer"]) == 5, "정답 로드 실패"
    assert state["num"], "회차 로드 실패"
    assert not state["source"].startswith("오프라인"), "NYT 소스 아님: " + state["source"]
    assert state["words"] > 10000, "단어사전 로드 실패: %s" % state["words"]
    today_word = state["answer"]

    # 0) 위조 가능한 '이름 선택' 드롭다운은 제거됐어야 함 (연동은 Discord 로그인 전용)
    assert pg.evaluate("!document.getElementById('who')"), "이름 선택 드롭다운이 아직 남아있음(위조 가능)"
    assert "Discord 로그인" in pg.evaluate("document.getElementById('login-btn').textContent"), "로그인 버튼 없음"
    print("OK 이름선택 드롭다운 제거 확인(연동=Discord 로그인 전용)")

    # 1) 사전에 없는 단어는 거부돼야 함
    pg.keyboard.type("ZZZZZ")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(300)
    assert pg.evaluate("guesses.length") == 0, "무효 단어가 통과됨"
    print("OK 무효단어 거부")

    # 2) 유효 추측 → 색 판정이 NYT 규칙과 일치해야 함
    pg.keyboard.press("Backspace") if pg.evaluate("cur.length") else None
    pg.evaluate("cur=''; document.querySelectorAll('.tile').forEach(t=>{t.textContent='';t.className='tile';})")
    guess = "ADIEU"
    pg.keyboard.type(guess)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(1800)
    got = pg.evaluate("guesses[0].results")
    exp = score(guess, today_word)
    print("guess1:", guess, got, "expected", exp)
    assert got == exp, "채점 불일치"
    colored = pg.evaluate("Array.from(document.querySelectorAll('.key')).filter(k=>/correct|present|absent/.test(k.className)).map(k=>k.textContent).join('')")
    print("keyboard colored:", colored)
    assert sorted(colored) == sorted(guess), "키보드 색칠 실패: %s" % colored
    print("OK 채점 일치(NYT 규칙) + 키보드 색칠")

    # 3) 정답 입력 → 승리 + 모달 + 공유 텍스트
    pg.evaluate("cur=''; document.querySelector('.row.shake') && document.querySelector('.row.shake').classList.remove('shake')")
    pg.keyboard.type(today_word)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(3500)
    end = pg.evaluate("({status, open: document.getElementById('overlay').classList.contains('show'), title: document.getElementById('modal-title').textContent, grid: document.getElementById('grid').textContent, share: shareText(), cd: document.getElementById('countdown').textContent})")
    print("END:", end)
    assert end["status"] == "won" and end["open"], "승리 플로우 실패"
    assert ("#%s" % state["num"]) in end["share"] and "2/6" in end["share"], "공유 텍스트 형식 이상"
    assert end["cd"].startswith("다음 문제까지"), "카운트다운 없음"
    print("OK 승리·모달·공유·카운트다운")

    # 3-1) 미연동 상태에서는 자동 전송이 일어나면 안 됨(위조/오귀속 방지)
    pg.wait_for_timeout(1500)
    print("unlinked posted:", json.dumps(posted, ensure_ascii=False)[:150])
    assert not posted, "미연동인데 결과가 전송됨: %s" % posted
    print("OK 미연동 시 자동 전송 없음")

    # 3-2) 친구들 결과 패널 (공식 앱 결과화면 대체) — 모달 안 버튼으로 진입
    pg.click("#friends-btn")
    pg.wait_for_timeout(900)
    assert not pg.evaluate("document.getElementById('overlay').classList.contains('show')"), "모달이 안 닫힘"
    fr = pg.evaluate("({open: document.getElementById('fr-overlay').classList.contains('show'), label: document.getElementById('fr-label').textContent, rows: document.querySelectorAll('.fr-row').length, crowns: document.querySelectorAll('.fr-best').length, grids: document.querySelectorAll('.fr-cell').length, wrong: document.querySelectorAll('.fr-cell.correct').length, note: document.getElementById('fr-note').textContent})")
    print("FRIENDS:", fr)
    assert fr["open"] and fr["rows"] == 3, "친구들 패널 미표시: %s" % fr
    assert fr["crowns"] == 2, "👑 표시 오류(3/6 두 명이 최고): %s" % fr["crowns"]
    assert fr["grids"] >= 35, "그리드 셀 렌더 누락: %s" % fr["grids"]
    assert fr["wrong"] >= 7, "초록 타일 누락(성공줄): %s" % fr["wrong"]
    assert "#1944" in fr["label"], fr["label"]
    pg.click("#fr-prev"); pg.wait_for_timeout(400)
    label2 = pg.evaluate("document.getElementById('fr-label').textContent")
    assert "#1943" in label2, "이전 날 이동 실패: %s" % label2
    if shot:
        pg.screenshot(path="/tmp/wordle_friends.png", full_page=True)
    pg.click("#fr-close"); pg.wait_for_timeout(300)
    assert not pg.evaluate("document.getElementById('fr-overlay').classList.contains('show')"), "패널 닫기 실패"
    print("OK 친구들 결과 패널(순위·👑·그리드·날짜이동)")

    # 3-3) Discord 로그인(OAuth implicit) 콜백 처리
    assert pg.evaluate("document.getElementById('login-btn').textContent").startswith("🔗")
    pg.goto(URL + "?oauth=1#access_token=FAKE&token_type=Bearer&expires_in=604800&scope=identify", wait_until="load")
    pg.wait_for_timeout(2500)
    oauth = pg.evaluate("({me: localStorage.getItem('mw-me'), state: document.getElementById('me-state').textContent, hash: location.hash, btn: document.getElementById('login-btn').textContent})")
    print("OAUTH:", oauth)
    assert '"via":"oauth"' in (oauth["me"] or ""), "OAuth 신원 저장 실패: %s" % oauth["me"]
    assert "테스터" in oauth["state"], "연동 표시 실패: %s" % oauth["state"]
    assert oauth["hash"] == "", "토큰 해시가 남음"
    # 로그인 직후: 이미 끝난 오늘 게임이 자동 전송돼야 함(귀속 = 로그인 신원)
    pg.wait_for_timeout(1200)
    body = posted.get("content", "")
    print("oauth auto submit:", body[:130].replace("\n", "|"))
    assert "<@777000000000000042>" in body, "멘션 형식으로 자동 전송 안 됨: %s" % body
    assert "👤" not in body and "777000000000000042 (" not in body, "id/이름 노출됨: %s" % body
    assert ("#%s" % state["num"]) in body and "2/6" in body, "전송 본문 형식 이상: %s" % body
    assert posted.get("allowed_mentions") == {"parse": []}, "멘션 차단(핑 방지) 누락"
    posted.clear()
    pg.evaluate("submittedDay = null")            # 수동 재전송 경로도 확인
    pg.click("#send-btn"); pg.wait_for_timeout(1500)
    assert "<@777000000000000042>" in posted.get("content", ""), "수동 전송 실패"
    print("OK Discord 로그인 연동(콜백·신원·멘션 전송·자동/수동)")

    # 4) 레이아웃: 가로 스크롤 없음 + 타일 5개 한 줄
    lay = pg.evaluate("({iw: window.innerWidth, sw: document.documentElement.scrollWidth, tiles: document.querySelector('.row').childElementCount, tileW: Math.round(document.querySelector('.tile').getBoundingClientRect().width)})")
    print("LAYOUT:", lay, "viewport", width)
    assert lay["sw"] <= lay["iw"] + 1, "가로 스크롤 발생"
    assert lay["tiles"] == 5, "타일 배치 오류"

    # 5) localStorage 통계 기록 확인
    st = pg.evaluate("localStorage.getItem('mw-stats')")
    print("STATS:", st)
    assert st and '"played":1' in st, "통계 미기록"

    if shot:
        pg.screenshot(path=shot, full_page=True)
        print("SCREENSHOT:", shot)
    assert not errs, "JS 에러: %s" % errs[:3]
    bad = [c for c in cons if c.startswith("error")]
    assert not bad, "콘솔 에러: %s" % bad[:3]
    b.close()
    return today_word, state["num"]


if __name__ == "__main__":
    with sync_playwright() as pw:
        word, num = run(pw, 390, 844, shot="/tmp/wordle_mobile.png")     # 모바일(디스코드 앱브라우저 감각)
        print("=== MOBILE OK ===")
        run(pw, 1200, 900, shot="/tmp/wordle_desktop.png")
        print("=== DESKTOP OK ===")
    print(f"✅ E2E 전부 통과 — 오늘 문제 #{num} ({word}) · {URL}")
