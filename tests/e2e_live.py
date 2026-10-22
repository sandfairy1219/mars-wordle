#!/usr/bin/env python3
"""실시간 진행 전송 E2E — 시도할 때마다 /live 로 같은 메시지를 갱신하고, 완주하면 /submit 1회.

실행: /home/ubuntu/.venvs/pw/bin/python /home/ubuntu/wordle/tests/e2e_live.py
"""
import json

from playwright.sync_api import sync_playwright

URL = ("https://sandfairy1219.github.io/mars-wordle/?oauth=1"
       "#access_token=FAKE_TOKEN_FOR_E2E&token_type=Bearer&scope=identify%20guilds")
CHROME = "/usr/bin/google-chrome"
CORS = {"Access-Control-Allow-Origin": "*"}

live, subs, errs = [], [], []


def main():
    global live, subs
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch(headless=True)
        except Exception:
            b = pw.chromium.launch(headless=True, executable_path=CHROME)
        ctx = b.new_context(viewport={"width": 420, "height": 900},
                            permissions=["clipboard-read", "clipboard-write"])
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))

        pg.route("**/api/v10/users/@me", lambda r: r.fulfill(
            status=200, content_type="application/json", headers=CORS,
            body='{"id":"777000000000000042","name":"테스터"}'))

        def _live(route):
            live.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", headers=CORS,
                          body=json.dumps({"ok": True, "n": 1948, "edited": len(live) > 1}))

        def _sub(route):
            subs.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(status=200, content_type="application/json", headers=CORS,
                          body='{"ok":true,"n":1948}')

        pg.route("**/wordle-submit.sandfairy1219.workers.dev/live", _live)
        pg.route("**/wordle-submit.sandfairy1219.workers.dev/submit", _sub)

        ok = True

        def chk(label, cond, extra=""):
            nonlocal ok
            print(f"  {'✅' if cond else '❌'} {label}{('  ' + extra) if extra else ''}")
            if not cond:
                ok = False

        # 로딩 (CDN 지연 흡수: 최대 25초)
        pg.goto(URL, wait_until="domcontentloaded", timeout=60000)
        loaded = False
        for _ in range(25):
            pg.wait_for_timeout(1000)
            try:
                if pg.evaluate("typeof answer==='string' && answer.length===5 && !!num"): 
                    loaded = True
                    break
            except Exception:
                pass
        chk("문제 로드", loaded)
        if not loaded:
            print("  STATE:", pg.evaluate("({num, day, status, meta: document.getElementById('meta').textContent})"))
            b.close()
            return False

        st = pg.evaluate("({num, day, answer, tok: !!TOK, mode})")
        print(f"  문제: #{st['num']} ({st['day']}) · 로그인={st['tok']} · 정답길이={len(st['answer'])}")

        def guess(word):
            pg.keyboard.type(word)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(3200)     # 타일 플립 + 전송

        wrong = [w for w in ["CRANE", "SLATE", "AUDIO", "PLUCK"] if w != st["answer"]][:2]
        guess(wrong[0])
        chk("1번째 시도 → /live 1건", len(live) == 1, f"attempt={live[-1].get('attempt') if live else None}")
        chk("1번째 그리드 1줄", bool(live) and live[0]["grid"].count("\n") == 0)
        chk("1번째에 최종 전송은 없음", len(subs) == 0)

        guess(wrong[1])
        chk("2번째 시도 → /live 2건", len(live) == 2, f"attempt={live[-1].get('attempt') if len(live) > 1 else None}")
        chk("2번째 그리드 2줄", len(live) > 1 and live[1]["grid"].count("\n") == 1)
        chk("payload 필드(token,n,day,grid,attempt)",
            bool(live) and set(live[0]) == {"token", "n", "day", "grid", "attempt"}, str(sorted(live[0]) if live else []))

        # 정답 입력 → 승리 → 최종 1회
        guess(st["answer"].upper())
        pg.wait_for_timeout(1500)
        chk("완주 시 /submit 1건", len(subs) == 1)
        chk("최종 텍스트에 점수 표기", bool(subs) and "/6" in subs[0].get("text", ""))
        chk("최종 텍스트에 3줄 그리드", bool(subs) and subs[0]["text"].count("🟩") >= 5)
        chk("완주 후 추가 live 없음", len(live) == 2, f"live={len(live)}")
        chk("JS 에러 0", not errs, str(errs[:2]))

        print("\n  live 페이로드:", [{"attempt": l["attempt"], "rows": l["grid"].count("\n") + 1} for l in live])
        print("  submit 텍스트:", (subs[0]["text"].split("\n")[0] if subs else "없음"))
        print("  live 본문에는 x/6 없음(집계 무시):",
              all("/6" not in l.get("grid", "") for l in live))
        b.close()
    return ok


if __name__ == "__main__":
    ok = main()
    print("\n✅ 실시간 전송 E2E 통과" if ok else "\n❌ 실패")
    raise SystemExit(0 if ok else 1)
