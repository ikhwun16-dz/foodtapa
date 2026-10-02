# 푸드타파 외부 노출용 홈페이지

매일 아침 9시에 AI(Claude 권장 / Gemini 무료 대안)가 음식물처리기 정보글 1편을 써서 자동으로 발행하는 정적 사이트입니다.
구매·렌탈·무료체험 버튼은 모두 유통나라 공식몰로 연결됩니다.

## 들어있는 것

| 폴더/파일 | 내용 |
|---|---|
| `data/site.json` | 사이트 주소, 상품 링크(구매·렌탈·체험·업소용), 연락처, 컬러. **링크·가격이 바뀌면 여기만 고치면 됩니다** |
| `data/brand_facts.md` | AI가 글 쓸 때 반드시 지키는 푸드타파 팩트 시트 (없는 수치를 지어내지 않게 막는 장치) |
| `data/topics.json` | 앞으로 쓸 주제 102개 (약 3개월분). 다 쓰면 AI가 새 주제를 스스로 정함 |
| `data/faq.json` | FAQ 페이지 질문·답변 22개 |
| `data/question_bank.json` | 카톡 상담 질문 모음 (이름·연락처·아파트명 제거본) — 글 소재로 사용 |
| `content/posts/` | 정보글. 초기 12편 포함, 매일 1편씩 자동 추가 |
| `scripts/generate_post.py` | Gemini로 글 작성 + 검수(타사 브랜드명·전화번호·분량·표·FAQ 확인, 실패 시 재작성) |
| `build.py` | HTML·sitemap.xml·rss.xml·robots.txt·llms.txt·썸네일 생성 |
| `.github/workflows/daily.yml` | 매일 09:07 자동 실행 → 글 작성 → 빌드 → 배포 → 네이버/빙 색인 요청 |

## 처음 한 번만 하는 설정 (약 20분)

### 1. GitHub 저장소 만들기
1. github.com 가입 → 오른쪽 위 **+ → New repository**
2. 이름 `foodtapa`, **Public** 선택 → Create
3. **uploading an existing file** 클릭 → 압축 푼 폴더 안의 파일·폴더를 전부 끌어다 놓기 → Commit
   (`.github` 폴더도 꼭 같이 올라가야 합니다)

### 2. 배포 켜기
- 저장소 **Settings → Pages → Source: GitHub Actions** 선택

### 3. AI 키 등록 (둘 중 하나)
**Claude (권장 · 글 품질 높음 · 월 3~5천원 수준 충전식)**
1. https://console.anthropic.com 가입 → Billing에서 크레딧 $5 충전 → API Keys → Create Key → 복사
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `ANTHROPIC_API_KEY` / Secret: 복사한 키

**Gemini (무료 대안)**
- https://aistudio.google.com/apikey → 키 복사 → Name: `GEMINI_API_KEY` 로 등록
- 두 키가 다 있으면 Claude를 사용합니다

### 4. 첫 실행
- 저장소 **Actions 탭 → "매일 정보글 발행 + 배포" → Run workflow**
- 2~3분 뒤 `https://내아이디.github.io/foodtapa/` 에서 사이트 확인
- 이후로는 매일 아침 자동으로 글이 올라갑니다

### 5. 네이버·구글에 등록 (노출의 핵심)
1. **네이버 서치어드바이저**(searchadvisor.naver.com) → 사이트 등록 → "HTML 태그" 방식 선택
   → `content="..."` 안의 값을 `data/site.json`의 `verification.naver`에 붙여넣고 저장
2. 소유확인 후 **요청 → 사이트맵 제출**: `sitemap.xml` / **RSS 제출**: `rss.xml`
3. **구글 서치콘솔**도 같은 방식 (`verification.google`) → Sitemaps에 `sitemap.xml` 제출

## 도메인 연결 (나중에 해도 됨)
1. 도메인 구매 (가비아·카페24·Cloudflare 등) — 예: `foodtapa-guide.co.kr`
2. 저장소 **Settings → Pages → Custom domain**에 도메인 입력, 도메인 회사 DNS에 안내된 레코드 추가
3. **Settings → Secrets and variables → Actions → Variables 탭 → New variable**
   - `SITE_URL` = `https://foodtapa-guide.co.kr`
4. Actions에서 한 번 실행 → canonical·sitemap 주소가 새 도메인으로 바뀜
5. 서치어드바이저·서치콘솔에 새 도메인으로 다시 등록

> 네이버는 `github.io` 같은 공용 주소보다 **자체 도메인**을 더 신뢰하는 편이라, 노출이 목적이면 도메인은 빨리 연결하는 걸 권장합니다.

## 운영 방법

- **주제 직접 지정:** Actions → Run workflow → "직접 지정할 주제" 칸에 제목 입력
- **구글시트로 주제 관리(선택):** 시트 A열=제목, B열=카테고리(`choose`/`tech`/`install`/`care`/`legal`/`cost`/`life`)
  → 파일 → 공유 → **웹에 게시 → CSV** → 나온 주소를 Variables에 `TOPICS_CSV_URL`로 등록. 시트 주제가 먼저 쓰입니다
- **글 숨기기:** `content/posts/`의 해당 파일에 `"draft": true` 추가
- **글 수정:** 해당 파일을 GitHub에서 연필 아이콘으로 고치고 Commit → 자동 재배포
- **상품 링크·가격 변경:** `data/site.json` 수정
- **모델 변경:** 기본은 내 키로 쓸 수 있는 최신 Flash 모델을 자동 선택. 고정하려면 Variables에 `GEMINI_MODEL` 입력

## 로컬에서 미리보기
```bash
pip install -r requirements.txt
PREVIEW=1 python build.py      # dist/index.html 을 브라우저로 열기
GEMINI_API_KEY=키 python scripts/generate_post.py --dry-run   # 글 생성 테스트
```

## 들어간 SEO · GEO · 캐러셀
- 페이지별 title·description·canonical·OG·트위터 카드, 네이버/구글/빙 인증 메타
- JSON-LD: Organization, WebSite, Product(AggregateOffer), BlogPosting, FAQPage, HowTo, BreadcrumbList, ItemList(캐러셀), CollectionPage
- sitemap.xml(이미지 포함), RSS(전문), robots.txt(AI 검색봇 허용), **llms.txt / llms-full.txt** (AI 검색용 요약)
- 글마다: 핵심 요약 박스, 첫 문단 결론, 표, FAQ, 작성자·작성일·수정일, 목차, 관련글
- IndexNow로 새 글을 네이버·빙에 즉시 알림
- 캐러셀: 메인 히어로 슬라이드(자동재생), 시작 방법 카드, 정보글 레일, 제품 갤러리, 관련글 레일
- 모바일 하단 고정 바: 상담·렌탈·구매·15일 무료체험
