# 리뷰 스킬과 도그푸딩 재판정 — 2026-09-09

아래 첫 판정은 당시 실행의 역사로 보존한다. **후속 구현의 최종 방향, 3회 상한과 새 실증은
이 문서 끝의 「3회 상한과 실행 가능한 되먹임」에 있다.**

판정은 **결함 탐지 보조 도구로서는 효용이 있고, 두 라운드 수렴을 약속하는 자동 머지
게이트로서는 유효하지 않다**이다. 이번 변경은 후자를 철회한다. Markdown 허용 문법을
더 늘려 승인율을 올리는 것으로 문제를 해결했다고 선언하지 않는다. 현재 구현은 질문형
리뷰, 원본 근거 보존, 수정 차이에 대한 후속 검토를 제공한다. 실제 PR의 안전한 머지 완료는
이번에도 입증하지 못했다.

## 근거와 집계의 한계

먼저 읽은 원장은 `~/.sol-simplify-review/EVIDENCE.md`와
`~/.sol-simplify-review/artifacts/c8ec762c99769ce8/649/ledger.jsonl`이다. 후자의
`round-NNNN/ARTIFACT.md`, `prompt.txt`, 실행 기록을 대조했다. 추가로
`artifacts/1d6e6237b2424479/804/ledger.jsonl`과
`67ec065f842b0d34/pr830/ledger.jsonl`을 읽었다. 소비자 원본과 수정 커밋은 로컬
agent-operator-score, agent-control-plane, logic-pro-mcp 저장소에서 확인했다.
이 파일들은 호스트의 비공개 근거이며 이 저장소에 복제하지 않았다.

#649의 13번은 두 단계 프로토콜의 13회 완주가 아니라, 전부 phase 1을 시도한 기록이다.
열 번은 실행됐고 세 번은 실행 전에 거부됐다. 승인 inventory는 0건이다. 여러 head가
섞이므로 같은 코드에 대한 13개의 독립 실험도 아니다. 세 소비자의 확인 가능한 원장에는
총 21개 시도, 17개 실행이 있고, 승인된 1차 inventory와 phase 2 실행은 모두 0건이다.
따라서 발견 수로 후속 단계의 유효성이나 머지까지의 비용을 입증할 수 없다.

`inventory x10`은 열 개의 제품 결함이나 같은 가드의 동일 실패가 아니다. 기존 runner는
`check_shape`, `check_verdict`, `check_items`를 단락 평가하고, 상세 메시지는 stderr에
내보낸 뒤 원장에는 `invalid round-1 inventory`만 기록했다. 그 다음 binding, coverage,
sibling 비교도 같은 상위 이름에 들어갔다. #649 원장에 실제 남아 있는 상세 태그로 나누면
inventory 내부는 미상 4건, binding 2건, coverage 2건, enumeration 1건, sibling-sweep 1건이다.
미상 네 건을 추정으로 덮어쓰지는 않았다.

아티팩트를 읽으면 실패들이 다르다. 1라운드는 Verdict가 없고 필드 체계도 요청과 다르다.
7라운드는 원장이 보존한 ARTIFACT가 비어 있으며 마지막 메시지 추출도 실패했다. 이것을
완료된 리뷰로 부를 수 없다. 반면 5·6라운드는 host가 봉인한 SHA를 백틱으로 감싸 적었는데
binding에서 거부됐고, 9·10라운드는 rename의 이전 경로를 별도 READ로 인식하지 못했다.
12라운드에는 `## Verdict` 바로 아래 `**BLOCK**`과 두 coverage 축이 실제로 있다. 13라운드
O-09는 applicable_sites의 `lib/form-class.mjs:1285-1288` 안에 failing_sites의 `:1286`을
명시했는데 문자열 집합 포함 비교가 이를 거부했다. 이는 더 강한 모델이 필요한 증거가 아니라
가드가 의미를 잘못 대리한 구체적 사례다.

반대로 모든 미완성을 문법 탓으로 돌릴 수도 없다. logic-pro-mcp #830의 처음 두 산출물은
51개·82개 항목을 출력했지만 sweep 필드가 빠지고 두 번째는 Verdict도 없다. 다음 실행은
34개 항목으로 줄고 필드를 채웠다. 모델/예산/출력 요구량이 영향을 준다는 관측이다. 그러나
동일 모델·동일 head·동일 프롬프트를 통제한 실험이 아니며, 이 관측만으로 작은 모델 탓이나
PR 크기 탓 중 하나를 확정할 수 없다. 완결된 산출물도 거부됐으므로 그것만으로 게이트 실패를
설명할 수도 없다.

사용자가 제시한 `12 → 5 BLOCKER`도 같은 단위의 측정으로 쓰지 않는다. 12라운드의 결론은
여러 O/G/P 항목을 묶어 **일곱 가지** blocker라고 썼고, 13라운드는 다섯이라고 썼다.
기존 원장의 `fail_count`는 오히려 11 → 12이며 NIT와 정확히 `FAIL`인 필드도 섞여 있다.
또 P-03의 미호출 라이브러리 mutation 집계는 13라운드에도 남았는데 BLOCKER에서 NIT로
변했다. 감소에는 실제 수정, 같은 결함의 중복 항목, 심각도 재판정이 섞인다. 수렴의 확정
근거로 쓰기 어렵다. `/tmp/skill-log.txt`도 현재 파일은 23줄이 아닌 30개 커밋이다. 개수보다
각 커밋이 무엇을 고쳤는지를 기준으로 판단했다.

## 발견의 가치는 실제로 있다

AOS `295ea29`는 완료된 채점을 terminal lock 앞에서 서명된 pending completion으로 보존하고
재생하도록 바꿨다. `55b2900`은 발급 시점의 판단을 나중의 가변 ledger로 다시 판정하던 verify를
finalization receipt 기반으로 고치고, recovery를 모든 CLI 명령 앞에서 실행하던 것을 실제
소비 명령으로 좁혔다. `bdb7a36`은 재생할 수 없는 pending 자료를 격리하고 경로와 조치를
알리도록 바꿨다. `c419875`는 cycle의 미기록 완료 run을 복구하고 replay의 publication 부분까지
실패 분류와 복구 설명 안에 넣었다. 해당 diff와 새 회귀 테스트의 내용을 대조했다.

따라서 채점 유실, home 차단, 정당한 발급의 사후 뒤집힘은 추상적인 리뷰 의견이 아니다.
특히 `295ea29`가 추가한 전역 recovery, 가변 상태 기반 verify 재판정, publication 오류의
처리 누락이 후속 리뷰와 수정에서 다시 드러난다. 같은 날의 복구 작업이 회귀를 만들었다는
반대 증거도 무시할 수 없다. 다만 모든 13건 이상을 이번 작업에서 다시 실행·독립 재현한 것은
아니다. 수정 커밋의 테스트 결과 보고와 직접 실행한 결과를 구분한다.

카탈로그도 아무 값이 없었다고 판정할 수 없다. #649 10라운드 prompt는 catalog가 none이고,
12라운드는 열 개 프로젝트 ID를 공급한다. P-04/P-06은 기존의 명령 범위 문제에서 publication
실패로, P-09는 read/stat race의 다른 분기로, P-10은 재시도 가능한 원인을 영구 격리하는 분기로
조사를 확장했다. `c419875`의 변경과 이어진다. 그러나 P-04와 P-06은 같은 finding을 공유하고,
P-05/P-08도 한 항목으로 보고됐다. “여섯 클래스가 각각 독립적인 새 blocker를 찾았다”는
수를 여기서 독립 확정하지 않는다. 되먹임을 넣지 않은 같은 head와의 대조도 없어, 발견이
카탈로그 때문에 일어났다는 인과 효과의 크기는 알 수 없다.

다른 소비자에서도 #804의 두 리뷰가 19개와 14개 항목을 내고 서로 다른 blocker를 보고했다.
후속 `7fe2933`, `917ea39`는 reconnect/transfer 처리와 census 문제를 수정한다.
logic-pro-mcp의 `13ec2e60`, `5d7d2d80`도 잘못 성공하는 검사들을 수정한다.
이는 도구의 탐지 효용을 뒷받침한다. “자체 여섯 라운드가 놓쳤다”는 전체 이전 과정을 이번에
모두 대조한 것은 아니므로 그 비교 성능까지 증명했다고 쓰지 않는다.

## 형식에 대한 판정과 바꾼 의미

기존 Markdown은 자유 서술이라기보다 불완전하게 구현된 스키마였다. 수십 개 항목마다
정형 필드를 요구하고, 다양한 산문에서 exact status·site·coverage를 추출해 머지 조건으로
삼았다. 정규식을 보수할수록 지원 문법이 커졌지만 의미의 진실성은 증명하지 못했다.
가드를 세분화하면 진단은 나아진다. 그러나 행 범위와 그 내부 한 행이 다르다는 이유로
머지를 막는 설계까지 정당해지지는 않는다. 그래서 복합 inventory 가드를 분해해 더 많은
필수 가드를 만드는 대신, 산문을 승인 조건으로 삼는 계층을 삭제했다.

JSON schema를 첫 출력에 강제하는 대안은 문법 모호성을 줄인다. 그러나
`~/.claude/rules/grok-blind-review.md` §7에는 같은 모델의 schema 실행이 비어 있는 approve를
내고 질문형 재실행에서 실제 결함이 나온 세 사례가 있다. 이는 모든 구조화 출력에 대한
보편적 반증은 아니지만 이 워크플로에서 다시 기본값으로 삼기에는 불리한 관측이다.
도구를 23번 썼는데 보고한 filesRead는 하나인 사례도 있어 도구 횟수만으로 해결되지 않는다.

자유 리뷰 후 별도 추출기가 구조화하는 대안은 검토와 보고를 분리할 수 있다. 대신 누락·왜곡을
검사하고 원문에 맞추는 두 번째 작업이 필요하다. 추출기 결과를 자동 승인으로 삼으면 빈 봉투
문제는 다음 단계로 옮겨간다. 사람/담당 리뷰어가 원문과 확인하는 작은 handoff는 가능하지만,
현재 증거로 새 추출기와 그 검증 시스템까지 만들 근거는 부족하다.

선택한 대안은 질문형 산문 리뷰와 원본 보존이다. 다음은 의도적인 **프로토콜 의미 변경**이다.
첫째, 두 라운드 보장과 “모든 머지의 기본 자동 gate”를 철회했다. 둘째, 전 클래스의 PASS/N/A
봉투와 출력 필드 의무를 없앴다. 셋째, sweep가 미완성이어도 재현된 blocker를 FAIL/UNVERIFIED
규칙으로 희석하지 않고 blocker로 보고하게 했다. 넷째, 필요한 근거가 없으면 PASS를 추천할 수
없도록 기존의 상충하는 UNVERIFIED/PASS 문장을 정리했다. 다섯째, 후속 리뷰는 원본과 직전
후속 리뷰, Git의 전체 수정 diff를 읽는다. 미해결 finding과 범위 한계를 이어받고, 별도 escape
폼이나 hunk-ID 문법을 만족해야 시작할 수 있다는 조건을 없앴다. 두 prompt heading 다음의 첫
fence와 `{{PLACEHOLDER}}` 렌더링 계약은 유지했다.

새 runner의 `RECORDED`는 실행·target·원본 일치 기록일 뿐이다. BLOCK, PASS, 빈 승인 봉투,
TBD 산문 모두 자동 승인으로 바뀌지 않는다. 정상 기록은 **exit 10**, 실행/근거 실패는 5이고
review 실행에는 성공 0 경로가 없다. report/path/hunks의 0은 조회 성공이다. 기존 소비자가
exit 0을 merge 조건으로 사용했다면 그 연결을 바꾸고, 이미 있는 maintainer 리뷰와 제품 테스트가
머지를 결정해야 한다. “10을 0처럼 승인으로 취급”하는 이전은 같은 잘못을 반복한다.

잃는 것은 자동으로 산문의 파일 누락, ID 불일치, sibling 누락, PASS 모순을 거부하고 그 결과를
승인으로 사용하는 기능이다. 이 작업은 이제 근거를 읽는 리뷰어의 책임이다. 비용이 없다고
주장하지 않는다. 대신 산문 문법 때문에 근거가 버려지거나 1차 리뷰를 무한 재생성하는 비용을
제거한다. 자동 누락 감지가 반드시 필요한 환경에는 현재 도구가 충분하지 않다.

## 도그푸딩 구성별 판정

카탈로그는 유지하되 자동 승격을 없앴다. 기존 `catalog.py`는 같은 PR에서 같은 문구가 두 번
나오면 “independently”라고 썼고, 한 문장에 `recurs`나 `again`만 있어도 standing entry로
승격했다. 이는 “독립 변경/컴포넌트에서 재발”이라는 SKILL 규칙을 구현한 것이 아니다.
`97ddd71`은 미연결 되먹임을 만들었지만, `191af3b`가 잘못된 root를 고칠 때까지는 주입하지
못했고 `ea662c1`은 의무 ID 전달을 보수했다. 이제 원본 문장과 source round를 조사 단서로
전달하며, 자동 P-ID 생성과 필수 항목 수 증가는 없다. 명시적 host catalog는 계속 받는다.

거부 집계는 진단에 값이 있다. `97ddd71`이 넣은 집계와 후속 `a545554`의 두 coverage 구현
불일치 수정은 자기 가드의 결함을 보게 했다. 하지만 집계가 10회 거부를 멈추거나 PR을 머지로
보낸 증거는 없다. 새 보고는 원장에 있는 leaf 이유를 세고, 세부가 없는 inventory는 미상으로
남긴다. 항목 비율을 미발견 결함률이나 수렴률처럼 출력하던 기능은 제거했다.

pre-commit hook은 남겼다. installed/staged 두 suite를 staged Git tree에 실행하는 것은
후보가 테스트를 지워 통과하는 것을 막는 제한된 효용이 있고, 실패 witness로 확인됐다.
하지만 185 통과 상태에서 지금의 0승인과 문법 오거부가 발생했다. 이 훅은 구현한 규칙의
일관성을 검사했지 규칙의 유효성을 입증하지 않았다. 의미를 의도적으로 바꾸는 이번에는 새
버전을 검증한 뒤 그 버전으로 로컬 설치본을 갱신해야 한다. 옛 suite를 영구 권위로 두지 않는다.

소비자 등록과 poller 코드는 유지했다. `b3ed908`은 자기 등록 과정에서 추적되던 pyc의 경로를
제거했고, `3fe0a3c`는 실제 소비자가 아닌 repo-factory를 agent-control-plane으로 바로잡았다.
이는 구체적인 효과다. 다만 등록만으로 자동 실행이 생기지는 않는다. 점검 당시
`~/Library/LaunchAgents/dev.sol-simplify.review-dogfood.plist`는 없었다. 다른 scheduler의
존재까지 배제하지 않지만, 이 설치 경로의 지속 실행은 확인할 수 없다. poller는 새 exit 10을
기록 완료로 처리하고 실행 오류와 구분한다. poller의 0도 머지 승인이 아니다.

## 검증과 남은 판단

변경 전 selftest는 185 통과였고, 변경 후는 **112 통과, 실패 0**이다. 기존 이름 61개를
유지하고 124개를 폐기하거나 대체했으며 새 이름 51개에는 대체 검증도 포함된다.
변경 후 suite는 산문 문법·필수 ID·자동 verdict/escape
조건을 위한 사례를 제거하고, 자유 리뷰 handoff, 이전 미해결 finding 전달, 과거 거부 보존,
자동 승인 경로 부재, 실행·원본·head 실패를 검사한다. 숫자 감소는 제거한 승인 프로토콜의
검사를 유지하지 않았기 때문이다. 이는 과거의 185와 같은 품질 척도가 아니다.

실제 원장도 읽기 전용으로 재검증했다. #649의 13개 과거 결과와 0승인은 그대로다. 7라운드의
빈 원본을 제외한 실행 기록들은 문법 승인 없이 후속 검토의 근거가 될 수 있으며, 누락된
Verdict나 미확인 범위는 원문에 남는다. 이 확인에서 target-seal verify가 증거 디렉터리에
임시 파일을 쓰는 문제가 드러나 파일 생성 없이 hash를 재계산하도록 고쳤다. 잘못된 head,
변조된 inventory, 완료되지 않은 실행을 거부하는 검사는 유지했다. 세 소비자의 21개 과거
시도 모두 원장을 변경하지 않고 검사했고, 보존된 원본 16개를 후속 검토 입력으로 읽을 수
있었다. 이는 16개가 완결된 리뷰라는 뜻은 아니다. poller의 10/5 처리도 모델·네트워크 호출
없는 stub으로 각각 실행 완료/실패로 구분됨을 확인했다.

PR 하나를 머지까지 보내려면 확인된 실패를 같은 원인과 사이트별로 고치고, 새 회귀와 알려진
검토 공백을 실제 코드·테스트로 닫아야 한다. 범위를 한 번에 다루지 못하면 PR을 나누거나
검토 범위를 나눠야 한다. 13번째 원본을 다시 정형화하려고 14번째 전체 inventory를 요구할
이유는 없다. 남은 실패와 필요한 검증이 끝났는지는 기존 maintainer가 판단한다.

이 변경의 검증은 구현 동작과 과거 근거 보존까지다. 새로운 prompt를 실제 모델에 걸어 안전한
머지까지 완료한 실험은 하지 않았다. 재현 가능한 통제 benchmark도 여전히 없다. 따라서
현재 도구를 “안전한 자동 머지 게이트로 복구했다”고 부르지 않는다. 실패한 승인 기능을 철회하고,
확인된 효용에 맞게 리뷰 보조 도구로 범위를 바로잡았다는 것이 이 작업의 결론이다.

커밋 단계에서는 설치된 옛 훅이 `coverage-full: expected ok got fail`로 거부했다. 폐기한
Markdown 계약의 검사이므로 이를 만족시키려고 승인 기능을 되살리지는 않았다. 새 버전으로
훅을 갱신하는 명령도 `.git/hooks` 파일 쓰기 제한으로 `Operation not permitted: selftest.sh`가
발생했다. 따라서 작업 내용은 stage했지만 커밋은 생성하지 못했다. 푸시는 시도하지 않았다.

## 3회 상한과 실행 가능한 되먹임 — 후속 구현

제품은 **최대 세 번 자동으로 실행하고 근거를 인계하는 리뷰 보조 도구**로 정했다.
원일이 요구한 **안전한 머지 상태까지 최대 3라운드에 수렴하는 자동 게이트는 만들지 못했다.**
대신 세 번 안에 자동 시도를 끝내는 기능을 구현했다. 종료와 결함 해소를 같은 뜻으로 쓰지 않는다.
기존 재판정에서 철회한 산문 승인 게이트는 되살리지 않았다. 바꾼 결정은 무제한 후속 시도 허용과
수동 재생에 머물던 되먹임이다.

근거는 처음 재판정과 같다. 같은 봉인 head의 두 리뷰가 서로 다른 실제 blocker를 찾았고,
수정이 새 회귀를 만들었다. 한 라운드의 남은 결함은 이전 결함에서 닫은 것을 뺀 뒤 새 회귀와
새로 발견한 누락을 더한 것이다. 감소가 보장되지 않는다. inventory를 동결해도 수정 회귀를
차단 집합에 계속 넣으면 단조 감소가 아니다. 그것까지 제외하면 알려진 결함을 머지한다.
더구나 동결된 항목 하나조차 반드시 한 번의 수정으로 닫힌다는 전제가 없다. 기계 사실만으로
결정하는 게이트는 가능하지만 그 사실이 제품 안전과 같지는 않다. 이미 있는 CI에 새 이름의
승인 계층을 얹는 대신, 이 도구가 실제로 기여한 결함 탐지와 근거 재사용에 집중했다.

상한은 `protocol.MAX_ROUNDS = 3`과 PR별 잠금 안의 원장 검사로 구현했다. 새 디렉터리와
실행기를 만들기 전에 누적 `started` 수를 확인한다. 실패와 중단도 소비하며, head·base·응답·
phase 변경은 초기화하지 않는다. 3회째 정상 기록은 exit 11과 인계, 증거 실패는 exit 5와 인계다.
이후 호출은 exit 11로 원본 위치와 남은 사람의 판단을 보여주며 새 시도나 거부를 추가하지 않는다.
기존 13회·6회·3회 원장도 추가 예산을 받지 않는다. 과거 결과를 새 승인으로 고쳐 쓰지 않는다.
조회와 읽기 전용 재생은 계속 가능하다. 이는 안정된 PR ID·증거 root를 쓰는 협력적 호스트의
실행 횟수 상한이다. 사람이 원장을 지우거나 ID를 바꾸는 것을 막는 보안 경계도, 벽시계 제한도,
수동 수정 횟수 제한도 아니다. 설치된 스케줄러가 영원히 기다리는 실행을 종료한다는 보장도 없다.

이 도구 자체가 머지를 막거나 허용하는 조건은 없다. 실제 머지는 기존 필수 제품 검사와
maintainer 판단이 결정한다. 리뷰의 BLOCK 권고에는 재현된 미해결 결함, 수정 회귀, 뒤늦게 찾은
원래 결함을 모두 남긴다. 필수 증거가 없으면 PASS를 권고하지 않는다. NIT, 문장 형식, 카탈로그
반복 횟수, 세 번의 예산 소진은 제품 결함으로 승격하지 않는다. 요구 해석, 커버리지, 심각도,
이의 제기, 종결 근거와 실제 통합 대상의 위험은 사람에게 남는다. 알려진 blocker를 새 이슈로
밀어내서 상한을 만족했다고 표시하는 경로는 없다. 잃는 기능은 무제한 자동 재리뷰다.
상한 뒤에도 남은 결함은 수동으로 고치고 검토하거나 변경을 나눠야 한다.

도그푸딩의 새 `scripts/lib/witness.py`는 사람이 선택한 source review, 수정 전후 커밋,
테스트 파일·정확한 이름·질문을 받는다. 수정 후 테스트 파일의 같은 바이트를 두 임시 clone에
놓고 실행한다. Node 이벤트에서 해당 파일·이름의 유일한 테스트가 실제 assertion으로 실패한 뒤
통과한 경우에만 `LEAD.md`를 만든다. 파일 wrapper, 무선택, skip, TODO, 로드·일반 실행 오류,
timeout, 테스트 통과 뒤 프로세스 실패는 개선 증거가 아니다. 실패한 재생이 예전 성공을 그대로
발행하지 못하도록 기존 출력 디렉터리를 재사용하지 않는다. 명령·이벤트·종료 값·테스트와 원본
hash를 함께 남긴다. Node의 top-level `.mjs` 테스트만 지원하며 의존성 설치는 수행하지 않는다.
다른 러너는 그 러너가 내는 개별 테스트 결과를 읽는 어댑터가 필요하다.

소비자 설정의 `lessons` 또는 `REVIEW_LESSONS`로 선택한 디렉터리의 재생 질문은 이후 두 리뷰
phase 모두에 자동으로 들어간다. 현재 PR의 후보 수집과 명시적 카탈로그도 함께 전달된다.
poller는 발견·실행·기록·질문 재주입을 하고 exit 10/11을 완료로, 실행 실패를 오류로 구별한다.
선택한 재생은 명령 하나로 자동 실행한다. 원문에서 인과 관계를 자동 판정하거나 수정 패치를
작성하거나 상설 클래스 승격·머지를 하지는 않는다. 사람이 고른 질문이 이후 리뷰에 들어가는
실행 가능한 학습 경로이며, 모델 스스로 탐지율을 높였다는 실험과는 구분한다. 이번 작업에서
소비자 설정 변경이나 scheduler 설치는 하지 않았다.

실행 기록은 `/tmp/sol-20260909-evidence/`에 남겼다. 원장 재생은 각 소비자 저장소와 원장
디렉터리, 마지막 기록의 정확한 base·head를 `review-replay.sh`에 전달했다. 결과는 다음과 같다.

```text
AOS #649:   13 attempts; 10 executed; 9 preserved original reviews; exit 10
ACP #804:    6 attempts;  5 executed; 5 preserved original reviews; exit 10
Logic #830:  3 attempts;  3 executed; 3 preserved original reviews; exit 10
Total:      22 attempts; 18 executed; 17 preserved original reviews
Historical accepted inventories: 0. Phase-2 executions: 0.
```

입력의 21/17보다 #830 기록 하나가 더 있다. 당시 원장은 오류로 거부했지만 이벤트에는 연결
복구 오류 뒤 `turn.completed`와 exit 0이 있다. 현재 재생기가 읽는 것은 복구된 실행 증거다.
과거의 `accepted: false`는 그대로다. 같은 이유로 원장 leaf만 보고 종료 실패라 단정한 이번
작업 중간 보고도 이벤트를 본 뒤 정정했다. 17은 완전한 리뷰나 승인 수가 아니다. 세 원장과
그 증거 파일 196개를 작업 전후 전부 hash 비교해 추가·삭제·바이트 변경이 없음을 확인했다.

`a319ef0`을 요청한 AOS 원장 재생은 exit 5, `replay-target: no attempt is bound to the
requested base..head`였다. 마지막 원장은 `d85e68a`에 묶여 있다. `a319ef0`의 EN/KO 1965/1965,
mutation 987 command-reachable + 31 library-pending, ECD 1.10.0은 사용자 제공 상태이며,
이번에 전체 suite나 mutation을 재측정한 결과로 쓰지 않는다.

대신 그 head의 실제 회귀 테스트 하나를 새 helper로 재생했다. source는 #649 round-0013
원본이고 SHA-256은 `6b33dce1a599bb3673043a50356b61cf78da6f69d3f96120f556bf5aaf2d8351`이다.
실행한 호출은 아래와 같다. 변수는 로컬 AOS 저장소와 해당 원본 경로를 가리킨다.

```sh
python3 skills/sol-simplify-review/scripts/lib/witness.py \
  "$AOS_REPO" d85e68a a319ef0 tests/product/form-class.test.mjs \
  'every cross-facet comparison is withheld until invariance evidence exists, for each declared facet' \
  "$ROUND13_ARTIFACT" /tmp/sol-20260909-evidence/facet \
  --lesson 'Does a test derive its expected domain from the implementation it is meant to challenge? Check independently named requirement values, including omitted values.'
```

```text
Node: v22.23.2
Before: d85e68a0c301076144344e37f63ccc0fc5f1ec98
After:  a319ef0f60f6328f06072753c263b18fbe97ff2a
Same test SHA-256: 39bf40603db23249748aaaedb9d76dbbe1d6b8a309bbaa76bbf25dde0a128d86
before: test:fail, testCodeFailure, ERR_ASSERTION
  Expected domain includes platform, domain_familiarity, administration_version; actual omits them.
after: test:pass, skip=false, todo=false
Witness replay exit: 0. LEAD.md produced.
```

이 실제 `LEAD.md`를 `REVIEW_LESSONS`로 주고 로컬 Git·가짜 PR metadata·stub reviewer로
실제 `review-pr.sh`를 실행했다. 반환은 10, 생성된 prompt에 질문 파일의 전체 본문이 그대로
들어갔다(`feedback-delivery/result.txt`: `Actual replay lead delivered byte-for-byte: True`).
이는 소비자 실패 → 같은 테스트의 전후 차이 → 질문 생성 → 다음 리뷰 입력까지의 실증이다.
원래 발견을 카탈로그가 유발했는지, 새 질문이 모델의 탐지율을 높이는지는 측정하지 않았다.

같은 AOS `a319ef0`의 테스트 파일에 `--test-name-pattern=THIS_WITNESS_DOES_NOT_EXIST`를
주고 Node TAP 실행도 별도로 보존했다. exit 0, `# tests 1`, `# pass 1`, `# fail 0`이 나왔다.
wrapper 이름은 `tests/product/form-class.test.mjs`였다. 새 helper에 동일한 없는 이름을 주면
`GUARD FAIL [witness-selection] expected exactly one result for the named test in its file`로
거부했다. pass 개수 검사로 약화하지 않았고, 이 사례를 실제 Node 실행 selftest에도 넣었다.

최종 `./skills/sol-simplify-review/scripts/selftest.sh`는 **164 통과, 0 실패**다. 시작점은
127/0이었다. 기존 테스트의 기대와 실행 위치 일부를 새 상한에 맞췄다. 세 번째 실행이 계속 기록 상태에
머물던 기대는 terminal handoff 기대가 됐고, base·역방향 head·응답 테스트는 예산이 남은 별도
PR에서 원래 실패 원인을 계속 검사한다. 폐기한 보호 검사는 없다. 새 실패 witness에는 4회째
실행 시도, phase 재시작, 실패·중단 예산 우회, BLOCKER가 남은 세 번째 인계, base를 무시하는
cache, 없는 질문 디렉터리, 무선택·skip·TODO·로드 오류·timeout·중복 이름·종료 오류, 거꾸로 된
수정·동일 head·변경된 테스트 바이트·stale 출력 재사용이 포함된다. poller의 10/11/5/예상 밖 0
처리와 질문 전달도 실행했다. prompt 두 heading의 첫 fence와 placeholder 계약을 유지했고,
두 phase의 실제 렌더 및 누락 placeholder 실패를 검사했다. skill frontmatter 검사와
`git diff --check`도 통과했다.

원본 작업공간에서는 명시한 15개 파일만 stage하는 `git add`가
`.git/index.lock: Operation not permitted`로 거부됐다. 원래 main은 `4732565` 그대로이고
파일 변경은 워킹트리에 보존된다. `.git/hooks`를 수정하거나 권한 우회를 하지 않았다.
전달용 커밋은 쓰기 가능한 임시 clone에서 만들며, 원래 main에 적용된 커밋으로 보고하지 않는다.
원본 훅을 통한 커밋 검증도 실행되지 않았다. 푸시는 하지 않는다.
