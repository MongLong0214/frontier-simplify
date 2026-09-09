<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg?v=3">
    <img src="assets/logo.svg?v=3" width="480" alt="sol-simplify — 가위와 워드마크">
  </picture>
</p>

<p align="center">
  <em>게이트를 직접 만들었다. 그리고 그 게이트가 작업을 막았다.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-111111?style=flat-square" alt="MIT license">
  <img src="https://img.shields.io/badge/install-one%20file-111111?style=flat-square" alt="One file">
  <img src="https://img.shields.io/badge/works%20with-Codex%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor-111111?style=flat-square" alt="Works with">
  <img src="https://img.shields.io/badge/measured%20on-gpt--5.6--sol-111111?style=flat-square" alt="Measured on gpt-5.6-sol">
</p>

<p align="center">
  <strong>에이전트가 자기 작업 주위에 관료제를 짓는 걸 멈춘다.</strong><br>
  <sub>마크다운 한 장. 설정할 것도, 실행할 것도 없다.<br>
  <b>실측: 없이 돌린 런은 전부 아무도 요청하지 않은 절차를 만들어냈다. 적용한 런은 거의 전부 하나도 만들지 않았다.</b><br>
  <a href="benchmarks/">어떻게 측정했는지 보기</a></sub>
</p>

<p align="center">
  <sub><a href="README.md">English</a> &middot; <strong>한국어</strong></sub>
</p>

---

코딩 에이전트는 코드만 과설계하지 않는다. **자기 작업 주위에 관료제를 짓는다.** 게이트, 레지스트리, 추적성 매트릭스, 검증기를 검증하는 검증기. 그러고는 프로젝트 수명을 그걸 유지하는 데 쓴다. 결국 기계가 제품보다 커지면 작업을 통과시키지 않기 시작한다.

핵심 `sol-simplify` 스킬은 마크다운 한 장이며 플러그인이나 훅이 필수는 아니다.
아래에서 설명하는 선택형 리뷰 스킬에는 별도로 실행하는 로컬 실행기가 포함된다.

## 설치

쓰는 에이전트에 맞는 걸 고르면 된다. 그다음은 그냥 작업하면 된다. 필요한 작업이 오면 에이전트가 스스로 스킬을 읽는다. 호출할 게 없다.

**Codex.** 플러그인으로 넣으면 버전 관리와 업데이트가 된다.

```bash
codex plugin marketplace add MongLong0214/sol-simplify
codex plugin add sol-simplify@sol-simplify
```

**Claude Code:**

```
/plugin marketplace add MongLong0214/sol-simplify
/plugin install sol-simplify@sol-simplify
```

**파일만 복사해도 된다.** `~/.codex/skills/`, `~/.claude/skills/`, 또는 다른 도구의 rules 디렉토리(Cursor, Windsurf, Cline, Copilot) 아래에 **자기 폴더를 만들어** 넣는다. 표준 프론트매터가 붙은 평범한 마크다운이다. 폴더는 지켜야 한다. `skills/` 바로 아래에 `SKILL.md`를 그냥 두면 로드는 된다. 다만 나중에 플러그인을 설치하면 그걸 가리고 조용히 구버전을 먹인다.

```bash
mkdir -p ~/.codex/skills/sol-simplify
curl -sL https://raw.githubusercontent.com/MongLong0214/sol-simplify/main/skills/sol-simplify/SKILL.md \
  -o ~/.codex/skills/sol-simplify/SKILL.md
```

제거는 파일 삭제.

## 무엇을 하는가

**코드가 0줄이고 메인테이너가 1명인** 프로젝트의 개발 프로세스를 설계해달라고 했을 때:

**없이 돌리면** 437줄, 35개 섹션이 나온다: 리스크 기반 품질 게이트, 6단 테스트 계층, CI 운영 모델, 릴리스 후보 체크리스트, 결함 분류 체계, 프로젝트 건강 지표, 그리고 이 문서 자체를 유지보수하는 방법에 관한 섹션.

**적용하면** 58줄, 6개 섹션이다. 그리고 이유를 적는다:

> 혼자 작업할 때 의식용 자기 승인 PR은 만들지 않는다.
>
> 한 번의 실수를 이유로 새 문서나 전역 규칙을 추가하지 않는다.
>
> 검사가 제품 동작과 무관한 이유로 실패하면, 그 검사를 우회하는 예외 절차를 짓지 말고 검사를 고치거나 삭제한다.

프롬프트에 스킬 이름은 없었다. Codex가 스스로 찾아서 적용했다.

남기기로 한 절차에는 제거 조건을 붙인다. 나중에 감사할 수 있게, 영구히 굳지 않게:

```
sol-simplify: <이게 왜 존재하는가>, <어떤 조건이 되면> 제거
```

## 절대 자르지 않는 것

정확성. 실제 동작을 검사하는 테스트. 신뢰 경계의 입력 검증. 데이터 손실을 막는 에러 처리. 보안. 접근성. 데이터 마이그레이션. 명시적으로 요청한 모든 것.

절제는 에이전트가 발명한 절차에만 적용된다. 제품의 실제 의무에는 적용되지 않는다. PCI-DSS 감사를 앞둔 결제팀이 체크리스트·승인 절차·롤백 절차·감사 기록을 명시적으로 요구하는 시나리오에서, 스킬은 네 항목을 전부 유지했다. 모든 런에서 실제 PCI DSS v4.0.1 통제에 매핑해서 지켰다.

## 이미 병이 든 레포 진단

기존 레포를 진단하는 두 번째 스킬이 있다. 같은 방식으로 설치하고 *"이 레포 ceremony 감사해줘"* 라고 하면 된다.

```bash
mkdir -p ~/.codex/skills/sol-simplify-audit
curl -sL https://raw.githubusercontent.com/MongLong0214/sol-simplify/main/skills/sol-simplify-audit/SKILL.md \
  -o ~/.codex/skills/sol-simplify-audit/SKILL.md
```

기계 대 제품 비율을 재고 아무것도 출하하지 않은 유지보수 커밋을 찾아 삭제 우선순위를 매긴다. 보고만 하고 파일은 바꾸지 않는다.

## 같은 코드 리뷰를 반복하지 않기

선택형 **sol-simplify-review** 스킬은 구체적인 발견 사항을 보존하고, 그 근거로 수정과 회귀를
검토한다. 실행기는 1인용 trusted-local 도구이며 머지 게이트나 호스팅 서비스가 아니다.
리뷰할 checkout 밖에 둔 이 저장소의 설치본에서 실행한다:

```sh
skills/sol-simplify-review/scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" auto codex
skills/sol-simplify-review/scripts/review-pr.sh "$CONSUMER_REPO" "$PR_NUMBER" status codex
```

- 입력이 같으면 마지막 시도를 재사용한다. 코드·대상 커밋·제공한 맥락·lesson·응답·모델 설정·
  프로토콜이 바뀌면 다시 검토할 수 있다. 같은 입력으로 실패한 시도는 자동 재실행하지 않는다.
- 후속 리뷰는 원래 발견 사항과 최신 리뷰를 이어받는다. 이력이 다시 쓰이거나 기준점이 바뀌면
  새 범위를 검토하되, **동일 PR의 총 3회 예산** 안에서 진행한다. 횟수를 초기화하지 않는다.
- `status`는 모델 실행이나 Git fetch 없이 상태를 조회한다. 종료 직전 대상 커밋을 다시 확인하고,
  바뀌었거나 확인할 수 없으면 결과를 보존하되 오래된 결과로 표시한다.
- `report`는 GitHub 조회·fetch 없이 로컬 근거를 읽고, 실행 시작 시 프로토콜 해시와 종료 시
  신선도를 표시한다. 근거 검사 진행을 알리며, 과거 종료 시점의 신선도를 현재 PR 상태로 간주하지 않는다.
- 실행 제한 시간은 기본 1,800초이며 `REVIEW_TIMEOUT`으로 바꾼다. timeout·SIGINT·SIGTERM은
  실행기의 프로세스 그룹을 종료하고 실패 기록을 남긴다.

종료 코드 **10**은 근거 기록, **11**은 예산 소진에 따른 인계, **5**는 실패하거나 오래된 근거를
뜻한다. 어느 것도 승인이 아니다. 3회는 자동 반복 상한이지 정확한 리뷰·결함 해소·안전한 머지의
보장이 아니다. 공급자 내부 모델 리비전과 노출되지 않는 실행기 기본 설정은 확인 불가로 남긴다.

실행기는 Bash·Git·Python 3.9+가 필요하다. PR 조회에는 인증된 `gh`, 실제 리뷰에는 Codex 또는
Claude Code가 필요하다. 전체 오프라인 테스트와 선택형 Node 회귀 재생은 Node 22+를 사용한다.

```sh
bash skills/sol-simplify-review/scripts/selftest.sh
python3 dogfood/run.py --status  # 등록된 소비자 조회, 모델 호출 없음
python3 dogfood/run.py           # 한 번 조회·실행하고 종료, daemon 아님
```

`dogfood/consumers.json`의 메인테이너 로컬 경로를 수정하거나 `REVIEW_CONSUMERS_CONFIG`로 별도 파일을
선택한다. 플러그인 설치만으로 주기 실행이 시작되지는 않는다. 선택형 macOS poller·구현자 응답·
측정된 회귀 단서는 [소비자 가이드](dogfood/README.md)와 [실행 가이드](skills/sol-simplify-review/README.md)에
설명돼 있다. 소비자 리뷰는 push·댓글 작성·머지를 하지 않는다.

## 왜 만들었는가

<p align="center">
  <img src="assets/hero.svg?v=3" width="900" alt="감사한 레포의 git 히스토리 기반 선 그래프: 검증 기계 선이 20일 내내 제품 선을 앞서고, 6일차에 13,090줄인데 제품은 3,561줄이다. 17일차 표시는 에이전트 자신의 규칙이 모든 작업을 거부한 지점이다. 최종값은 기계 20,280줄, 제품 17,964줄.">
</p>

에이전트가 20일간 만든 레포 하나의 전체 git 히스토리에서 측정했다: **검증 기계 20,280줄 대 제품 소스 17,964줄**, 커밋의 33%가 기계 유지보수, 그리고 17일차에 에이전트 자신의 규칙이 모든 작업을 막았다. 커밋 메시지는 이렇게 적혀 있다:

```
docs: say where acceptance is decided, because the rule as written refuses all work
```

거기 있는 파일은 하나하나 다 정당하다. *표준 라이브러리를 써라, diff를 작게 유지해라* 같은 코드 수준 조언으로는 아무것도 막을 수 없었다. 실패가 코드에 있지 않기 때문이다.

```
1  선제적 거버넌스   제품이 존재하기 전에 게이트, ADR, 추적성, 레지스트리
2  검사 증식         모든 산출물에 검증기, 모든 검증기에 계약 테스트
3  자기 증폭         머지마다 pin 깨짐 → 재동기화 커밋 → 반복
4  자기 거부         에이전트가 작성한 절차가 에이전트의 작업을 거부
```

3·4단계는 다른 어떤 것도 다루지 않는 지점이자 한 줄 지시로 부족한 이유다.

## 효과가 있나

흔한 요청 5개를 각각 세 가지로 넣었다. 그냥, *"간단하게 해줘"* 한 문장을 붙여서, 스킬을 설치해서. 모델과 프롬프트는 매번 같다.

숫자는 **요청받지 않았는데 모델이 덧붙인 것**의 개수다: 근거 없는 응답시간 목표, 단계적 배포 계획, 1인 팀을 위한 승인 단계. **0이 가장 좋다.**

| 요청 | 그냥 | "간단하게 해줘" | **스킬 적용** |
|---|:--:|:--:|:--:|
| 북마크 버튼 1개 PRD 써줘 | 4–5 | 0 | **0** |
| 코드 0줄인 1인 프로젝트 개발 프로세스 설계해줘 | 5–6 | 1–2 | **0** |
| 감사 앞둔 결제팀이 절차 문서 4종을 요구 | 4종 + 2개 추가 | 4종 + 2개 추가 | **4종 + 추가 0** |
| 머지 사고 재발을 막아줘 | PR 템플릿과 영구 규칙 추가 | 테스트만, 집행 장치 없음 | **테스트와 그걸 집행하는 CI 검사** |
| 에이전트가 만든 게이트가 모든 작업을 막는다 | 다시 짓는다 | 눈앞의 불편만 치우고 기계는 그대로 둔다 | **기계를 삭제한다** |

두 번째 줄을 0으로 만들면서 잘라낸 건 없다. 그 문서에서 사라진 것은 릴리스 후보 체크리스트, 결함 분류 체계, 6단 테스트 계층이고 셋 다 아무도 요청하지 않았다.

이걸 쓰면 대충 만드는 게 아닐까 걱정된다면 세 번째 줄을 보면 된다. 절차가 정말 필요할 때는 전부 지킨다.

스킬 없이 돌린 런은 전부 이런 걸 1개에서 6개씩 만들어냈다. 스킬을 적용한 쪽에서는 한 런이 감사 시나리오에 카나리 배포 단계를 넣었다. 나머지는 아무것도 만들지 않았다. 모든 숫자는 커밋된 산출물의 라인으로 추적된다. 상세와 한계: [`benchmarks/`](benchmarks/).

## FAQ

**Ponytail 같은 코드 미니멀리즘 스킬과 뭐가 다른가?**
층이 다르다. 그쪽은 코드를 두고 *"한 줄로 되나?"* 를 묻는다. sol-simplify는 절차를 두고 *"이 검사가 존재할 이유가 있나?"* 를 묻는다. 같이 쓰면 된다.

**에이전트가 테스트를 건너뛰게 되나?**
실측: 아니다. 사고 시나리오의 모든 스킬 런이 근본 원인을 고치고 회귀 테스트를 추가했다. 동작을 검사하는 테스트는 절대 자르지 않는 목록에 있다. 실제 테스트를 자르는 걸 보면 이슈로 올릴 만한 버그다.

**다른 모델에서도 되나?**
모른다. `gpt-5.6-sol`을 위해 쓰고 그 위에서 측정했다. 이 실패 모드를 만드는 게 그 모델의 ambition 튜닝이다. 다른 환경 결과는 환영한다.

**왜 핵심 스킬은 마크다운 한 장인가?**
핵심 `sol-simplify` 스킬은 마크다운 한 장입니다. 선택적으로 쓰는 리뷰 스킬에는 명시적으로 실행하는
리뷰 실행기, 회귀 재생기와 로컬 테스트 훅도 있습니다. 플러그인 설치만으로 poller가 시작되지는 않습니다.

## License

MIT
