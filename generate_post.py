#!/usr/bin/env python3
"""매일 1편 푸드타파 정보글을 AI로 자동 작성합니다.

필요한 환경변수 (둘 중 하나)
  ANTHROPIC_API_KEY: Claude API 키 (권장, 글 품질 높음) — console.anthropic.com
  CLAUDE_MODEL     : (선택) Claude 모델 고정. 비우면 최신 Sonnet 자동 선택
  GEMINI_API_KEY   : Google AI Studio API 키 (무료 대안)
  GEMINI_MODEL     : 사용할 모델 (선택, 비우면 내 키로 쓸 수 있는 최신 Flash 모델 자동 선택)

사용법
  python scripts/generate_post.py            # 다음 주제로 1편 작성
  python scripts/generate_post.py --dry-run  # 저장하지 않고 결과만 출력
  python scripts/generate_post.py --topic "원하는 제목" --category care
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "content/posts"
KST = timezone(timedelta(hours=9))
SITE = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))
CATS = {c["slug"]: c["name"] for c in SITE["categories"]}
FACTS = (ROOT / "data/brand_facts.md").read_text(encoding="utf-8")
QBANK = json.loads((ROOT / "data/question_bank.json").read_text(encoding="utf-8"))

# 글에 등장하면 안 되는 타사 브랜드명 (비방·비교 광고 방지)
BANNED = ["쿠쿠", "린클", "스마트카라", "미닉스", "휴렉", "보랄", "에코체", "한경희", "신일", "스테나", "리쿡", "웰릭스",
          "싱크리더", "블랙홀", "쾌존", "바리미", "락앤락", "오쿠", "휴리엔", "젝타", "씽크퓨어", "이노스", "헤이홈",
          "클레보", "도깨비방망이", "오토드", "코오롱", "황금맷돌", "홈바이홈", "UMS", "보아르", "바툼", "이나프", "에코웨일",
          "SK매직", "LG전자", "삼성전자", "쿠첸", "쉘퍼", "씽크365"]
ALLOWED_PHONES = {"070-7450-0401", "1522-0930"}


def load_posts():
    posts = []
    for f in list(POSTS.glob("*.json")) + list(POSTS.glob("*.md")):
        raw = f.read_text(encoding="utf-8")
        if f.suffix == ".md":
            raw = re.match(r"^---json\s*\n(.*?)\n---", raw, re.S).group(1)
        posts.append(json.loads(raw))
    return posts


def norm(s):
    return re.sub(r"[^가-힣a-zA-Z0-9]", "", s or "").lower()


def pick_topic(posts):
    used = {norm(p.get("topic") or "") for p in posts} | {norm(p["title"]) for p in posts}
    queue = []
    # (선택) 구글시트에서 주제 받기: 시트를 '웹에 게시 → CSV'로 공개하고 그 주소를 TOPICS_CSV_URL 에 등록
    # 시트 열: A=제목, B=카테고리(choose/tech/install/care/legal/cost/life)
    csv_url = os.environ.get("TOPICS_CSV_URL")
    if csv_url:
        try:
            import csv, io
            rows = list(csv.reader(io.StringIO(requests.get(csv_url, timeout=30).content.decode("utf-8-sig"))))
            for r in rows:
                if r and r[0].strip() and r[0].strip() != "제목":
                    cat = (r[1].strip() if len(r) > 1 else "") or "life"
                    queue.append({"title": r[0].strip(), "category": cat if cat in CATS else "life"})
            print(f"구글시트 주제 {len(queue)}개 불러옴")
        except Exception as e:
            print(f"구글시트 주제 불러오기 실패(무시하고 진행): {e}")
    queue += json.loads((ROOT / "data/topics.json").read_text(encoding="utf-8"))
    for t in queue:
        if norm(t["title"]) not in used:
            return t
    return None


# ------------------------------------------------------------------ Gemini
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "slug": {"type": "STRING"},
        "description": {"type": "STRING"},
        "category": {"type": "STRING", "enum": list(CATS)},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "summary": {"type": "ARRAY", "items": {"type": "STRING"}},
        "body": {"type": "STRING"},
        "faq": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"q": {"type": "STRING"}, "a": {"type": "STRING"}}, "required": ["q", "a"]}},
        "howto_name": {"type": "STRING"},
        "howto_steps": {"type": "ARRAY", "items": {"type": "STRING"}},
        "cta": {"type": "STRING", "enum": ["trial", "buy", "rental", "kakao"]},
    },
    "required": ["title", "slug", "description", "category", "tags", "summary", "body", "faq", "cta"],
}


_MODEL_CACHE = None


def available_flash_models(key):
    """내 API 키로 쓸 수 있는 Flash 모델을 최신 버전 순으로 자동 선택 (모델 이름이 바뀌어도 그대로 동작)."""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    names = []
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        token = None
        for _ in range(5):
            r = requests.get(url, params={"key": key, "pageSize": 200, **({"pageToken": token} if token else {})}, timeout=30)
            if not r.ok:
                break
            j = r.json()
            for m in j.get("models", []):
                n = m.get("name", "").split("/")[-1]
                if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n \
                        and not any(x in n for x in ("image", "tts", "live", "audio", "embedding", "thinking", "exp")):
                    names.append(n)
            token = j.get("nextPageToken")
            if not token:
                break
    except requests.RequestException:
        pass

    def rank(n):
        ver = [int(x) for x in re.findall(r"gemini-(\d+)(?:\.(\d+))?", n)[0] if x] if re.search(r"gemini-\d", n) else [0]
        return (ver + [0])[:2], "lite" not in n, "preview" not in n

    _MODEL_CACHE = sorted(set(names), key=rank, reverse=True)
    if _MODEL_CACHE:
        print("사용 가능 모델:", ", ".join(_MODEL_CACHE[:4]))
    return _MODEL_CACHE


def call_gemini(prompt, schema=SCHEMA, temperature=0.75):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY 환경변수가 없습니다. GitHub 저장소 Settings → Secrets 에 등록하세요.")
    models = [m for m in [os.environ.get("GEMINI_MODEL")] + available_flash_models(key) + ["gemini-2.5-flash"] if m]
    last = None
    for model in dict.fromkeys(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json", "responseSchema": schema, "maxOutputTokens": 16384},
        }
        for attempt in range(3):
            r = requests.post(url, params={"key": key}, json=body, timeout=180)
            if r.status_code == 404:
                last = f"{model}: 모델 없음"
                break
            if r.status_code in (429, 500, 503):
                last = f"{model}: {r.status_code}"
                time.sleep(20 * (attempt + 1))
                continue
            if not r.ok:
                last = f"{model}: {r.status_code} {r.text[:300]}"
                break
            data = r.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text), model
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last = f"{model}: 응답 파싱 실패 {e}"
                break
    raise RuntimeError(f"Gemini 호출 실패 → {last}")


# ------------------------------------------------------------------ Claude (권장: 글 품질 우선)
def to_json_schema(sc):
    """Gemini 형식 스키마(대문자 type)를 표준 JSON Schema로 변환."""
    out = {}
    for k, v in sc.items():
        if k == "type":
            out[k] = v.lower()
        elif isinstance(v, dict):
            out[k] = {kk: to_json_schema(vv) for kk, vv in v.items()} if k == "properties" else to_json_schema(v)
        else:
            out[k] = v
    return out


def pick_claude_model(key):
    if os.environ.get("CLAUDE_MODEL"):
        return os.environ["CLAUDE_MODEL"]
    try:
        r = requests.get("https://api.anthropic.com/v1/models", params={"limit": 100},
                         headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=30)
        ids = [m["id"] for m in r.json().get("data", [])]  # 최신순으로 정렬돼 옴
        for family in ("sonnet", "opus", "haiku"):
            for i in ids:
                if family in i:
                    return i
    except Exception as e:
        print("모델 목록 조회 실패:", e)
    return "claude-sonnet-4-5"


def _extract_json(text):
    """모델이 텍스트로 답한 경우 JSON 부분만 꺼내기."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def call_claude(prompt, schema=SCHEMA, temperature=0.7):
    key = os.environ["ANTHROPIC_API_KEY"]
    model = pick_claude_model(key)
    js = to_json_schema(schema)
    body = {
        "model": model, "max_tokens": 16000, "temperature": temperature,
        "system": "당신은 한국어 생활가전 전문 에디터입니다. 결과는 반드시 publish 도구를 호출해 제출하세요.",
        "messages": [{"role": "user", "content": prompt}],
        "tools": [{"name": "publish", "description": "완성된 결과를 제출", "input_schema": js}],
        "tool_choice": {"type": "tool", "name": "publish"},
    }
    print(f"Claude 모델: {model}")
    last = None
    for attempt in range(6):
        r = requests.post("https://api.anthropic.com/v1/messages", json=body, timeout=300,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        if r.status_code in (429, 500, 502, 503, 529):
            last = f"{r.status_code}"
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 400:
            msg = r.text
            # 모델마다 지원 옵션이 달라서, 거절된 옵션을 빼고 다시 시도
            if "tool_choice" in msg and body.get("tool_choice", {}).get("type") != "auto":
                body["tool_choice"] = {"type": "auto"}
                print("  tool_choice 미지원 → auto 로 재시도")
                continue
            if "temperature" in msg and "temperature" in body:
                body.pop("temperature")
                print("  temperature 미지원 → 제거 후 재시도")
                continue
            if "tools" in body and ("tool" in msg or "input_schema" in msg):
                body.pop("tools"); body.pop("tool_choice", None)
                body["system"] = "당신은 한국어 생활가전 전문 에디터입니다. 다른 말 없이 JSON 객체 하나만 출력하세요."
                body["messages"][0]["content"] = prompt + "\n\n[출력 형식 JSON 스키마]\n" + json.dumps(js, ensure_ascii=False)
                print("  도구 미지원 → JSON 텍스트 모드로 재시도")
                continue
        if not r.ok:
            raise RuntimeError(f"Claude 호출 실패 {r.status_code}: {r.text[:300]}")
        content = r.json().get("content", [])
        for block in content:
            if block.get("type") == "tool_use":
                return block["input"], model
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        try:
            return _extract_json(text), model
        except (ValueError, json.JSONDecodeError):
            last = "도구 응답 없음 / JSON 파싱 실패"
            body["messages"][0]["content"] = prompt + "\n\n반드시 publish 도구를 호출해서 결과를 제출하세요."
    raise RuntimeError(f"Claude 호출 실패 → {last}")


def call_llm(prompt, schema=SCHEMA, temperature=0.7):
    """ANTHROPIC_API_KEY 가 있으면 Claude, 없으면 Gemini 로 작성."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return call_claude(prompt, schema, temperature)
    if os.environ.get("GEMINI_API_KEY"):
        return call_gemini(prompt, schema, temperature)
    sys.exit("ANTHROPIC_API_KEY(권장) 또는 GEMINI_API_KEY 가 필요합니다. GitHub 저장소 Settings → Secrets 에 등록하세요.")


def build_prompt(topic, posts, feedback=""):
    links = "\n".join(f"- ../{p['slug']}/ : {p['title']}" for p in sorted(posts, key=lambda p: p["date"], reverse=True)[:40])
    sample_q = "\n".join(f"- ({q['type']}) {q['q']}" for q in random.sample(QBANK, min(25, len(QBANK))))
    today = datetime.now(KST).strftime("%Y년 %m월 %d일")
    return f"""당신은 푸드타파(FOODTAPA) 하이브리드 음식물처리기 공식 정보 사이트의 수석 에디터입니다.
오늘({today}) 발행할 정보글 1편을 작성합니다. 네이버·구글 검색(SEO)과 ChatGPT·Perplexity 같은 AI 검색(GEO)에서
그대로 인용될 만큼 정확하고 구조적인 글을 써야 합니다.

[오늘의 주제]
제목 방향: {topic['title']}
카테고리: {topic['category']} ({CATS.get(topic['category'], '')})

[반드시 지킬 사실 — 아래에 없는 수치·인증·수상·가격은 절대 지어내지 마세요]
{FACTS}

[실제 고객 상담에서 나온 질문 예시 — 글의 소재와 FAQ에 참고 (개인정보는 절대 쓰지 말 것)]
{sample_q}

[내부 링크로 연결할 수 있는 기존 글 — 본문에서 관련 있으면 1~2개를 마크다운 링크로 자연스럽게 연결. 이 목록에 없는 주소는 만들지 마세요]
{links}

[작성 규칙]
1. 한국어 '해요체'. 친근하지만 정확하게. 과장·감탄사 남발 금지. 이모지 금지.
2. title: 검색 키워드를 앞쪽에 넣은 28~45자 제목. 주제 방향은 유지하되 더 검색 친화적으로 다듬어도 됩니다. 기존 글 제목과 겹치지 않게.
3. slug: 제목 핵심어를 한글로, 단어 사이는 하이픈(-). 공백·특수문자 없이 20~45자.
4. description: 80~150자. 이 글이 답하는 질문과 핵심 내용을 담은 메타 설명.
5. summary: 핵심 요약 3개 문장 (각 30~80자). AI 검색이 그대로 인용할 수 있도록 결론을 명확하게.
6. body: 마크다운. 전체 2,000~3,500자.
   - 첫 문단(2~3문장)에서 질문에 대한 결론을 바로 말하기.
   - '## ' 소제목 4~6개. 소제목은 질문형 또는 구체적인 명사형.
   - 표(마크다운 table) 최소 1개, 번호 또는 글머리 목록 최소 1개.
   - 본문 중간(두 번째 또는 세 번째 소제목 다음)에 정확히 한 줄로 [[CTA:kakao]] 또는 [[CTA:trial]] 삽입.
   - 마지막 소제목은 '## 정리' 로 2~3문장 마무리.
   - 푸드타파 이야기는 자연스럽게 1~2개 섹션에서만. 정보 전달이 우선.
   - '# '(H1) 사용 금지. HTML 태그 금지.
7. faq: 3~4개. 실제 고객이 검색할 법한 질문 + 2~3문장 답변.
8. howto_name / howto_steps: 글이 '방법·순서·절차'를 다룰 때만 4~6단계로 작성. 아니면 빈 값.
9. tags: 5~7개 검색 키워드 (예: 음식물처리기 설치, 싱크대 음식물처리기). '#' 붙이지 말 것.
10. cta: 글 성격에 맞게 trial(무료체험) / buy(구매) / rental(렌탈) / kakao(설치 상담) 중 하나.
11. 금지: 다른 브랜드·제품명 언급, 고객 실명·연락처·아파트명, 의학적 효능 주장, 공식 번호 외 전화번호, 확인되지 않은 통계.
{feedback}
JSON으로만 답하세요."""


def validate(d, posts):
    errs = []
    body = d.get("body", "")
    text_len = len(re.sub(r"[#*|\-\[\]()`>]", "", body))
    if text_len < 1500:
        errs.append(f"본문이 너무 짧습니다({text_len}자). 2,000자 이상으로 늘리세요.")
    if body.count("\n## ") + body.startswith("## ") < 4:
        errs.append("'## ' 소제목이 4개 이상이어야 합니다.")
    if "|---" not in body.replace(" ", "") and "| ---" not in body:
        errs.append("마크다운 표가 최소 1개 필요합니다.")
    if re.search(r"^# ", body, re.M):
        errs.append("H1('# ')을 쓰지 마세요.")
    if "[[CTA:" not in body:
        errs.append("본문 중간에 [[CTA:kakao]] 또는 [[CTA:trial]]을 넣으세요.")
    all_text = json.dumps(d, ensure_ascii=False)
    hit = [b for b in BANNED if b in all_text]
    if hit:
        errs.append(f"타사 브랜드명이 들어 있습니다: {', '.join(hit)}. 모두 삭제하고 방식명으로 바꾸세요.")
    phones = set(re.findall(r"\d{2,4}-\d{3,4}-\d{4}", all_text)) - ALLOWED_PHONES
    if phones:
        errs.append(f"허용되지 않은 전화번호: {phones}")
    if len(d.get("summary", [])) < 3:
        errs.append("summary는 3개여야 합니다.")
    if len(d.get("faq", [])) < 3:
        errs.append("faq는 3개 이상이어야 합니다.")
    if not 50 <= len(d.get("description", "")) <= 180:
        errs.append("description은 80~150자로 쓰세요.")
    if norm(d.get("title")) in {norm(p["title"]) for p in posts}:
        errs.append("기존 글과 제목이 같습니다.")
    return errs


def clean(d, posts):
    slugs = {p["slug"] for p in posts}
    slug = re.sub(r"[^가-힣a-zA-Z0-9-]", "", re.sub(r"\s+", "-", d["slug"].strip())).strip("-")[:60] or "post"
    if slug in slugs:
        slug = f"{slug}-{hashlib.md5(d['title'].encode()).hexdigest()[:4]}"
    body = d["body"].strip()

    # 존재하지 않는 내부 링크는 텍스트만 남김
    def fix_link(m):
        text, href = m.group(1), m.group(2)
        if href.startswith("../"):
            target = href.strip("./").strip("/")
            return m.group(0) if target in slugs else text
        if href.startswith("http") and not any(h in href for h in ("yootongnara.com", "pf.kakao.com", "youtu.be", "youtube.com", ".go.kr", ".or.kr")):
            return text
        return m.group(0)

    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", fix_link, body)
    out = {
        "slug": slug,
        "title": d["title"].strip(),
        "description": d["description"].strip(),
        "category": d["category"] if d["category"] in CATS else "life",
        "tags": [t.strip().lstrip("#") for t in d.get("tags", []) if t.strip()][:7],
        "summary": [s.strip() for s in d.get("summary", [])][:3],
        "faq": [{"q": f["q"].strip(), "a": f["a"].strip()} for f in d.get("faq", [])][:4],
        "cta": d.get("cta", "trial"),
        "body": body,
        "auto": True,
    }
    steps = [s for s in d.get("howto_steps") or [] if s.strip()]
    if d.get("howto_name") and len(steps) >= 3:
        out["howto"] = {"name": d["howto_name"].strip(), "steps": steps[:8]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--topic")
    ap.add_argument("--category", default="life")
    ap.add_argument("--force", action="store_true", help="오늘 이미 글이 있어도 작성")
    args = ap.parse_args()

    posts = load_posts()
    today = datetime.now(KST).date().isoformat()
    if not args.force and not args.dry_run and any(p["date"][:10] == today for p in posts):
        print(f"오늘({today}) 글이 이미 있어 건너뜁니다. (--force 로 강제 작성)")
        return

    if args.topic:
        topic = {"title": args.topic, "category": args.category}
    else:
        topic = pick_topic(posts)
        if topic is None:  # 주제 목록 소진 → AI가 새 주제 제안
            titles = "\n".join("- " + p["title"] for p in posts)
            res, _ = call_llm(
                f"푸드타파(하이브리드 싱크대 음식물처리기) 정보 사이트의 새 글 주제 1개를 제안하세요. 소비자가 실제로 검색할 만한 질문형 주제. "
                f"타사 브랜드명 금지. 아래 기존 글과 겹치지 않게.\n{titles}\n카테고리는 {list(CATS)} 중 하나.",
                schema={"type": "OBJECT", "properties": {"title": {"type": "STRING"}, "category": {"type": "STRING", "enum": list(CATS)}}, "required": ["title", "category"]},
                temperature=1.0)
            topic = res
    print(f"주제: {topic['title']} [{topic['category']}]")

    feedback = ""
    for attempt in range(3):
        data, model = call_llm(build_prompt(topic, posts, feedback))
        errs = validate(data, posts)
        if not errs:
            break
        print(f"  검증 실패({attempt + 1}/3): {errs}")
        feedback = "\n[이전 초안의 문제 — 반드시 고쳐서 다시 작성]\n" + "\n".join("- " + e for e in errs)
    else:
        sys.exit("3회 시도 후에도 검증을 통과하지 못했습니다. 오늘은 발행하지 않습니다.")

    post = clean(data, posts)
    now = datetime.now(KST).replace(microsecond=0)
    post["date"] = now.isoformat()
    post["topic"] = topic["title"]
    post["model"] = model
    if args.dry_run:
        print(json.dumps(post, ensure_ascii=False, indent=1))
        return
    fn = POSTS / f"{now.date().isoformat()}-{hashlib.md5(post['slug'].encode()).hexdigest()[:6]}.json"
    fn.write_text(json.dumps(post, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ 저장: {fn.name}  ({post['title']})")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"slug={post['slug']}\n")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"::error title=정보글 작성 실패::{str(e)[:400]}")
        raise
