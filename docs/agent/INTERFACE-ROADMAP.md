# 상세 실행 로드맵 — Python 기반 · Rust CLI/TUI · 에이전트 연동

기준일: 2026-10-30. 기준 코드: `main`의 AGENT-1 머지 `f473ff8`.
설계 근거: [승인된 ADR-0004](../adr/0004-rust-frontends-python-execution-agent-access.md).
이 문서는 승인된 방향의 구현 순서와 검증 기준을 구체화한다. 새로운 패키지
이동, 과학 계산 변경, 기존 명령 교체를 승인하는 문서는 아니다.

## 1. 최종 목표와 현재 위치

Python은 과학 계산·검증·데이터 처리를 담당한다. Rust는 CLI/TUI 사용 경험과
프로세스 제어를 담당한다. Skill과 MCP는 동일한 Python 실행 계약을 사용한다.
어느 인터페이스를 쓰더라도 같은 입력에 같은 과학 결과와 오류를 제공해야 한다.

```text
ARCH-1 설계 승인 [완료]
  └─ EXEC-1 공유 Python API / JSON 실행 [완료]
      └─ EXEC-2 Python 환경 선택 / 로컬 작업 수명주기 [완료]
          ├─ AGENT-1 공통 Skill [완료: 호스트별 미검증 범위 별도]
          │   └─ AGENT-2 선택적 MCP [미착수]
          └─ UI-1 Rust CLI [다음 단계]
              └─ UI-2 Rust TUI [미착수]
```

현재의 첫 공통 작업은 `thermo.summary` v1이다. 모든 분석 기능의 서비스화가
끝났다는 뜻은 아니다. UI-1과 AGENT-2는 EXEC-2 이후 독립적으로 진행 가능하며,
실제 작업은 한 백로그 항목씩 별도 브랜치·PR로 진행한다.

| 단계 | 실제 상태 | 근거 | 남은 범위 |
| --- | --- | --- | --- |
| ARCH-1 | 설계 승인·머지 | PR #28, `d447a30` | 후속 단계의 구체적 배포 결정 |
| EXEC-1 | 구현·검증·머지 | PR #29, `ed41c1f` | 다른 과학 작업은 개별 확장 |
| EXEC-2 | 구현·검증·머지 | PR #30, `07983bd` | 영속 작업·원격 실행은 범위 밖 |
| AGENT-1 | 구현·검증·머지 | PR #31, `f473ff8` | Claude/Codex 실호스트 검증·자동 호출 평가 |
| UI-1 | 미착수, 다음 구현 | 아래 7절 | Rust CLI 전체 |
| UI-2 | 미착수 | 아래 8절 | Rust TUI 전체 |
| AGENT-2 | 미착수 | 아래 9절 | MCP 어댑터 전체 |

## 2. 요청 조건과 반영 위치

| 조건·희망사항 | 구현 원칙 / 담당 단계 | 현재 확인 수준 |
| --- | --- | --- |
| Python 호환성 필수 | Python API·NumPy·과학 패키지 생태계 유지; EXEC-1/2, 모든 UI | 실제 Python 실행 및 설치 wheel 검증 |
| 기존 conda/venv 활용 | 명시 Python 경로, symlink 보존, 호환성 확인, 실패 후 환경 자동 변경 금지 | 실제 venv·공백 경로 검증; 모든 conda 조합을 검증한 것은 아님 |
| Rust CLI 및 대화형 TUI | UI-1 → UI-2; 계산 커널은 Python 재사용 | 설계 반영, 아직 미구현 |
| Claude/Codex/OpenCode 연동 | AGENT-1 공통 Skill + 얇은 호스트 안내; AGENT-2 MCP | OpenCode 발견·명시적 로딩 확인; 나머지 실호스트 미검증 |
| CLI·API·에이전트 결과 일치 | 동일 operation/schema/오류 계약과 직접 Python 기준값 대조 | 현재 thermo.summary 경로 검증 |
| 주석·코멘팅 항상 유지 | 새/중요 변경 함수·클래스·테스트에 영문 설명, 비자명한 분기에 이유 기록 | AGENTS.md 상시 규칙; 신규 Python 정의 점검 기록 |
| 로깅·개발로그 항상 유지 | 상태 이벤트·오류·정리 상태 보존, stdout은 프로토콜 전용, 단계별 로그 갱신 | EXEC-2/Skill 및 개발로그 반영 |
| 커밋은 사용자 이름 | 커밋 전 `Kim Donghwan <e1075536@u.nus.edu>` 설정 확인 | 현재 구현 커밋 확인; GitHub 머지는 같은 이메일의 Donghwan Kim |
| 건너뛴 테스트 확인 후 진행 | 각 skip의 이유·대체 실행 증거 기록; 미검증을 통과로 계산하지 않음 | native 전용 6개 재실행 및 개별 PASS 대조 |
| 실제 HPC 실행은 보류 | 로컬 분석·생성물 검증과 실제 LAMMPS/HPC 실행 구분 | 실제 HPC 미실행·후속 범위로 유지 |
| 기존 Python 사용자 보호 | Python-only 설치 유지, 기존 lkpr/import 보존, Rust 실행 파일 별도 | 기반 구현 유지; UI-1에서 재검증 |
| 범용화·과학 정확성 우선 | ADR-0001 및 GEN 경로 유지, 관련 REV 결함 해결 후 기능 공개 | 별도 과학 백로그와 연계; 범용화 전체 완료 아님 |

## 3. 모든 단계에 적용할 작업·완료 절차

1. 해당 백로그·ADR·선행 검증 기록을 읽고 이번 단계의 범위와 제외 범위를 기록한다.
2. 구현 전 요청/응답, 환경, 오류, 작업 소유권 및 호환성 결정을 개발로그에 명시한다.
3. 한 항목을 한 브랜치·PR로 구현한다. 기존 사용자 변경·fixtures·goldens를 보존한다.
4. 버그 수정은 실패 재현 → 수정 → 통과를 남긴다. 새로운 기능은 외부 계약과 실패
   경계를 검증한다. 기존 테스트 기대값을 편의상 바꾸지 않는다.
5. 영문 설명 주석과 상태·실패 로그를 유지한다. 로그를 과학 결과 stdout에 섞지 않는다.
6. 직접 Python 결과와 새 인터페이스 결과를 대조하고, 필수 로컬 검증을 실행한다.
   PR 전 저장소 full verifier를 실행하며 skip·없는 선택 의존성·미검증 플랫폼을 명시한다.
7. 독립 리뷰의 차단 이슈를 해결하고 개발로그·백로그·이 로드맵의 상태를 갱신한다.
8. 사용자 작성자 설정 확인 → feature branch 커밋·푸시 → PR 검증 → 명시적 승인된
   머지 순서로 마무리한다. 직접 main 푸시·force-push·이력 변경은 별도 승인 사항이다.

완료는 코드 존재만을 뜻하지 않는다. 테스트·설치/호스트 확인·실패 처리·문서가
해당 단계의 기준을 충족해야 한다. 미검증 항목을 다음 단계의 완료 실적으로 옮기지 않는다.

## 4. ARCH-1 — 책임 경계와 실행 순서 확정 [완료]

**목표:** Rust 도입과 Python 생태계 유지가 충돌하지 않는 구조를 승인받는다.

- 비교: Python shell 유지, Rust 전면 재작성, Python 임베딩, subprocess 경계.
- 선택: Python 계산·검증 + Rust UI + 공통 실행 계약; 초기 전송은 subprocess/JSON.
- 큰 배열·trajectory는 제어 JSON 밖에 두고 형식·단위·수명주기를 명시한다.
- Python API 사용자를 JSON/Rust에 종속시키지 않는다.
- 기반 → 로컬 실행 → 각 클라이언트 순서와 호환성·배포 승인 지점을 정한다.

**산출물/완료 근거:** ADR-0004 승인, MIGRATION/BACKLOG, PR #28.
실행 파일 이름·Rust crate 위치·배포 대상은 UI-1에서 결정할 미해결 구현 선택이다.

## 5. EXEC-1 — 공유 Python 작업과 구조화 실행 [완료]

**목표:** UI나 에이전트 없이 호출 가능한 검증된 과학 작업 하나를 만든다.

**구현 순서:**
1. 기존 thermo 통계를 공유 application 함수로 추출한다.
2. operation/version/request ID/input/parameters를 가진 엄격한 JSON 계약을 정한다.
3. `lkpr exec --capabilities` 및 `lkpr exec --request`를 제공한다.
4. Python API·기존 shell·JSON 경로를 같은 계산으로 연결한다.
5. 잘못된 입력·버전·비유한 숫자·행 파싱 오류를 명시적으로 실패시킨다.

**산출물:** `lammpkeeper/application.py`, `execution.py`, additive CLI,
회귀 테스트, [EXEC-1 개발로그](EXEC-1.md).

**완료 근거:** PR #29; 당시 native 461/0/0, NumPy 455/0/6,
설치 wheel/API/CLI 결과 일치. 이 수치는 당시 단계의 측정값이다.

**범위 제한:** `thermo.summary`는 통계 요약이며 `artifacts: []`이다.
그래프·trajectory·정밀 timeline·species/PBC 작업의 전체 계약 검증을 대신하지 않는다.
입력 stat fingerprint는 content hash가 아니다.

## 6. EXEC-2 — 선택 환경에서의 로컬 작업 실행 [완료]

**목표:** CLI/TUI/에이전트가 동일한 작업 상태와 실패·취소 규칙을 사용할 수 있게 한다.

**구현 순서:**
1. Python 선택 우선순위(명시 경로 → LKPR_PYTHON → 실행 중 interpreter)를 고정한다.
2. cwd·환경·요청을 제출 시점에 고정하고 venv symlink를 보존한다.
3. capability handshake로 버전·operation 호환성을 확인한다.
4. LocalJob/start_job, snapshot/wait/cancel, ordered state events를 제공한다.
5. 전체 작업 deadline, bounded stdout/stderr, 자식 프로세스 종료/정리를 구현한다.
6. 취소·timeout과 정리 실패를 별도 필드로 보존하고 stale success를 차단한다.

**산출물:** `lammpkeeper/jobs.py`, `lkpr run`, 32개 집중 회귀,
[EXEC-2 개발로그](EXEC-2.md).

**완료 근거:** PR #30; native 및 pytest 493개 통과, NumPy 487개 통과·6 native
전용 skip. 6개 모두 개별 PASS 대조. 저장소 밖 실제 venv 설치 실행 검증.
실제 런타임 검증은 Python 3.11이며 Python 3.9는 문법 검사만 수행했다.
Python 3.9 런타임·비POSIX lifecycle·MDAnalysis는 미검증이다. 지원 Python
버전과 플랫폼을 확대 주장하기 전에 해당 환경의 실제 실행 결과를 확보해야 한다.

**범위 제한:** POSIX/non-reaping waitid 기반 process-owned 작업이다. 이벤트는
상태 전환이지 과학 계산 진행률 %가 아니다. 영속 작업 조회·재시작 복구·daemon·HPC는
제공하지 않는다. OS가 정리를 허용하지 않는 경우 실패/불완전 정리를 정직하게 보고한다.
현재 작업은 과학 파일을 만들지 않으므로 partial artifact 정리는 향후 생산 작업에서 검증한다.

## 7. UI-1 — additive Rust CLI [다음 구현]

**선행 조건:** EXEC-1/2 완료. 기존 Python `lkpr`를 덮어쓰지 않는다.

**구현 순서:**
1. 설계 기록: 별도 실행 파일 이름, crate 위치, Rust 최소 버전, 대상 OS/배포 방식,
   Python/backend 호환성 정책을 확정한다. 필요한 구조 변경은 구현 전 승인받는다.
2. Rust는 선택 Python을 subprocess로 호출한다. 최초 구현은 기존 `exec`/`run`
   계약을 소비하며 과학 커널·별도 작업 상태 머신을 재작성하지 않는다.
3. capability 및 환경 진단을 제공한다. 미설치·경로 오류·버전 불일치에서 명확히 실패한다.
4. thermo.summary 요청을 구성하고 JSON 결과/상태 이벤트를 읽는다.
5. 사람이 읽는 출력과 기계 출력 모드를 분리하고 단위·경고·provenance를 유지한다.
6. Ctrl-C와 timeout을 기존 작업 소유권에 연결한다. Rust 부모 중단 시 Python supervisor와
   손자 프로세스가 어떻게 정리되는지 명시·시험하고, 단순 kill을 취소 완료로 취급하지 않는다.
7. 설치된 Rust binary + 저장소 밖 Python wheel/venv 조합으로 검증한다.

**예정 산출물:** 별도 Rust CLI, 설치/환경 선택 안내, protocol client 및 계약 테스트,
`docs/agent/UI-1.md`. 최종 이름·경로는 아직 결정되지 않았다.

**완료 기준:**
- 직접 Python/기존 CLI/구조화 CLI/Rust 결과가 값·단위·경고·오류에서 일치한다.
- 공백 경로·선택 venv·missing backend·incompatible version·malformed JSON·큰 출력·
  child crash·timeout·Ctrl-C에서 비정상 종료와 정리 상태가 올바르다.
- signed integer 문자열과 null/비유한 값 규칙을 손실 없이 취급한다.
- Python-only 설치·기존 lkpr·기존 imports가 그대로 작동한다.
- 측정한 플랫폼만 지원으로 표기한다. Rust 설치가 Python core 필수 조건이 되지 않는다.

## 8. UI-2 — Rust TUI / 대화형 로컬 워크플로 [미착수]

**선행 조건:** UI-1의 실행 client 및 중단/정리 계약이 검증되어야 한다.

**구현 순서:**
1. TUI 라이브러리·터미널 지원 범위·키 동작·화면 상태 모델을 기록한다.
2. 입력 선택 → 설정 확인 → 실행 → 상태/경고 → 결과 → 취소 흐름을 구현한다.
3. 화면 갱신과 backend 실행을 분리해 작업 중 UI가 멈추지 않게 한다.
4. 각 실행에 명시적 전체 요청을 보내고 서로 다른 worker의 cache 공유를 가정하지 않는다.
5. 요청/작업 ID에 결과를 연결한다. 입력 변경·새 작업·취소 후 이전 성공을 현재 결과로
   표시하지 않는다. 오류·warnings·cleanup health를 화면에서 확인할 수 있게 한다.
6. 정상 종료·Ctrl-C·panic·child crash 후 터미널 복구와 비TTY 동작을 검증한다.

**예정 산출물:** TUI 화면/상태 관리, UI-1 공통 client 재사용, PTY 통합 테스트,
사용 안내와 `docs/agent/UI-2.md`.

**완료 기준:** load/configure/run/status/results/cancel 경로가 실제 backend와 동작하고,
잘못된 입력·중단된 작업에서 stale success가 없다. 이벤트에 없는 % 진행률을 만들지
않는다. 터미널 복구·비차단 동작·단위/경고 표시를 자동/수동 검증으로 구분해 기록한다.
첫 TUI의 완료는 전체 prep/post 기능 이식을 뜻하지 않는다.

## 9. AGENT-1 / AGENT-2 — Skill과 MCP

### AGENT-1: 공통 workflow Skill [구현 완료]

**구현 흐름:** capability 발견 → 입력/환경 확인 → 구조화 요청 → 실행 → 상태·오류·
단위·경고·정리 확인 → 재현 가능한 보고와 증거 보존.

**산출물:** `.agents/skills/lammpkeeper`, Claude 프로젝트 symlink, 호스트별 안내,
3개 paired 평가와 12개 assertion, [AGENT-1 개발로그](AGENT-1.md).

**완료 근거:** PR #31. Skill 평가 12/12; full verifier 487/0/6.
OpenCode에서 자동 발견 및 명시적 Skill 로딩 확인. baseline도 과학 결과는 정확했으며
차이는 주로 구조화 실행 증거다. 속도·토큰 효율 향상은 측정하지 않았다.

**남은 호스트 확인:** Claude Code와 Codex 각각에서 버전·발견 경로·명시적 로딩·
정상/실패 실행 결과를 기록한다. 자동 호출 정확도는 별도 평가다. 문서상 호환성을
실호스트 통과로 계산하지 않는다. 사용 가능한 호스트 환경에서 후속 검증 항목으로 수행한다.

### AGENT-2: 선택적 MCP 어댑터 [미착수]

**선행 조건:** EXEC-2와 AGENT-1. TUI 완료를 기다릴 필요는 없다.

**구현 순서:**
1. 실제 backend capability에 맞춰 inspect/run/status/result/cancel 도구 범위와
   schema·오류 매핑·Python 환경 선택을 명시한다. 정확한 도구 이름은 이 단계에서 정한다.
2. 초기 전송은 local stdio, 설치는 선택 기능으로 제공한다.
3. 과학 실행과 작업 상태는 기존 application/LocalJob에 연결한다.
4. 서버가 보유한 handle의 소유권·동시 작업·종료 시 취소/정리 규칙을 정한다.
5. MCP 메시지 stdout과 backend/log stderr를 분리한다.
6. 클라이언트 연결 종료·중복 취소·timeout·backend crash를 시험한다.
7. 실제 각 호스트에서 연결·tool discovery·성공/실패 호출을 확인하고 지원 행렬에 기록한다.

**예정 산출물:** optional MCP 패키지/entry point, 도구 schema와 lifecycle 매핑,
설치/호스트 안내, parity/error 테스트, `docs/agent/AGENT-2.md`.

**완료 기준:** 직접 Python/CLI와 결과·오류·단위·warnings가 일치한다. 지원하지 않는
작업은 명시적으로 거절한다. 서버 재시작 뒤 UUID만으로 작업 복구를 약속하지 않는다.
Python-only 설치에 MCP 의존성이 들어오지 않는다. artifact 생산 작업을 노출하는 경우
실제 파일 존재·완료 여부·형식·소유권/수명 검증도 함께 통과해야 한다.

## 10. 후속 과학 작업 확장과 별도 결정

새 operation마다 다음 절차를 반복한다:
1. 관련 REV 오류와 GEN metadata/domain 의존성을 먼저 확인한다.
2. 기존 과학 함수를 공유 application 계약에 연결한다.
3. 파라미터·units/species/PBC·provenance·오류와 capability를 정의한다.
4. 큰 배열/파일 출력은 형식·shape/dtype·단위·수명·실패 시 불완전 표시를 정의한다.
   pickle 로딩을 요구하지 않으며 제어 JSON에 trajectory를 넣지 않는다.
5. 직접 Python과 각 공개 client의 일치 및 실패/취소 검증 후 순차 공개한다.

PR #26/#27은 아직 열려 있는 charge 관련 수정이다. 현재 thermo.summary 완료와
별개이며 해당 분석 공개 전 해결해야 한다. 그 밖의 미해결 REV 항목도 관련 작업의
차단 조건으로 확인한다. GEN-2 metadata, GEN-4 domain 분리 및 GEN-8 비Fe 참조계는
기존 별도 로드맵을 유지한다. GEN-9 전면 이동을 UI 작업의 선행 조건으로 만들지 않는다.

다음은 아직 승인·구현된 제공 기능이 아니다: Rust로 기존 lkpr 대체, Python 임베딩,
영속 서비스/재시작 복구, 원격/HPC 제출, 새로운 저장 형식·필수 의존성 도입.
각각 필요가 입증될 때 별도 설계·호환성·검증 절차로 결정한다.

## 11. 기존 전체 프로젝트 단계와의 연결

인터페이스 개선은 과학 정확성·범용화 로드맵을 대체하지 않는다.

| 기존 단계 | 상태 | 후속 진행 순서와 완료 조건 |
| --- | --- | --- |
| Phase 0 재현성 | REL-0 완료 | thesis tag 보존; 역사적 재현성과 현재 정확성 검증을 구분 |
| Phase 1 테스트·물리 교정 | 기존 주요 항목 완료, 후속 REV 일부 미해결 | 관련 실패 재현 → 수정 → 독립 oracle/회귀 → 리뷰 순서; open REV를 완료로 표시하지 않음 |
| GEN-1 species model | 완료, PR #19 | system-owned species/group 계약을 새 operation에서도 사용 |
| GEN-3 box/PBC | 완료, PR #20 | 지원되는 triclinic/PBC는 검증된 geometry 재사용; 미지원 소비자는 명시적 거절 |
| GEN-2 명시적 metadata | open, 설계 승인·관련 검토 필요 | input/manifest에서 FF·units·atom_style 해석 → 충돌 검증 → heuristic 최후 수단 경고 → LJ/EAM을 Fe 전용 모델로 오인하지 않는 시험 |
| GEN-4 domain 분리 | open, GEN-2 이후 | Fe/O 전용 분석·상수를 domain pack으로 이동 → 기존 import shim → generic 경로의 원소 하드코딩 점검 → Fe-O 회귀 |
| GEN-5 molecule/bond | open | generic per-pair cutoff·PBC pairing → O2 preset 연결 → 기존 결과 및 A–B 합성 분자 검증 |
| GEN-6 HPC site profiles | deferred | 사이트 설정과 run logic 분리 → 기존 NUS 출력 보존 → local/Slurm 문법·실패 주입; 실제 HPC는 별도 사용자 승인 후 |
| GEN-7 generic prep | open | ASE/CIF/data 구조 입력 → 사용자 분자/영역 배치 → data-driven FF registry → Fe-O recipe 보존 및 비Fe 생성물 확인 |
| GEN-8 두 번째 참조계 | open, 사용자 시스템 선택 필요 | 생성 스크립트·작은 fixture·독립 기대값 확정 → 두 참조계 full verifier; fixture 추가 승인 필요 |
| GEN-9 패키지 정리 | open, 마지막 | 승인된 layout으로 이동 → deprecation shim·문서·버전 정책 → 기존 entry point/import 호환 테스트 |

GEN-6의 11월 초·중순 이후 보류 기록은 자동 실행 날짜가 아니다. GEN-7의 실제
LAMMPS 확인과 GEN-8의 실제 참조계 확보는 사용자 환경/선택에 의존하며 현재 로컬
합성 시험으로 대체 완료 처리하지 않는다. 상세 과학 항목은 BACKLOG의 해당 ID가 기준이다.

## 12. 바로 다음 실행 순서

1. UI-1 설계 노트에서 실행 파일·crate·배포 대상·중단 소유권을 확정한다.
2. 승인된 구조 안에서 가장 작은 capability/thermo.summary Rust client를 구현한다.
3. 직접 Python 대조와 환경/실패/취소 검증 후 별도 PR로 마무리한다.
4. 이후 UI-2를 진행한다. AGENT-2는 필요 우선순위에 따라 독립 항목으로 진행 가능하다.

고정 일정이나 구현되지 않은 기능의 완료 날짜는 추정하지 않는다. 각 단계가 위 완료
기준을 충족할 때만 상태를 갱신하며, 다음 단계 시작 전에 미검증 항목을 다시 확인한다.

## 문서 정비 기록

2026-10-30: 사용자 요청으로 단계별 상세 계획과 조건 추적표를 작성했다.
GitHub 상태를 조회해 PR #28–31 머지 및 #26/#27 open을 대조했다. 기존 안내의
TEST-1 skip 집계 미해결 문구와 교정 전 MSD golden 예시를 완료 기록에 맞게 수정하고,
사용자 명의 커밋 확인을 AGENTS.md 상시 규칙에 추가했다. ADR·런타임·과학 계산·
fixtures는 변경하지 않았다. 문서 리뷰와 저장소 검증 결과를 공개 전에 기록한다.
