# Cursor CLI + pstack 운영 가이드 (LammpKeeper)

사람이 읽는 운영 문서입니다. 에이전트용 규칙은 `AGENTS.md`와 `.cursor/rules/`에 있습니다.
작성 기준: Cursor CLI 문서·changelog(v2026.10.08), pstack 공개 문서(2026-10).

## 0. 파일 구성

| 파일 | 역할 | 로드 시점 |
|---|---|---|
| `AGENTS.md` | 프로젝트 원칙, 명령어, 물리 불변량, golden 정책, 사람 승인 지점, pstack 사용 규칙 | 항상 (CLI가 자동으로 읽음) |
| `.cursor/rules/physics-analysis.mdc` | 분석 코드 체크리스트 (PBC, ID 추적, 원소 선택, 빠른 경로/느린 경로 일치) | `lammps_post/*` 파일을 다룰 때 |
| `.cursor/rules/hpc-job-scripts.mdc` | PBS 스크립트 안전 규칙 | `lammps_pre/templates.py` 등을 다룰 때 |
| `.cursor/rules/tests-and-goldens.mdc` | 테스트 작성과 golden 재설정 규칙 | `tests/**`를 다룰 때 |
| `.cursor/skills/verify-lkpr/` | 프로젝트 검증 skill (pstack의 "prove it works" 단계에서 사용) | `/verify-lkpr` 호출 시, 또는 자동 |
| `.cursor/cli.json` | CLI 명령 허용·거부 목록 | 항상 |
| `docs/agent/BACKLOG.md` | 작업 항목과 각 항목의 완료 조건 (Phase 0 재현성 / 1 정확성 / 2 범용화) | 세션 시작 시 지정 |
| `docs/agent/PROMPTS.md` | Cursor에 붙여 넣는 프롬프트 모음 (P0–P10) | 사람이 복사해서 사용 |
| `docs/adr/` | 설계 결정 기록. `0001`은 범용화 아키텍처(proposed) | 구조 변경 전 |
| `tests/pending_review_findings.py` | 미해결 결함의 재현 테스트 (테스트 러너가 수집하지 않음) | Bug fix 첫 단계에서 사용 |

## 1. 처음 한 번 하는 설정

1. **CLI 버전 확인.** 플러그인, skill 같은 기능은 2026년 3월 이후 버전부터 들어왔습니다. 최신 버전으로 맞추십시오.
2. **개발 환경 준비.** 가상환경에서 `pip install -e .[all,dev]`를 실행하고, `gh auth status`로 GitHub 로그인 상태를 확인합니다. ASE가 없으면 prep 관련 테스트가 실제로는 실행되지 않습니다.
3. **pstack 설치.** 공식 안내 방식은 IDE 채팅에서 `/add-plugin pstack`입니다. CLI에서는 `/plugin` 메뉴로도 설치할 수 있습니다.
   - 설치 후 반드시 CLI에서 `/skills`를 열어 `poteto-mode`와 `verify-lkpr`이 **둘 다** 보이는지 확인하십시오.
   - 과거에 "플러그인의 skill이 CLI에는 등록되지 않는다"는 버그 보고가 있었습니다.
   - 보이지 않으면 IDE에서 사용하거나, 커뮤니티 포팅판을 `~/.cursor/skills/`에 두는 방법을 검토하십시오.
4. **`/setup-pstack` 실행.** 역할별 모델 설정이 `~/.cursor/rules/pstack-models.mdc`에 저장됩니다. 실행 후 **새 채팅**을 시작해야 적용됩니다.
   - 기본값은 코드 작성 Grok, 판단·문장 작성 Opus 5.5입니다.
   - 이 저장소는 물리 해석 코드의 비중이 커서, Bug fix 구현 역할도 Opus로 지정하는 것을 고려할 만합니다. 정확도는 오르고 비용도 늘어납니다.
   - 설정 중 검증 skill을 새로 만들겠냐고 물으면 **거절**하십시오. 이미 `verify-lkpr`이 있습니다. 점검은 `/maintain-verification-skill`로 합니다.
5. **권한 확인.** `.cursor/cli.json`에서 `git:status*` 같은 인자 패턴은 공식 문서의 `curl:*` 예시를 근거로 작성했습니다. 처음 한 번은 실제로 의도대로 허용·거부되는지 확인하십시오. 참고로 `Shell(python)` 전체 허용은 편의를 위한 절충입니다. python으로는 사실상 무엇이든 실행할 수 있습니다.
6. **기준 브랜치 결정.** 현재 작업 브랜치는 `parser-streaming`입니다. BACKLOG 작업을 이 브랜치에서 할지, `main`에 병합한 뒤 시작할지 먼저 정하십시오.

## 2. 기본 작업 흐름: 백로그 1건 = 세션 1개 = PR 1개

```bash
cd ~/projects/lammpkeeper
agent -w phys-1          # 격리된 git worktree에서 시작 (~/.cursor/worktrees/...)
```

세션 첫 메시지 템플릿:

```
/poteto-mode docs/agent/BACKLOG.md의 PHYS-1을 처리해줘. 기준 브랜치는 main.
done when: BACKLOG의 "Done when"을 충족하고 /verify-lkpr full이 PASS.
golden 값을 바꿔야 하면 별도 커밋으로 분리하고, 커밋하기 전에 나에게 승인을 요청할 것.
```

진행 중 확인할 것:

1. 재현 테스트가 **실패하는 출력**을 실제로 보여주는지.
2. `Ctrl+R`로 diff를 검토하고, 필요하면 `i`로 추가 지시를 넣습니다.
3. 물리 관련 변경이면 `/interrogate` 결과에서 "act on"으로 분류된 항목을 확인합니다.
4. 마지막에 `/verify-lkpr full`의 `summary.txt`가 인용되고, SKIP 항목이 명시되는지.
5. PR이 열리면 **merge는 본인이** GitHub에서 합니다.
6. BACKLOG의 해당 항목 상태가 갱신됐는지.

권장 순서는 BACKLOG 상단에 있습니다: REL-0 → (Phase 1) TEST-1 → OPS-1 → HPC-1 → … → (Phase 2) GEN-1 → …
테스트 기반 정비를 먼저 하는 이유는, 그래야 나중에 나오는 "전부 통과"라는 결과를 믿을 수 있기 때문입니다.
상황별 프롬프트 전문은 `docs/agent/PROMPTS.md`에 있습니다.

## 2-1. 범용 툴로 키우기 위한 원칙

최종 목표는 Fe-O 산화에 한정되지 않는 범용 LAMMPS 전·후처리 도구입니다. 그래서 지침도 이 방향을 전제로 짰습니다.

1. **재현성 고정이 먼저입니다 (REL-0).** 학위논문·논문에 쓴 숫자를 재현할 수 있는 커밋에 태그를 붙인 다음에 구조 변경을 시작합니다.
2. **정확성이 범용화보다 먼저입니다 (Phase 1).** 주기 경계 처리나 원소 선택이 틀린 상태로 일반화하면, 그 버그가 모든 계로 퍼집니다. 다만 Phase 1의 수정도 처음부터 범용 형태로 합니다. 원소는 타입 집합으로, 주기성은 `pbc` tuple로 다룹니다.
3. **ADR로 먼저 결정합니다.** 레이어 구조는 `docs/adr/0001`에 proposed 상태로 적어 두었습니다. "Open questions" 다섯 가지(범위, 설정 파일 형식, 직접 구현 vs 외부 라이브러리, 배포 방식, 두 번째 기준 계)는 **직접 답하셔야 accepted가 됩니다.** 그 전에는 GEN 항목을 시작하지 마십시오. 프롬프트 P1로 검토를 시작할 수 있습니다.
4. **한꺼번에 갈아엎지 않습니다 (strangler 방식).** 새 경로를 만들고, 호출부를 하나씩 옮기고, Fe-O 결과가 그대로인지 확인한 뒤 옛 경로를 지웁니다. Fe-O는 버리는 것이 아니라 첫 번째 domain pack이자 기준 검증 계가 됩니다.
5. **범용성은 증거로 확인합니다.** 테스트에 임의 라벨(`"A"`, `"B"`)을 쓰고, Fe가 아닌 두 번째 기준 계(GEN-8)를 둡니다. 둘 다 통과해야 "범용"이라고 할 수 있습니다.
6. **지침의 범위 가정:** 현재는 "LAMMPS 전용 범용 도구"를 전제로 합니다. 다른 MD 엔진까지 다룰 계획이면 ADR-0001의 첫 번째 open question에서 정하시면 되고, 그 경우 `io` 레이어의 경계를 다시 설계해야 합니다.

## 3. 상황별 사용법

| 상황 | 방법 |
|---|---|
| 한 줄짜리 명백한 수정 | pstack 없이 바로 지시 (비용 절약) |
| 코드 이해 (예: "O₂ 검출은 어떻게 동작하나") | `/how …`, 설계 배경은 `/why …`. 편집이 필요 없으면 `agent --mode=ask` |
| 새 분석 기능 | `/architect`로 시그니처와 모듈 위치를 먼저 확정한 뒤 `/poteto-mode feature: … done when …` |
| 숫자가 이상할 때 | `/poteto-mode investigation: … ` + 원칙 `explain-the-number`, `prove-it-works`를 명시 |
| 수정 영향 범위가 걱정될 때 | `/blast-radius` |
| 에이전트가 같은 실수를 반복할 때 | `/correct`. 수정 위치는 코드·테스트를 먼저, 규칙·문서는 그다음으로 고르게 합니다 |
| 긴 세션을 마친 뒤 | `/reflect`. 제안된 AGENTS.md·rules 변경은 직접 읽고 승인 |
| 빠른 무인 점검 | `agent -p "/verify-lkpr quick" --output-format text` (아래 주의 참고) |

헤드리스 모드(`-p`)에서는 에이전트가 파일 쓰기 권한을 전부 갖습니다. 검증처럼 읽기 위주인 작업에만 쓰십시오.

## 4. 오래 유지하기 위한 습관

- **AGENTS.md는 짧게 유지합니다** (지금 약 120줄). 교훈은 테스트나 코드로 먼저 고정하고, 다음이 scoped rule, 마지막이 문서입니다. pstack의 `encode-lessons-in-structure` 원칙과 같은 방향입니다.
- **사람 승인 지점은 제가 정한 기본값입니다** (AGENTS.md §7). 운영해 보면서 너무 잦거나 부족하면 조정하십시오.
- **정기 점검:** 큰 변경 후나 월 1회 `/maintain-verification-skill`을 실행합니다. 이 skill은 제품 코드를 수정하지 않습니다.
- **비용 관리:** `poteto-mode`는 subagent와 리뷰 패널을 띄우므로 토큰을 많이 씁니다. 세션당 한 건만 처리하고, 길어지면 `/summarize`를 쓰십시오. `/arena`, `/swarm`은 꼭 필요할 때만 씁니다.
- **golden 값 변경은 항상 사람이 승인합니다.** 커밋 메시지에 이유와 독립 검증이 없으면 거절하십시오.

## 5. 하지 말 것

- "테스트를 전부 통과시켜" 같은 결과만 지정한 지시. golden 값을 고쳐서 통과시키는 방향으로 유도됩니다. 항상 BACKLOG의 "Done when"을 완료 조건으로 주십시오.
- Orchestrate, Autopilot, Benny playbook 사용. 이 저장소에는 Graphite가 없고 관리자가 한 명입니다.
- `tests/fixtures/` 수정, 여러 백로그 항목을 한 세션에서 동시에 처리하는 것.

## 6. 이 설정이 보장하지 않는 것

- **실제 LAMMPS/HPC 실행.** HPC-1을 고친 뒤에는 작은 job을 한 번 직접 제출해 확인하십시오. 일부러 복사 실패를 낼 수 있다면 더 좋습니다.
- **slab(`p p f`) 분석 경로.** 현재 fixture는 bulk(`p p p`)입니다. TEST-3이 끝나기 전까지는 미검증 상태입니다.
- **Fe-O 외의 계와 triclinic 상자.** GEN-3, GEN-8이 끝나기 전까지는 "범용"을 주장할 근거가 없습니다.
- **pstack이 내세우는 보장.** 상당 부분이 실행 코드가 아니라 지시문입니다. 최종 판단 근거는 테스트, `verify-lkpr`의 증거 파일, 그리고 본인의 diff 검토입니다.
