#!/usr/bin/env python3
"""배포된 워들 페이지 E2E — 실제 브라우저로 한 판 끝까지 플레이한다.
사용: /home/ubuntu/.venvs/pw/bin/python tests/e2e_pages.py [URL]
"""
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
    pg.goto(URL, wait_until="load", timeout=45000)
    pg.wait_for_timeout(4000)

    state = pg.evaluate("({answer, num, source, status, words: WORDSET.size, pz: PUZZLES ? Object.keys(PUZZLES).length : null, meta: document.getElementById('meta').textContent})")
    print("STATE:", state)
    assert state["answer"] and len(state["answer"]) == 5, "정답 로드 실패"
    assert state["num"], "회차 로드 실패"
    assert not state["source"].startswith("오프라인"), "NYT 소스 아님: " + state["source"]
    assert state["words"] > 10000, "단어사전 로드 실패: %s" % state["words"]
    today_word = state["answer"]

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
    assert colored == guess, "키보드 색칠 실패: %s" % colored
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
