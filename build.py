#!/usr/bin/env python3
"""푸드타파 정적 사이트 빌더.

사용법:
  python build.py              # dist/ 에 사이트 생성
  PREVIEW=1 python build.py    # 링크를 .../index.html 형태로 (로컬 파일 미리보기용)
  SITE_URL=https://내도메인.com python build.py   # 도메인 연결 후

content/posts/*.json 을 읽어 정보글 페이지를 만들고,
sitemap.xml / rss.xml / robots.txt / llms.txt 까지 한 번에 생성합니다.
"""
import hashlib
import html
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
KST = timezone(timedelta(hours=9))
PREVIEW = os.environ.get("PREVIEW") == "1"
PER_PAGE = 12

SITE = json.loads((ROOT / "data/site.json").read_text(encoding="utf-8"))
if os.environ.get("SITE_URL"):
    SITE["site_url"] = os.environ["SITE_URL"]
SITE["site_url"] = SITE["site_url"].rstrip("/")
FAQ = json.loads((ROOT / "data/faq.json").read_text(encoding="utf-8"))
CATS = {c["slug"]: c["name"] for c in SITE["categories"]}


# ---------------------------------------------------------------- helpers
def abs_url(path: str) -> str:
    """사이트 절대 URL (canonical, sitemap, JSON-LD 용)."""
    path = path.lstrip("/")
    return SITE["site_url"] + "/" + quote(path, safe="/-_.~")


def make_rel(depth: int):
    prefix = "../" * depth

    def rel(path: str = "") -> str:
        p = path.lstrip("/")
        if PREVIEW and (p == "" or p.endswith("/")):
            p = p + "index.html"
        return (prefix + p) or "./"

    return rel


def link(key: str) -> str:
    return SITE["links"][key]


def won(n) -> str:
    return f"{int(n):,}원"


def parse_date(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=KST)
    return d


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


MD = markdown.Markdown(extensions=["tables", "toc", "attr_list", "sane_lists"],
                       extension_configs={"toc": {"slugify": lambda v, sep: "s-" + hashlib.md5(v.encode()).hexdigest()[:6]}})


CTA_HTML = {
    "trial": ("15일 무료체험", "100원으로 신청하고 우리 집 싱크대에서 직접 써보세요. 기사님이 방문 설치해 드립니다.", "무료체험 신청", "trial"),
    "buy": ("공식몰 구매", "공식몰 결제 시 최대 24개월 무이자 할부와 3년 무상 A/S가 적용됩니다.", "공식몰에서 보기", "buy"),
    "rental": ("36개월 렌탈", "초기 목돈 없이 월 납부로 시작하세요. 월 렌탈료는 상담 후 안내됩니다.", "렌탈 상담 신청", "rental"),
    "kakao": ("설치 가능 여부 무료 확인", "싱크대 하부장 사진만 보내주시면 설치 가능 여부를 먼저 확인해 드려요.", "카카오톡 상담", "kakao"),
}


def cta_block(kind: str) -> str:
    title, desc, btn, key = CTA_HTML.get(kind, CTA_HTML["trial"])
    href = SITE["brand"]["kakao"] if key == "kakao" else link(key)
    return (f'<aside class="inline-cta inline-cta--{kind}"><div><strong>{title}</strong><p>{desc}</p></div>'
            f'<a class="btn btn--accent" href="{href}" target="_blank" rel="noopener" data-track="cta-{kind}">{btn} →</a></aside>')


def render_md(text: str):
    MD.reset()
    text = re.sub(r"\[\[CTA:(\w+)\]\]", lambda m: f"\n\n<!--CTA:{m.group(1)}-->\n\n", text)
    body = MD.convert(text)
    toc = MD.toc_tokens
    body = re.sub(r"<p><!--CTA:(\w+)--></p>|<!--CTA:(\w+)-->", lambda m: cta_block(m.group(1) or m.group(2)), body)
    if PREVIEW:
        body = re.sub(r'href="(\.\./[^"#:]+/)"', r'href="\1index.html"', body)
    body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    return body, [{"id": t["id"], "name": strip_tags(t["name"])} for t in toc if t["level"] == 2]


# ---------------------------------------------------------------- covers (PNG for OG / cards)
FONT_CANDIDATES = [
    os.environ.get("COVER_FONT", ""),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
]
PALETTES = [  # (배경, 글자, 포인트) — 프리미엄: 블랙 / 아이보리 / 브라스
    ("#111111", "#F1EEE8", "#B39566"), ("#EDEAE4", "#111111", "#8C6E43"), ("#1C1B19", "#F1EEE8", "#B39566"),
]
COVER_VERSION = "p2"  # 표지 디자인을 바꾸면 이 값을 바꿔서 새로 만들게 함


def _logo_polys(key, x0, y0, height):
    """data/logo_paths.json 의 로고 윤곽을 (x0,y0) 위치, 주어진 높이로 변환한 다각형 목록."""
    data = json.loads((ROOT / "data/logo_paths.json").read_text(encoding="utf-8"))
    bx, by, bw, bh = map(float, data[key + "_box"])
    k = height / bh
    polys = []
    for seg in re.findall(r"M([^Z]+)Z", data[key]):
        pts = [tuple(map(float, xy.split(","))) for xy in seg.split("L")]
        polys.append([(x0 + (x - bx) * k, y0 + (y - by) * k) for x, y in pts])
    return polys, bw * k


def _draw_logo(im, key, x0, y0, height, color, alpha=255):
    from PIL import Image, ImageDraw, ImageChops
    polys, w = _logo_polys(key, x0, y0, height)
    mask = Image.new("L", im.size, 0)
    for poly in polys:  # even-odd 채우기 (구멍 유지)
        layer = Image.new("L", im.size, 0)
        ImageDraw.Draw(layer).polygon(poly, fill=255)
        mask = ImageChops.logical_xor(mask.convert("1"), layer.convert("1")).convert("L")
    if alpha < 255:
        mask = mask.point(lambda v: v * alpha // 255)
    im.paste(Image.new("RGB", im.size, color), (0, 0), mask)
    return w


def make_cover(text: str, sub: str, out: Path, seed: str):
    if out.exists():
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    font_path = next((f for f in FONT_CANDIDATES if f and Path(f).exists()), None)
    if not font_path:
        return
    bg, fg, ac = PALETTES[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(PALETTES)]
    W, H = 1200, 630
    S = 2  # 2배로 그린 뒤 줄여서 가장자리를 매끄럽게
    im = Image.new("RGB", (W * S, H * S), bg)
    # 큰 로고 심볼 (오른쪽, 은은하게)
    _draw_logo(im, "symbol", 760 * S, 120 * S, 470 * S, fg, alpha=22)
    # 왼쪽 위 로고
    sw = _draw_logo(im, "symbol", 72 * S, 64 * S, 40 * S, fg)
    _draw_logo(im, "word", 72 * S + sw + 16 * S, 78 * S, 12 * S, fg)
    d = ImageDraw.Draw(im)
    f_big = ImageFont.truetype(font_path, 60 * S)
    f_sub = ImageFont.truetype(font_path, 24 * S)
    f_tag = ImageFont.truetype(font_path, 22 * S)
    # 카테고리: 가는 선 + 포인트 컬러 글자
    d.line([(72 * S, 205 * S), (112 * S, 205 * S)], fill=ac, width=2 * S)
    d.text((126 * S, 190 * S), sub, font=f_tag, fill=ac)
    # 제목 줄바꿈 (단어 단위)
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=f_big) > 820 * S and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1].rstrip() + "…"
    y = 248 * S
    for ln in lines:
        d.text((72 * S, y), ln, font=f_big, fill=fg)
        y += 84 * S
    d.line([(72 * S, (H - 92) * S), ((W - 72) * S, (H - 92) * S)], fill=ac, width=1 * S)
    d.text((72 * S, (H - 70) * S), "푸드타파 하이브리드 음식물처리기", font=f_sub, fill=fg)
    im = im.resize((W, H), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "PNG", optimize=True)


# ---------------------------------------------------------------- load posts
def load_posts():
    posts = []
    files = sorted((ROOT / "content/posts").glob("*.json")) + sorted((ROOT / "content/posts").glob("*.md"))
    for f in files:
        raw = f.read_text(encoding="utf-8")
        if f.suffix == ".md":  # ---json {메타} --- 본문
            meta, body = re.match(r"^---json\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S).groups()
            p = json.loads(meta)
            p["body"] = body.strip()
        else:
            p = json.loads(raw)
        if p.get("draft"):
            continue
        p["_date"] = parse_date(p["date"])
        p["_updated"] = parse_date(p.get("updated") or p["date"])
        p["url"] = f"guide/{p['slug']}/"
        p["cat_name"] = CATS.get(p["category"], "정보")
        p["body_html"], p["toc"] = render_md(p["body"])
        text = strip_tags(p["body_html"])
        p["read_min"] = max(2, math.ceil(len(text) / 700))
        p["cover"] = f"assets/covers/{hashlib.md5(p['slug'].encode()).hexdigest()[:10]}-{COVER_VERSION}.png"
        posts.append(p)
    posts.sort(key=lambda x: x["_date"], reverse=True)
    for i, p in enumerate(posts):
        p["newer"] = posts[i - 1] if i > 0 else None
        p["older"] = posts[i + 1] if i + 1 < len(posts) else None
    for p in posts:  # 관련글: 같은 카테고리 → 태그 겹침 순
        def score(o):
            return (o["category"] == p["category"]) * 3 + len(set(o.get("tags", [])) & set(p.get("tags", [])))
        p["related"] = sorted([o for o in posts if o is not p], key=lambda o: (-score(o), -o["_date"].timestamp()))[:4]
    return posts


# ---------------------------------------------------------------- JSON-LD
def ld_org():
    b = SITE["brand"]
    return {
        "@type": "Organization", "@id": abs_url("") + "#org", "name": b["name"], "alternateName": b["name_en"],
        "url": abs_url(""), "logo": abs_url("assets/img/logo.png"),
        "sameAs": [b["official"], b["kakao"]],
        "contactPoint": [{"@type": "ContactPoint", "telephone": "+82-70-7450-0401", "contactType": "customer service", "areaServed": "KR", "availableLanguage": "Korean"},
                         {"@type": "ContactPoint", "telephone": "+82-1522-0930", "contactType": "technical support", "areaServed": "KR", "availableLanguage": "Korean"}],
        "award": "환경부 장관 표창 (2020)",
    }


def ld_product():
    offers = []
    for pr in SITE["products"]:
        if pr["price"] >= 1000:
            offers.append({"@type": "Offer", "name": pr["label"], "price": pr["price"], "priceCurrency": "KRW",
                           "availability": "https://schema.org/InStock", "url": link(pr["url_key"]),
                           "seller": {"@type": "Organization", "name": SITE["brand"]["seller"]}})
    return {
        "@type": "Product", "@id": abs_url("product/") + "#product",
        "name": "푸드타파 하이브리드 음식물처리기", "brand": {"@type": "Brand", "name": "푸드타파"},
        "manufacturer": {"@type": "Organization", "name": SITE["brand"]["manufacturer"]},
        "model": "푸드타파하이브리드", "category": "싱크대 음식물처리기",
        "image": [p["image"] for p in SITE["products"]],
        "description": "분쇄와 미생물 분해를 결합한 하이브리드 싱크대 음식물처리기. 국내 유일 상향배출 구조로 액체만 배출해 하수구 막힘을 줄이고, 전국 3년 무상 A/S를 제공합니다.",
        "color": ", ".join(c["name"] for c in SITE["colors"]),
        "countryOfOrigin": "KR",
        "award": "환경부 장관 표창 (2020)",
        "offers": offers[0] if len(offers) == 1 else {"@type": "AggregateOffer", "lowPrice": min(o["price"] for o in offers), "highPrice": max(o["price"] for o in offers), "priceCurrency": "KRW", "offerCount": len(offers), "offers": offers},
    }


def ld_faq(items):
    return {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": strip_tags(q["a"])}} for q in items]}


def ld_breadcrumb(items):
    return {"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(u)} for i, (n, u) in enumerate(items)]}


def ld_itemlist(posts, name):
    return {"@type": "ItemList", "name": name, "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": abs_url(p["url"]), "name": p["title"]} for i, p in enumerate(posts)]}


def ld_graph(*nodes):
    return json.dumps({"@context": "https://schema.org", "@graph": [n for n in nodes if n]}, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- render
env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html"]))
LOGO = json.loads((ROOT / "data/logo_paths.json").read_text(encoding="utf-8"))
env.globals.update(SITE=SITE, link=link, won=won, CATS=CATS, now=datetime.now(KST), cta_block=cta_block, LOGO=LOGO)


def write_logo_files():
    """로고 SVG(전체·파비콘)와 이미지 대체용 SVG를 logo_paths.json 에서 만든다."""
    sym, word = LOGO["symbol"], LOGO["word"]
    x, y, w, h = map(float, LOGO["symbol_box"])
    img = DIST / "assets/img"
    img.mkdir(parents=True, exist_ok=True)
    (img / "logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-0.5 -0.5 149 121"><g fill="#111" fill-rule="evenodd">'
        f'<path transform="translate(-4 -4)" d="{sym}"/><path transform="translate(-4 102)" d="{word}"/></g></svg>', encoding="utf-8")
    s_ = max(w, h) * 1.36
    cx, cy = x + w / 2, y + h / 2
    (img / "favicon.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{cx - s_ / 2:.1f} {cy - s_ / 2:.1f} {s_:.1f} {s_:.1f}">'
        f'<rect x="{cx - s_ / 2:.1f}" y="{cy - s_ / 2:.1f}" width="{s_:.1f}" height="{s_:.1f}" rx="{s_ * 0.22:.1f}" fill="#111"/>'
        f'<path fill="#fff" fill-rule="evenodd" d="{sym}"/></svg>', encoding="utf-8")
    (img / "product.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400" fill="#EDEAE4"/>'
        f'<g transform="translate(200 200) scale(1.3) translate({-cx:.1f} {-cy:.1f})"><path fill="#111" fill-opacity=".14" fill-rule="evenodd" d="{sym}"/></g></svg>', encoding="utf-8")


def write(path: str, html_text: str):
    out = DIST / path
    if path.endswith("/") or path == "":
        out = out / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")


def page(tpl: str, path: str, **ctx):
    depth = 0 if path in ("", "404.html") else path.rstrip("/").count("/") + 1
    ctx.setdefault("canonical", abs_url(path))
    ctx.setdefault("og_image", abs_url("assets/img/og-default.png"))
    rel = (lambda p="": abs_url(p)) if path == "404.html" else make_rel(depth)  # 404는 어느 경로에서든 열리므로 절대주소
    write(path, env.get_template(tpl).render(rel=rel, path=path, **ctx))


def build():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST)
    write_logo_files()
    cover_cache = ROOT / "static/assets/covers"
    posts = load_posts()
    for p in posts:
        make_cover(p["title"], p["cat_name"], cover_cache / Path(p["cover"]).name, p["slug"])
        if (cover_cache / Path(p["cover"]).name).exists():
            shutil.copy(cover_cache / Path(p["cover"]).name, DIST / p["cover"])
    logo_png = ROOT / "static/assets/img/logo.png"
    if True:  # 매번 다시 만듦 (결과가 같으면 커밋 변화 없음)
        try:  # 검색엔진용 로고 PNG (정사각형, 흰 배경)
            from PIL import Image
            S = 4
            im = Image.new("RGB", (512 * S, 512 * S), "#FFFFFF")
            sw = _logo_polys("symbol", 0, 0, 290 * S)[1]
            _draw_logo(im, "symbol", (512 * S - sw) / 2, 96 * S, 290 * S, "#111111")
            ww = _logo_polys("word", 0, 0, 34 * S)[1]
            _draw_logo(im, "word", (512 * S - ww) / 2, 400 * S, 34 * S, "#111111")
            im.resize((512, 512), Image.LANCZOS).save(logo_png, "PNG", optimize=True)
            shutil.copy(logo_png, DIST / "assets/img/logo.png")
        except Exception as e:
            print("로고 PNG 생성 건너뜀:", e)
    make_cover("막힘 없는 하이브리드 음식물처리기", "FOODTAPA", ROOT / f"static/assets/img/og-{COVER_VERSION}.png", "default")
    if (ROOT / f"static/assets/img/og-{COVER_VERSION}.png").exists():
        shutil.copy(ROOT / f"static/assets/img/og-{COVER_VERSION}.png", DIST / "assets/img/og-default.png")

    org = ld_org()
    website = {"@type": "WebSite", "@id": abs_url("") + "#website", "url": abs_url(""), "name": SITE["site_name"], "inLanguage": "ko-KR", "publisher": {"@id": abs_url("") + "#org"}}
    home_faq = FAQ[:6]

    # 홈
    page("home.html", "", title=SITE["default_title"], description=SITE["default_description"],
         posts=posts[:10], faq=home_faq,
         jsonld=ld_graph(org, website, ld_product(), ld_faq(home_faq), ld_itemlist(posts[:10], "푸드타파 최신 정보글")))

    # 제품 / 구매 / FAQ / 소개
    page("product.html", "product/", title="푸드타파 음식물처리기·음식물분쇄기 제품 정보 | 분쇄+미생물 하이브리드·상향배출·3년 A/S",
         description="푸드타파 하이브리드 음식물처리기·음식물분쇄기의 작동 원리(분쇄+미생물+상향배출), 컬러, 설치 조건, 관리법, 보증 정책을 한 페이지에 정리했습니다.",
         posts=posts[:6], og_image=SITE["products"][1]["image"],
         jsonld=ld_graph(org, ld_product(), ld_breadcrumb([("홈", ""), ("제품 정보", "product/")])))
    page("buy.html", "buy/", title="푸드타파 구매·렌탈·15일 무료체험 비교 | 나에게 맞는 방법 고르기",
         description="푸드타파 음식물처리기를 15일 무료체험, 공식몰 구매(최대 24개월 무이자), 36개월 렌탈 중 어떤 방법으로 시작하면 좋은지 비교해 드립니다.",
         jsonld=ld_graph(org, ld_product(), ld_breadcrumb([("홈", ""), ("구매 방법", "buy/")])))
    page("faq.html", "faq/", title="푸드타파 음식물처리기 자주 묻는 질문 (FAQ) | 설치·소음·전기요금·A/S",
         description="푸드타파 설치 공간, 소음, 전기요금, 이전설치 비용, 무상 A/S 기간, 미생물 교체 주기 등 실제 상담에서 가장 많이 받은 질문에 답합니다.",
         faq=FAQ, jsonld=ld_graph(org, ld_faq(FAQ), ld_breadcrumb([("홈", ""), ("자주 묻는 질문", "faq/")])))
    page("about.html", "about/", title="푸드타파 브랜드 소개 | 환경부 장관 표창 하이브리드 음식물처리기",
         description="성능을 1순위로 만든 브랜드 푸드타파. 2017년 업소용으로 시작해 상향배출 하이브리드 음식물처리기를 만들기까지의 이야기.",
         jsonld=ld_graph(org, {"@type": "AboutPage", "url": abs_url("about/"), "name": "푸드타파 브랜드 소개", "about": {"@id": abs_url("") + "#org"}}, ld_breadcrumb([("홈", ""), ("브랜드", "about/")])))

    # 정보글 목록 (페이지네이션 + 카테고리)
    def list_pages(items, base, heading, desc, cat=None):
        pages = max(1, math.ceil(len(items) / PER_PAGE))
        for n in range(1, pages + 1):
            path = base if n == 1 else f"{base}page/{n}/"
            chunk = items[(n - 1) * PER_PAGE:n * PER_PAGE]
            crumbs = [("홈", ""), ("정보글", "guide/")] + ([(heading, base)] if cat else [])
            page("list.html", path, title=f"{heading}{' - ' + str(n) + '페이지' if n > 1 else ''} | 푸드타파 음식물처리기 정보",
                 description=desc, heading=heading, posts=chunk, page_no=n, pages=pages, base=base, current_cat=cat,
                 total=len(items),
                 jsonld=ld_graph(org, {"@type": "CollectionPage", "name": heading, "url": abs_url(path)}, ld_itemlist(chunk, heading), ld_breadcrumb(crumbs)))

    list_pages(posts, "guide/", "음식물처리기 정보글", "음식물처리기 고르는 법, 설치 조건, 하수구 막힘 원인, 미생물 관리, 합법 기준까지 푸드타파가 매일 정리하는 정보글 모음입니다.")
    for slug, name in CATS.items():
        items = [p for p in posts if p["category"] == slug]
        if items:
            list_pages(items, f"guide/category/{slug}/", name, f"푸드타파 정보글 · {name} 카테고리: " + ", ".join(p["title"] for p in items[:3]), cat=slug)

    # 정보글 상세
    for p in posts:
        nodes = [org,
                 {"@type": "BlogPosting", "@id": abs_url(p["url"]) + "#article", "headline": p["title"], "description": p["description"],
                  "image": abs_url(p["cover"]), "datePublished": p["_date"].isoformat(), "dateModified": p["_updated"].isoformat(),
                  "inLanguage": "ko-KR", "mainEntityOfPage": abs_url(p["url"]), "keywords": ", ".join(p.get("tags", [])),
                  "articleSection": p["cat_name"], "wordCount": len(strip_tags(p["body_html"])),
                  "author": {"@type": "Organization", "name": "푸드타파 에디터팀", "url": abs_url("about/")},
                  "publisher": {"@id": abs_url("") + "#org"},
                  "about": {"@id": abs_url("product/") + "#product"}},
                 ld_breadcrumb([("홈", ""), ("정보글", "guide/"), (p["cat_name"], f"guide/category/{p['category']}/"), (p["title"], p["url"])])]
        if p.get("faq"):
            nodes.append(ld_faq(p["faq"]))
        if p.get("howto"):
            nodes.append({"@type": "HowTo", "name": p["howto"]["name"], "step": [{"@type": "HowToStep", "position": i + 1, "name": s.split(":")[0][:60], "text": s} for i, s in enumerate(p["howto"]["steps"])]})
        page("post.html", p["url"], title=f"{p['title']} | 푸드타파", description=p["description"], post=p,
             og_image=abs_url(p["cover"]), og_type="article", jsonld=ld_graph(*nodes))

    page("404.html", "404.html", title="페이지를 찾을 수 없어요 | 푸드타파", description="요청하신 페이지가 없습니다.", posts=posts[:4], noindex=True)

    # ------------------------------------------------ 검색엔진 / AI 파일
    static_pages = [("", 1.0, "daily"), ("product/", 0.9, "weekly"), ("buy/", 0.9, "weekly"), ("faq/", 0.8, "weekly"), ("about/", 0.6, "monthly"), ("guide/", 0.9, "daily")]
    today = datetime.now(KST).date().isoformat()
    urls = [f"<url><loc>{abs_url(u)}</loc><lastmod>{today}</lastmod><changefreq>{c}</changefreq><priority>{pr}</priority></url>" for u, pr, c in static_pages]
    urls += [f"<url><loc>{abs_url(f'guide/category/{s}/')}</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>" for s in CATS if any(p["category"] == s for p in posts)]
    urls += [f"<url><loc>{abs_url(p['url'])}</loc><lastmod>{p['_updated'].date().isoformat()}</lastmod><changefreq>monthly</changefreq><priority>0.8</priority><image:image><image:loc>{abs_url(p['cover'])}</image:loc></image:image></url>" for p in posts]
    (DIST / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n' + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")

    items = []
    for p in posts[:30]:
        items.append(f"<item><title>{html.escape(p['title'])}</title><link>{abs_url(p['url'])}</link><guid isPermaLink=\"true\">{abs_url(p['url'])}</guid>"
                     f"<pubDate>{format_datetime(p['_date'])}</pubDate><category>{html.escape(p['cat_name'])}</category>"
                     f"<description><![CDATA[{p['description']}]]></description><content:encoded><![CDATA[{p['body_html']}]]></content:encoded></item>")
    (DIST / "rss.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
                                  f"<title>{html.escape(SITE['site_name'])} 정보글</title><link>{abs_url('')}</link><description>{html.escape(SITE['default_description'])}</description><language>ko</language>"
                                  f'<atom:link href="{abs_url("rss.xml")}" rel="self" type="application/rss+xml"/>'
                                  + "".join(items) + "</channel></rss>\n", encoding="utf-8")

    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\n\n# AI 검색 크롤러 허용 (GEO)\nUser-agent: GPTBot\nAllow: /\nUser-agent: OAI-SearchBot\nAllow: /\nUser-agent: ChatGPT-User\nAllow: /\nUser-agent: ClaudeBot\nAllow: /\nUser-agent: Claude-SearchBot\nAllow: /\nUser-agent: PerplexityBot\nAllow: /\nUser-agent: Google-Extended\nAllow: /\nUser-agent: Yeti\nAllow: /\n\n"
                                     f"Sitemap: {abs_url('sitemap.xml')}\n", encoding="utf-8")

    facts = (ROOT / "data/brand_facts.md").read_text(encoding="utf-8").split("## 글쓰기 금지 사항")[0]
    facts = facts.split("\n", 3)[-1]
    llms = [f"# {SITE['site_name']}", "", f"> {SITE['default_description']}", "",
            "## 핵심 페이지",
            f"- [제품 정보]({abs_url('product/')}): 작동 원리, 컬러, 설치 조건, 보증",
            f"- [구매·렌탈·무료체험 비교]({abs_url('buy/')})",
            f"- [자주 묻는 질문]({abs_url('faq/')})",
            f"- [브랜드 소개]({abs_url('about/')})",
            f"- [공식몰 구매]({link('buy')}) · [렌탈]({link('rental')}) · [15일 무료체험]({link('trial')})",
            "", "## 정보글"] + [f"- [{p['title']}]({abs_url(p['url'])}): {p['description']}" for p in posts] + ["", "## 브랜드 팩트", facts]
    (DIST / "llms.txt").write_text("\n".join(llms), encoding="utf-8")
    full = ["\n".join(llms), "", "# 정보글 전문"]
    for p in posts:
        full += ["", f"## {p['title']}", f"URL: {abs_url(p['url'])} · 작성일 {p['_date'].date()}", "", p["body"]]
    (DIST / "llms-full.txt").write_text("\n".join(full), encoding="utf-8")

    if SITE.get("indexnow_key"):
        (DIST / f"{SITE['indexnow_key']}.txt").write_text(SITE["indexnow_key"], encoding="utf-8")
    (DIST / ".nojekyll").write_text("")
    print(f"✓ 빌드 완료: 정보글 {len(posts)}개 → {DIST}")


if __name__ == "__main__":
    build()
