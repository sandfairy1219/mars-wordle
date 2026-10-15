#!/usr/bin/env python3
"""로그인 유지 + 자동전송 회귀 테스트 — 실브라우저로 재현/검증한다.

사용: /home/ubuntu/.venvs/pw/bin/python tests/e2e_login_auto.py [URL]

검사 항목
  A. OAuth 콜백 → 토큰 저장 + me-bar가 '로그인됨'으로 표시
  B. 해시 없이 재방문(새로고침) → me-bar가 여전히 '로그인됨' (persist)
  C. 매일 모드 한 판 완주 → 서버(Worker /submit)로 자동 POST 발생 + 성공 토스트
"""
import json
import sys
import time
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://sandfairy1219.github.io/mars-wordle/"
CHROME = "/usr/bin/google-chrome"
FAKE_TOKEN = "TESTTOKEN"
HASH = (f"?oauth=1#access_token={FAKE_TOKEN}&token_type=Bearer&expires_in=604800"
        "&scope=identify%20guilds")


def launch(pw):
    try:
        return pw.chromium.launch(headless=True)
    except Exception as e:
        print("default launch failed (%s) -> executable_path" % str(e)[:70])
        return pw.chromium.launch(headless=True, executable_path=CHROME)


def main():
    results = []
    with sync_playwright() as pw:
        b = launch(pw)
        ctx = b.new_context(viewport={"width": 390, "height": 844},
                            permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: print("  [pageerror]", str(e)[:160]))

        # --- 스텁: Discord 사용자 조회, Worker /submit(전송 캡처), 결과집계 ---
        pg.route("**/api/v10/users/@me", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"id": "777000000000000042", "username": "tester",
                             "global_name": "테스터"})))
        pg.route("**/api/v10/users/@me/guilds", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps([{"id": "1512107856390783077"}])))
        sent = []

        def worker(route):
            if route.request.method == "OPTIONS":
                return route.fulfill(status=204, headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type"})
            try:
                sent.append(json.loads(route.request.post_data or "{}"))
            except Exception:
                sent.append({})
            return route.fulfill(status=200, content_type="application/json",
                                 headers={"Access-Control-Allow-Origin": "*"},
                                 body='{"ok":true,"n":1945}')

        pg.route("**/submit", worker)
        pg.route("**/results.json*", lambda r: r.fulfill(
            status=200, content_type="application/json", body='{"days":[]}'))

        def me_state():
            return pg.evaluate("document.getElementById('me-state').textContent")

        def tok_state():
            return pg.evaluate("(() => { try { return JSON.parse(localStorage.getItem('mw-tok')); }"
                               " catch(e) { return null; } })()")

        # ---------- A: OAuth 콜백 ----------
        pg.goto(URL + HASH, wait_until="load", timeout=60000)
        pg.wait_for_timeout(3500)
        a_tok = bool(tok_state())
        a_state = me_state()
        results.append(("A. 콜백 후 토큰 저장", a_tok, "mw-tok 저장=%s" % a_tok))
        results.append(("A2. 콜백 후 me-bar 표시", ("✅" in a_state and "테스터" in a_state),
                        repr(a_state[:60])))

        # ---------- B: 해시 없이 재방문 ----------
        pg.goto(URL, wait_until="load", timeout=60000)
        pg.wait_for_timeout(3000)
        b_tok = bool(tok_state())
        b_state = me_state()
        results.append(("B. 재방문 시 토큰 유지", b_tok, "mw-tok 저장=%s" % b_tok))
        results.append(("B2. 재방문 me-bar '로그인됨'", ("✅" in b_state and "테스터" in b_state),
                        repr(b_state[:60])))
        results.append(("B3. 재방문 시 로그인 버튼이 '계정 변경'(재로그인 유도 아님)",
                        ("계정 변경" in pg.evaluate("document.getElementById('login-btn').textContent")),
                        repr(pg.evaluate("document.getElementById('login-btn').textContent"))))

        # ---------- C: 한 판 완주 → 자동 전송 ----------
        answer = pg.evaluate("answer")
        results.append(("C0. 정답 로드", bool(answer) and len(answer) == 5, "answer=%s" % answer))
        if answer and len(answer) == 5:
            pg.keyboard.type(answer)
            pg.keyboard.press("Enter")
            for _ in range(40):                     # 모달이 뜰 때까지 최대 20초
                if pg.evaluate("document.getElementById('overlay').classList.contains('show')"):
                    break
                pg.wait_for_timeout(500)
            pg.wait_for_timeout(2500)               # 자동전송 완료 대기
            ok_payload = bool(sent) and set(sent[-1].keys()) == {"token", "text"}
            results.append(("C. 완주 시 자동 POST 발생", ok_payload,
                            "payload=%s" % (json.dumps(sent[-1], ensure_ascii=False)[:130] if sent else "없음")))
            results.append(("C2. 토큰이 실려 있음", bool(sent) and sent[-1].get("token") == FAKE_TOKEN,
                            "token=%s" % (sent[-1].get("token") if sent else None)))
            results.append(("C3. 결과 텍스트에 정답/그리드 포함",
                            bool(sent) and "1/6" in sent[-1].get("text", ""),
                            repr((sent[-1].get("text", "")[:40]) if sent else "")))
            results.append(("C4. 로그인 후 재전송 중복 없음(1회)", len(sent) == 1, "POST 횟수=%d" % len(sent)))

        ctx.close()
        b.close()

    print("\n=== 결과 ===")
    fails = 0
    for name, ok, detail in results:
        print(("  PASS  " if ok else "  FAIL  ") + name + " | " + detail)
        fails += 0 if ok else 1
    print("\n%d/%d 통과" % (len(results) - fails, len(results)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
