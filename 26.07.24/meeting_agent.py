"""회의 자동화 Agent — CrewAI 소스코드.

CrewAI 순차 3-에이전트 파이프라인(회의록 작성 → 액션아이템·예약 추출 → 인용 검증)과
온디맨드 Q&A 에이전트로 구성된다. 생성이든 응답이든 모든 문장에 근거 발화 ID [U##] 인용을
강제하고, audit_citations() 로 인용 실재성을 코드로 검증한다.

실행:
    (.env 에 OPENAI_API_KEY 설정 후)
    python meeting_agent.py
"""

import asyncio
import os
import re
import warnings
from pathlib import Path

from dotenv import load_dotenv

from crewai import Agent, Crew, LLM, Process, Task

warnings.filterwarnings("ignore")


# --------------------------------------------------------------- .env + LLM
def find_env_file(start: Path):
    """스크립트 폴더 또는 상위 폴더에서 .env 를 탐색한다. (없으면 None 반환)"""
    for folder in [start, *start.parents]:
        candidate = folder / ".env"
        if candidate.exists():
            return candidate
    return None


env_path = find_env_file(Path(__file__).resolve().parent)
if env_path is None:
    raise FileNotFoundError(
        ".env 파일을 찾을 수 없습니다. 스크립트와 같은(또는 상위) 폴더에 .env 를 만들고 "
        "OPENAI_API_KEY=... 형식으로 API 키를 저장하세요."
    )
load_dotenv(dotenv_path=env_path, override=False)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(".env 에 OPENAI_API_KEY 가 설정되어 있지 않습니다.")

# litellm 형식 모델명. 폐쇄망 배포 시에는 base_url 과 model 만 사내 엔드포인트로 바꾼다.
model_name = os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")
if not model_name.startswith("openai/"):
    model_name = f"openai/{model_name}"

llm = LLM(
    model=model_name,
    api_key=api_key,
    temperature=0.0,   # 인용 정확도·사실 보존이 최우선 → 결정론적으로
)

# 운영 모드: 회의 원문(민감 정보)이 콘솔/로그로 새지 않도록 verbose 를 기본 off 로 둔다.
# CrewAI 의 verbose 는 발화록 전문·프롬프트를 그대로 출력하므로, 보안 규제 조직 배포 시
# 이 자체가 데이터 유출 경로가 된다. 데모에서 에이전트 사고 과정을 보려면 .env 에
# AGENT_VERBOSE=1 로 켠다.
VERBOSE = os.getenv("AGENT_VERBOSE", "0") == "1"


# --------------------------------------------------------------- 입력 발화록
# 실제 서비스에서는 STT(Whisper)+화자 분리(pyannote) 결과가 입력이다.
# 발화마다 [U##] 발화 ID · 시각 · 화자가 붙어 있어 인용([U##])이 원문으로 역추적된다.
SAMPLE_TRANSCRIPT = """
[U01] (10:00) 이체계팀장: ○○유도무기 구성품 3차 진도점검 회의를 시작합니다. 참석은 저, 품질보증 박책임, 구매 김선임, 시험평가 최선임입니다.
[U02] (10:03) 김선임: 협력업체 A사의 탐색기 조립체 납품이 형상 변경으로 2주 지연됩니다. 당초 납기는 이달 20일이었습니다.
[U03] (10:05) 박책임: 지연되면 시험평가 일정 전체가 밀립니다. 재고 조립체를 먼저 투입하는 방안을 검토해야 합니다.
[U04] (10:08) 최선임: 환경시험은 다음 달 5일 국방과학연구소 시험장에서 진행하도록 조율돼 있어 변경이 어렵습니다.
[U05] (10:11) 이체계팀장: 그러면 A사 지연분은 재고 조립체로 대체하고, 정품은 2차 로트에 반영하겠습니다.
[U06] (10:13) 김선임: A사와 형상 변경분을 반영한 개당 단가 재협상이 필요합니다. 다음 주 수요일까지 재산정해 보고하겠습니다.
[U07] (10:16) 박책임: 재고 조립체 투입 전 품질 이력 확인이 필수입니다. 모레까지 해당 로트 검사성적서를 확인하겠습니다.
[U08] (10:19) 최선임: 환경시험 절차서 최신본을 시험 3일 전까지 배포해야 합니다. 초안은 이번 주 금요일까지 올리겠습니다.
[U09] (10:22) 이체계팀장: 납기·단가·시험 일정은 대외 유출 금지 사항입니다. 회의록이 외부로 나가면 안 됩니다.
[U10] (10:24) 이체계팀장: 다음 통합회의는 시험 준비 점검으로 다음 주 목요일 오후 2시, 본관 3층 보안회의실에서 진행합니다.
[U11] (10:25) 김선임: 보안회의실 예약은 제가 등록해 두겠습니다.
[U12] (10:27) 이체계팀장: 오늘 회의는 여기까지 하겠습니다.
"""


# --------------------------------------------------------------- 에이전트 (Role Prompt)
# ① 회의록 작성자 — practice_2 의 planner+writer 대응
minutes_writer = Agent(
    role="회의록 작성 전문가",
    goal=(
        "주어진 회의 발화록에서 주제·일시·참석자·핵심 논의·결정사항을 구조화하여 "
        "회의록을 작성한다. 모든 요약 문장 끝에는 근거가 된 발화 ID 를 [U##] 형식으로 "
        "반드시 붙인다."
    ),
    backstory=(
        "당신은 발화의 표현이 아니라 사실만 옮기는 원칙을 지닌 서기입니다. "
        "발화록에 없는 내용은 절대 지어내지 않으며, 근거로 지목할 발화가 없는 문장은 "
        "아예 쓰지 않습니다. 모든 결과물은 한국어로 작성합니다."
    ),
    llm=llm,
    allow_delegation=False,
    verbose=VERBOSE,
)

# ② 액션아이템·예약 추출자 — 회의 자동화 도메인 특화
action_booking = Agent(
    role="후속 조치 관리자",
    goal=(
        "발화록에서 액션아이템(담당자·할 일·기한)과 회의실/후속회의 예약 필요사항을 "
        "빠짐없이 추출해 승인 대기용 초안으로 만든다. 각 항목에도 근거 발화 ID [U##] 를 붙인다."
    ),
    backstory=(
        "당신은 회의에서 흘러가버리는 '누가·언제·무엇을'을 놓치지 않고 잡아내는 담당자입니다. "
        "예약은 사람이 승인만 하면 되도록 날짜·시간·장소를 명시한 초안 형태로 정리합니다. "
        "발화에 근거가 없는 항목은 만들지 않습니다. 모든 결과물은 한국어로 작성합니다."
    ),
    llm=llm,
    allow_delegation=False,
    verbose=VERBOSE,
)

# ③ 인용 검증 편집자 — practice_2 의 editor 대응 + 핵심 차별점(근거 인용 강제)
citation_verifier = Agent(
    role="인용 검증 편집자",
    goal=(
        "앞 단계 산출물의 모든 [U##] 인용이 실제 발화록에 존재하는 발화 ID 인지 대조하고, "
        "근거가 없거나 잘못된 인용이 붙은 문장은 삭제한 뒤, 최종 회의록만 출력한다."
    ),
    backstory=(
        "당신은 '근거가 붙어 있으면 리뷰어는 믿는다. 그러므로 틀린 근거는 근거가 없는 것보다 "
        "나쁘다'는 원칙을 지닌 편집자입니다. 검토 설명이나 편집 후기는 쓰지 말고 다듬어진 "
        "최종 회의록만 출력합니다. 모든 결과물은 한국어로 작성합니다."
    ),
    llm=llm,
    allow_delegation=False,
    verbose=VERBOSE,
)

# ④ 회의 지식 응답자 — 발화록을 근거로 질문에 답하는 온디맨드 에이전트
qa_agent = Agent(
    role="회의 지식 응답자",
    goal=(
        "주어진 회의 발화록만을 근거로 사용자의 질문에 답한다. 답변의 각 문장 끝에는 "
        "근거가 된 발화 ID 를 [U##] 형식으로 반드시 붙인다."
    ),
    backstory=(
        "당신은 발화록에 있는 내용만 답하고, 근거가 없으면 '해당 내용은 이번 회의에서 "
        "확인되지 않습니다.' 라고 답하는 원칙을 지닌 응답자입니다. 절대 추측하거나 "
        "지어내지 않습니다. 모든 답변은 한국어로 작성합니다."
    ),
    llm=llm,
    allow_delegation=False,
    verbose=VERBOSE,
)


# --------------------------------------------------------------- Task (생성 파이프라인)
# Task 1 — 회의록 작성 (Few-shot 으로 인용 형식을 고정)
task_minutes = Task(
    description=(
        "다음 회의 발화록을 읽고 회의록을 작성하세요.\n\n"
        "회의 발화록:\n{transcript}\n\n"
        "요구사항:\n"
        "1. '주제 / 일시 / 참석자 / 핵심 논의 / 결정사항' 순서의 마크다운으로 작성합니다.\n"
        "2. 핵심 논의와 결정사항의 모든 문장 끝에는 근거 발화 ID 를 [U##] 형식으로 붙입니다.\n"
        "   예) - 탐색기 조립체 납기가 형상 변경으로 2주 지연된다. [U02]\n"
        "   예) - 지연분은 재고 조립체로 대체하고 정품은 2차 로트에 반영한다. [U05]\n"
        "3. 발화록에 근거가 없는 내용은 절대 추가하지 않습니다."
    ),
    expected_output=(
        "주제·일시·참석자·핵심 논의·결정사항을 담고, 모든 요약 문장에 [U##] 인용이 붙은 "
        "한국어 마크다운 회의록"
    ),
    agent=minutes_writer,
)

# Task 2 — 액션아이템 + 예약 초안 (앞 회의록을 context 로 사용)
task_actions = Task(
    description=(
        "회의 발화록과 앞 단계 회의록을 바탕으로 후속 조치를 정리하세요.\n\n"
        "회의 발화록:\n{transcript}\n\n"
        "요구사항:\n"
        "1. '## 액션아이템' 표: 담당자 | 할 일 | 기한 | 근거([U##]).\n"
        "2. '## 회의실/후속회의 예약 초안' 표: 일시 | 장소 | 목적 | 근거([U##]).\n"
        "   사람이 승인만 하면 되도록 날짜·시간·장소를 명시합니다.\n"
        "3. 발화에 근거가 없는 항목은 만들지 않습니다."
    ),
    expected_output=(
        "담당자·기한이 명시된 액션아이템 표와 일시·장소가 명시된 예약 초안 표. "
        "각 행에 [U##] 근거 포함."
    ),
    agent=action_booking,
    context=[task_minutes],
)

# Task 3 — 인용 검증 후 최종 회의록 (앞 두 산출물을 context 로 사용)
task_verify = Task(
    description=(
        "앞 단계의 회의록과 후속 조치 초안을 하나의 최종 회의록으로 합치되, "
        "모든 [U##] 인용을 아래 발화록과 대조해 검증하세요.\n\n"
        "회의 발화록:\n{transcript}\n\n"
        "요구사항:\n"
        "1. 발화록에 존재하지 않는 발화 ID 를 인용한 문장은 삭제합니다.\n"
        "2. 인용이 아예 없는 요약 문장도 삭제합니다(근거 없는 문장 금지).\n"
        "3. 회의록 → 액션아이템 → 예약 초안 순서의 최종 마크다운만 출력하고, "
        "   검토 설명은 쓰지 않습니다."
    ),
    expected_output=(
        "모든 문장이 발화록에 실재하는 [U##] 로 뒷받침되는, 검토 설명 없는 한국어 마크다운 최종 회의록"
    ),
    agent=citation_verifier,
    context=[task_minutes, task_actions],
)

# 생성 파이프라인 Crew (순차 실행)
crew = Crew(
    agents=[minutes_writer, action_booking, citation_verifier],
    tasks=[task_minutes, task_actions, task_verify],
    process=Process.sequential,
    verbose=VERBOSE,
)


# --------------------------------------------------------------- 근거 인용 검증
_UID = re.compile(r"\[(U\d{2})\]")
_SEP = re.compile(r"^\s*\|?[\s:|+-]+\|?\s*$")          # 표 구분선(|---|)
_CLAIM_BULLET = re.compile(r"^([-*]|\d+\.)\s+\S")       # 불릿/번호 목록


def _is_claim_line(s: str) -> bool:
    """근거가 붙어야 하는 '청구 문장'인지 판정한다. 헤딩·표 헤더·구분선은 제외."""
    if _CLAIM_BULLET.match(s):
        return True
    # 표의 데이터 행: | 가 2개 이상이고, 구분선/헤더행('근거' 컬럼명 포함)이 아님
    if s.startswith("|") and s.count("|") >= 2 and not _SEP.match(s) and "근거" not in s:
        return True
    return False


def audit_citations(transcript: str, output_text: str, enforce: bool = False) -> dict:
    """인용 검증. 두 가지를 본다.

    1) 인용 실재성 : 산출물의 [U##] 가 발화록에 실제로 존재하는가 (환각 인용 검출)
    2) 문장 근거율 : 근거가 붙어야 하는 청구 문장이 실제로 유효한 [U##] 를 갖는가
       (= "인용할 발화가 없는 문장은 출력되지 않는다"를 문장 단위로 확인)

    enforce=True 면 근거 없는 청구 문장을 제거한 텍스트를 함께 돌려준다.
    """
    valid_ids = set(_UID.findall(transcript))
    cited_ids = _UID.findall(output_text)
    hallucinated = sorted({c for c in cited_ids if c not in valid_ids})
    valid_cnt = sum(1 for c in cited_ids if c in valid_ids)

    claim_total = claim_grounded = 0
    kept_lines = []
    for line in output_text.splitlines():
        s = line.strip()
        if _is_claim_line(s):
            ids = _UID.findall(s)
            ok = bool(ids) and all(i in valid_ids for i in ids)
            claim_total += 1
            claim_grounded += int(ok)
            if enforce and not ok:
                continue          # 근거 없는 문장 제거 (강제)
        kept_lines.append(line)

    rate = (claim_grounded / claim_total * 100) if claim_total else 100.0
    passed = (not hallucinated) and (claim_grounded == claim_total)

    bar = "━" * 48
    print(bar)
    print("근거 인용 검증 (Citation Audit)")
    print(bar)
    print(f"  인용      : {len(cited_ids)}개  (유효 {valid_cnt} / 환각 {len(hallucinated)})")
    print(f"  청구 문장  : {claim_grounded}/{claim_total} 근거 보유  (통과율 {rate:.0f}%)")
    if hallucinated:
        print(f"  환각 인용  : {hallucinated}")
    print(f"  판정      : {'✅ 통과 (모든 문장이 발화로 역추적됨)' if passed else '⚠️  보완 필요 (근거 없는 문장 존재)'}")
    print(bar)

    return {
        "citations": len(cited_ids),
        "valid": valid_cnt,
        "hallucinated": hallucinated,
        "claim_total": claim_total,
        "claim_grounded": claim_grounded,
        "grounded_rate": rate,
        "passed": passed,
        "enforced_text": "\n".join(kept_lines) if enforce else None,
    }


# --------------------------------------------------------------- ④ Q&A (온디맨드)
async def ask_meeting(question: str, transcript: str = SAMPLE_TRANSCRIPT) -> str:
    """질문 1건에 대해 단일 에이전트 Crew 를 즉석에서 구성해 답변을 반환한다."""
    qa_task = Task(
        description=(
            "아래 회의 발화록을 근거로 사용자의 질문에 답하세요.\n\n"
            "회의 발화록:\n{transcript}\n\n"
            "질문: {question}\n\n"
            "규칙:\n"
            "1. 답변의 각 문장 끝에 근거가 된 발화 ID 를 [U##] 형식으로 붙입니다.\n"
            "2. 발화록에서 근거를 찾을 수 없으면 "
            "'해당 내용은 이번 회의에서 확인되지 않습니다.' 라고만 답합니다.\n"
            "3. 발화록에 없는 내용을 추측하거나 지어내지 않습니다."
        ),
        expected_output="근거 [U##] 인용이 붙은 간결한 한국어 답변, 또는 확인 불가 안내",
        agent=qa_agent,
    )
    qa_crew = Crew(
        agents=[qa_agent],
        tasks=[qa_task],
        process=Process.sequential,
        verbose=VERBOSE,
    )
    result = await qa_crew.kickoff_async(inputs={"question": question, "transcript": transcript})
    return result.raw


# --------------------------------------------------------------- 실행 진입점
async def main():
    # 1) 생성 파이프라인: 회의록 + 액션아이템/예약 초안 (API 사용량 발생)
    result = await crew.kickoff_async(inputs={"transcript": SAMPLE_TRANSCRIPT})
    final_text = result.raw
    print("\n================= 최종 회의록 =================\n")
    print(final_text)

    print("\n================= 인용 검증 =================\n")
    audit = audit_citations(SAMPLE_TRANSCRIPT, final_text)
    # 근거 없는 문장이 남아 있으면 '강제 제거' 결과를 보여준다 (인용 강제).
    if not audit["passed"]:
        print("\n[인용 강제] 근거 없는 문장을 제거한 회의록:\n")
        cleaned = audit_citations(SAMPLE_TRANSCRIPT, final_text, enforce=True)["enforced_text"]
        print(cleaned)

    # 2) Q&A: 근거가 있는 질문 → 인용과 함께 답변
    print("\n================= Q&A =================\n")
    q1 = "탐색기 조립체 납품이 왜 지연됐고, 대체 방안은 무엇으로 결정됐나요?"
    a1 = await ask_meeting(q1)
    print("Q1:", q1)
    print("A1:", a1)
    print("-" * 60)
    audit_citations(SAMPLE_TRANSCRIPT, a1)

    # 3) Q&A: 근거가 없는 질문 → 지어내지 않고 '확인 불가'
    q2 = "이번 회의에서 양산 물량은 몇 발로 확정됐나요?"
    a2 = await ask_meeting(q2)
    print("\nQ2:", q2)
    print("A2:", a2)


if __name__ == "__main__":
    asyncio.run(main())
