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
    browser = b   # 브라우저 핸들 보존 (아래에서 b가 dict로 재사용됨)
    ctx = b.new_context(viewport={"width": width, "height": height}, permissions=["clipboard-read", "clipboard-write"])
    pg = ctx.new_page()
    errs, cons = [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: cons.append(f"{m.type}: {m.text}"))
    # --- 보안 회귀: 페이지 어디에도 웹훅(시크릿)이 없어야 함 + window.open 가로채기 ---
    opened = []
    pg.add_init_script("window.__opened=[]; window.open=(u)=>{window.__opened.push(u); return null;}")
    FR_DAYS = {"days": [
        {"n": 1944, "date": "2026-10-14", "players": [
            {"name": "친구A", "score": "3", "grid": "🟩🟨⬛⬛🟩\n🟩🟩🟨⬛⬛\n🟩🟩🟩🟩🟩"},
            {"name": "친구B", "score": "3", "grid": "🟨⬛⬛🟩⬛\n🟩🟩🟩🟨⬛\n🟩🟩🟩🟩🟩"},
            {"name": "친구C", "score": "X", "grid": "⬛⬛🟨⬛⬛\n🟨⬛⬛⬛⬛"}]},
        {"n": 1943, "date": "2026-10-13", "players": [{"name": "친구A", "score": "4", "grid": "🟩🟩🟩🟩🟩"}]},
    ]}
    pg.route("**/results.json*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(FR_DAYS, ensure_ascii=False)))
    # OAuth 콜백용 /users/@me 스텁
    pg.route("**/api/v10/users/@me", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"id": "777000000000000042", "username": "tester", "global_name": "테스터"})))
    # 서버측 릴레이(Cloudflare Worker /submit) 스텁 — 전송 페이로드 캡처 + CORS 프리플라이트 처리
    sent = []

    def _worker(route):
        if route.request.method == "OPTIONS":
            return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*",
                                                      "Access-Control-Allow-Methods": "POST, OPTIONS",
                                                      "Access-Control-Allow-Headers": "Content-Type"})
        try:
            sent.append(json.loads(route.request.post_data or "{}"))
        except Exception:
            sent.append({})
        return route.fulfill(status=200, content_type="application/json",
                             headers={"Access-Control-Allow-Origin": "*"}, body='{"ok":true,"n":1944}')

    pg.route("**/submit", _worker)
    # 로딩은 네트워크(NYT API + puzzles.json) 의존 → 일시 실패는 재시도로 흡수
    STATE_JS = ("({answer, num, source, status, words: WORDSET.size, "
                "pz: (typeof PUZZLES !== 'undefined' && PUZZLES) ? Object.keys(PUZZLES).length : null, "
                "meta: document.getElementById('meta').textContent})")
    state = {}
    for attempt in range(3):
        try:
            pg.goto(URL, wait_until="load", timeout=45000)
        except Exception as e:                       # 페이지 로드 타임아웃(CDN 순간 장애)
            print("LOAD retry %d: %s" % (attempt + 1, str(e)[:70]))
            pg.wait_for_timeout(3000)
            continue
        for _ in range(20):                          # 문제·사전 로딩 최대 20초 대기
            pg.wait_for_timeout(1000)
            try:
                st = pg.evaluate(STATE_JS)
            except Exception:
                continue
            if st.get("num") and st.get("words", 0) > 10000 and len(st.get("answer") or "") == 5:
                state = st
                break
            state = st
        print("STATE(try %d):" % (attempt + 1), state)
        if state.get("num") and state.get("words", 0) > 10000 and len(state.get("answer") or "") == 5:
            break
        print("  → 로딩 미완(네트워크 추정) — 재시도")
        pg.wait_for_timeout(2000)
    assert state.get("answer") and len(state["answer"]) == 5, "정답 로드 실패(재시도 후): %s" % state
    assert state.get("num"), "회차 로드 실패(재시도 후): %s" % state
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

    # 3-1) 페이지에 시크릿(웹훅 URL)이 없어야 함 + 결과 올리기 = 복사 + 채널 열기
    leaked = pg.evaluate("document.documentElement.outerHTML.includes('api/webhooks') ? 'LEAK' : ''")
    assert not leaked, "페이지 소스에 웹훅(시크릿)이 남아있음 — 클라이언트 노출"
    pg.click("#send-btn")
    pg.wait_for_timeout(1200)
    opened = pg.evaluate("window.__opened")
    clip = pg.evaluate("navigator.clipboard.readText()")
    print("opened:", opened, "| clipboard:", clip[:60].replace("\n", "|"))
    assert opened and "discord.com/channels/1512107856390783077/1559893272166662178" in opened[0], "채널 열기 실패: %s" % opened
    assert ("#%s" % state["num"]) in clip and "2/6" in clip, "복사 텍스트 형식 이상: %r" % clip
    assert "api/webhooks" not in clip and "<@" not in clip, "복사 텍스트에 시크릿/멘션 혼입: %r" % clip
    print("OK 시크릿 0노출 · 결과 복사+채널 열기(붙여넣기 경로)")

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
    pg.wait_for_timeout(2000)
    assert pg.evaluate("document.documentElement.outerHTML.includes('api/webhooks') ? 1 : 0") == 0, "로그인 후 소스에 시크릿 노출"
    # 로그인 상태로 이미 끝난 게임 복원 → 서버측(워커) 자동 전송이 나가야 함
    assert sent, "워커(/submit) 호출이 없음 — 자동 전송 경로 미동작"
    b = sent[-1]
    print("SUBMIT payload:", json.dumps(b, ensure_ascii=False)[:130])
    assert b.get("token") == "FAKE", "OAuth 토큰이 전송되지 않음: %s" % b
    txt = b.get("text", "")
    assert ("#%s" % state["num"]) in txt and "2/6" in txt, "전송 텍스트 형식 이상: %r" % txt
    assert "api/webhooks" not in txt and "<@" not in txt, "전송 텍스트에 시크릿/멘션 혼입: %r" % txt
    n_before = len(sent)
    pg.click("#send-btn"); pg.wait_for_timeout(900)
    assert len(sent) == n_before, "중복 전송 가드 실패"
    print("OK 서버측(워커) 전송 — 브라우저는 토큰+결과만 보낸다(웹훅 없음) · 중복가드 OK")

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
    ctx.close(); browser.close()
    return today_word, state["num"]


if __name__ == "__main__":
    with sync_playwright() as pw:
        word, num = run(pw, 390, 844, shot="/tmp/wordle_mobile.png")     # 모바일(디스코드 앱브라우저 감각)
        print("=== MOBILE OK ===")
        run(pw, 1200, 900, shot="/tmp/wordle_desktop.png")
        print("=== DESKTOP OK ===")
    print(f"✅ E2E 전부 통과 — 오늘 문제 #{num} ({word}) · {URL}")
