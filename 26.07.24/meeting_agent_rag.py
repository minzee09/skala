"""회의 자동화 Agent — 전체 시스템 (생성 파이프라인 + 벡터 DB 기반 RAG 질의응답).

두 흐름을 한 파일에 합친다.

  [1] 생성 파이프라인 (최신 회의 1건 대상, 순차 3-에이전트)
      최신 발화록 ─▶ ① 회의록 작성자 ─▶ ② 액션아이템·예약 추출자
                   ─▶ ③ 인용 검증 편집자 ─▶ 최종 회의록

  [2] RAG 질의응답 (과거 회의 전체 대상, 온디맨드)
      질문 ─▶ [임베딩·검색] Chroma 에서 관련 발화 top-k ─▶ ④ 회의 지식 응답자
           ─▶ 근거 [M#-U##] 인용이 붙은 답변

생성이든 응답이든 모든 문장에 근거 발화 ID [M#-U##] 인용을 강제하고,
audit_citations() 로 인용 실재성을 코드로 검증한다.

폐쇄망 배포 시 바꾸는 것은 두 곳뿐이다.
  - 생성 LLM   : LLM(model=..., base_url=사내 엔드포인트)
  - 임베딩 모델 : OpenAIEmbeddingFunction(api_base=사내 임베딩 엔드포인트)

실행:
    (.env 에 OPENAI_API_KEY 설정 후)
    python meeting_agent_rag.py
"""

import asyncio
import os
import re
import warnings
from pathlib import Path

# CrewAI 첫 실행 시 뜨는 트레이싱 안내 배너를 끈다 (발표 출력 정리용).
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from dotenv import load_dotenv

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from crewai import Agent, Crew, LLM, Process, Task

warnings.filterwarnings("ignore")


# --------------------------------------------------------------- .env + LLM
def find_env_file(start: Path):
    for folder in [start, *start.parents]:
        candidate = folder / ".env"
        if candidate.exists():
            return candidate
    return None


env_path = find_env_file(Path(__file__).resolve().parent)
if env_path is None:
    raise FileNotFoundError(".env 파일을 찾을 수 없습니다. OPENAI_API_KEY 를 설정하세요.")
load_dotenv(dotenv_path=env_path, override=False)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(".env 에 OPENAI_API_KEY 가 설정되어 있지 않습니다.")

model_name = os.getenv("OPENAI_MODEL_NAME", "openai/gpt-4o-mini")
if not model_name.startswith("openai/"):
    model_name = f"openai/{model_name}"

EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("RAG_TOP_K", "6"))
VERBOSE = os.getenv("AGENT_VERBOSE", "0") == "1"

llm = LLM(model=model_name, api_key=api_key, temperature=0.0)


# --------------------------------------------------------------- 과거 회의록 코퍼스
# 같은 사업이 회의를 거치며 진행되므로, RAG 는 '지난 회의들'을 가로질러 검색한다.
# 발화 ID 는 회의 구분을 위해 [M#-U##] 형식을 쓴다. (가상 샘플 데이터)
MEETINGS = {
    "M1": {
        "title": "1차 진도점검",
        "date": "2026-06-12(금)",
        "transcript": """
[M1-U01] (14:00) 이체계팀장: ○○ 유도무기 체계 탐색기 조립체, 도번 SA-7100 개발 1차 진도점검을 시작합니다. 참석은 체계개발 이체계팀장, 구매 김선임, 품질보증 박책임, 시험평가 최선임, 설계 정연구원 다섯 명입니다.
[M1-U02] (14:05) 정연구원: SA-7100 상세설계는 지난주 상세설계검토(CDR)를 통과했고, 현재 생산 도면 배포가 완료된 상태입니다.
[M1-U03] (14:09) 김선임: 협력업체 한빛정밀과 탐색기 조립체(SA-7100) 초도 물량 12조립체 계약을 체결했고, 탐색기 조립체 최초 납기는 2026년 7월 20일입니다.
[M1-U04] (14:14) 최선임: 환경시험은 고온·저온·진동 3개 항목이며, 3분기 중 국방과학연구소 창원 시험장에서 진행합니다. 시험 슬롯은 8월 첫째 주로 가배정 받았습니다.
[M1-U05] (14:19) 박책임: 현재까지 형상 변경 이슈는 없습니다. 입고 검사 기준서 개정판을 이번 주 내로 배포하겠습니다.
[M1-U06] (14:24) 이체계팀장: 좋습니다. 다음 진도점검은 4주 뒤에 잡고, 그때 시제 조립체 입고 준비 상태를 점검하겠습니다.
""",
    },
    "M2": {
        "title": "2차 진도점검",
        "date": "2026-07-10(금)",
        "transcript": """
[M2-U01] (10:00) 이체계팀장: SA-7100 조립체 2차 진도점검을 시작합니다. 오늘 핵심 안건은 형상 변경 요구 접수 건입니다.
[M2-U02] (10:05) 정연구원: 탐색기 렌즈 마운트 공차 문제로 설계변경요구 ECR-2026-0142 가 접수됐습니다. 형상 변경이 불가피합니다.
[M2-U03] (10:10) 김선임: 한빛정밀에 탐색기 조립체 형상 변경 반영을 요청했고, 재작업 때문에 탐색기 조립체 최초 납기 7월 20일에서 최대 2주 지연될 수 있다는 회신을 받았습니다.
[M2-U04] (10:15) 박책임: 형상 변경 시 렌즈 마운트 재검증이 필요합니다. 재검증을 거치지 않은 조립체를 시험에 투입하면 안 됩니다.
[M2-U05] (10:20) 최선임: 8월 첫째 주 국방과학연구소 시험 슬롯은 재배정이 어렵습니다. 조립체 확보가 늦어지면 이번 분기 시험 슬롯을 놓칩니다.
[M2-U06] (10:26) 이체계팀장: 그러면 대안으로 사내 재고 조립체 투입 가능성을 다음 회의까지 검토합시다. 김선임은 단가 영향, 박책임은 재고 품질 이력을 확인해 주세요.
""",
    },
    "M3": {
        "title": "3차 진도점검",
        "date": "2026-07-24(금)",
        "transcript": """
[M3-U01] (10:00) 이체계팀장: SA-7100 조립체 3차 진도점검을 시작합니다. 지난 회의 숙제였던 재고 조립체 투입안을 오늘 결정하겠습니다.
[M3-U02] (10:04) 김선임: 한빛정밀 정품 탐색기 조립체는 형상 변경 ECR-2026-0142 반영으로 납품이 2주 지연되어, 당초 7월 20일 납기가 8월 3일로 확정 연기됐습니다.
[M3-U03] (10:08) 박책임: 사내 재고 조립체 3조립체의 검사성적서를 확인했습니다. 품질 이력상 환경시험 투입에 문제가 없습니다.
[M3-U04] (10:12) 이체계팀장: 결정합니다. 8월 첫째 주 환경시험은 재고 조립체 3조립체로 진행하고, 정품 지연분은 2차 로트에 반영합니다.
[M3-U05] (10:16) 김선임: 정품은 형상 변경분을 반영해 개당 단가 재협상이 필요합니다. 7월 29일 수요일까지 재산정해 보고하겠습니다.
[M3-U06] (10:20) 최선임: 환경시험 절차서 최신본을 시험 3일 전까지 배포해야 합니다. 초안은 7월 27일 월요일까지 올리겠습니다.
[M3-U07] (10:24) 이체계팀장: 납기·단가·시험 일정은 대외 유출 금지 사항입니다. 회의록이 조직 외부로 나가면 안 됩니다.
[M3-U08] (10:26) 이체계팀장: 다음 통합회의는 시험 준비 점검으로 7월 30일 목요일 오후 2시, 본관 3층 보안회의실에서 진행합니다. 회의실 예약은 김선임이 등록해 주세요.
""",
    },
}

LATEST = "M3"  # 생성 파이프라인이 회의록을 만들 대상(오늘 회의)

_LINE = re.compile(r"^\[(M\d+-U\d{2})\]\s*\(([^)]+)\)\s*([^:]+):\s*(.+)$")


def parse_corpus():
    """모든 회의 발화록을 발화 단위 청크로 분해한다."""
    chunks = []
    for mid, m in MEETINGS.items():
        for line in m["transcript"].strip().splitlines():
            match = _LINE.match(line.strip())
            if not match:
                continue
            uid, time, speaker, content = match.groups()
            chunks.append({
                "uid": uid, "time": time.strip(), "speaker": speaker.strip(),
                "content": content.strip(), "meeting": mid,
                "title": m["title"], "date": m["date"],
            })
    return chunks


CHUNKS = parse_corpus()
CORPUS_IDS = {c["uid"] for c in CHUNKS}


def meeting_ids(mid: str) -> set:
    return {c["uid"] for c in CHUNKS if c["meeting"] == mid}


# --------------------------------------------------------------- 벡터 DB (Chroma)
# 발화 '내용'만 임베딩하고 id·화자·시각은 메타데이터로 둔다. 온프레미스 전환 시
# api_base 만 사내 임베딩 엔드포인트로 바꾼다.
_embed_fn = embedding_functions.OpenAIEmbeddingFunction(api_key=api_key, model_name=EMBED_MODEL)
_client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
_collection = _client.get_or_create_collection(name="past_meetings", embedding_function=_embed_fn)
_collection.add(
    ids=[c["uid"] for c in CHUNKS],
    documents=[c["content"] for c in CHUNKS],
    metadatas=[{"time": c["time"], "speaker": c["speaker"], "meeting": c["meeting"],
                "title": c["title"], "date": c["date"]} for c in CHUNKS],
)


def retrieve(question: str, k: int = TOP_K):
    """질문과 의미가 가까운 발화 top-k 를 벡터 검색으로 회수한다."""
    res = _collection.query(query_texts=[question], n_results=k)
    return [{"uid": u, "content": d, **m}
            for u, d, m in zip(res["ids"][0], res["documents"][0], res["metadatas"][0])]


def format_context(hits) -> str:
    return "\n".join(
        f"[{h['uid']}] ({h['title']}, {h['date']}) {h['speaker']}: {h['content']}" for h in hits
    )


# --------------------------------------------------------------- [1] 생성 파이프라인 에이전트
minutes_writer = Agent(
    role="회의록 작성 전문가",
    goal=(
        "주어진 회의 발화록에서 주제·일시·참석자·핵심 논의·결정사항을 구조화하여 "
        "회의록을 작성한다. 모든 요약 문장 끝에는 근거가 된 발화 ID 를 [M#-U##] 형식으로 "
        "반드시 붙인다."
    ),
    backstory=(
        "당신은 발화의 표현이 아니라 사실만 옮기는 원칙을 지닌 서기입니다. 발화록에 없는 "
        "내용은 절대 지어내지 않으며, 근거로 지목할 발화가 없는 문장은 아예 쓰지 않습니다. "
        "모든 결과물은 한국어로 작성합니다."
    ),
    llm=llm, allow_delegation=False, verbose=VERBOSE,
)

action_booking = Agent(
    role="후속 조치 관리자",
    goal=(
        "발화록에서 액션아이템(담당자·할 일·기한)과 회의실/후속회의 예약 필요사항을 빠짐없이 "
        "추출해 승인 대기용 초안으로 만든다. 각 항목에도 근거 발화 ID [M#-U##] 를 붙인다."
    ),
    backstory=(
        "당신은 회의에서 흘러가버리는 '누가·언제·무엇을'을 놓치지 않고 잡아내는 담당자입니다. "
        "예약은 사람이 승인만 하면 되도록 날짜·시간·장소를 명시한 초안 형태로 정리합니다. "
        "발화에 근거가 없는 항목은 만들지 않습니다. 모든 결과물은 한국어로 작성합니다."
    ),
    llm=llm, allow_delegation=False, verbose=VERBOSE,
)

citation_verifier = Agent(
    role="인용 검증 편집자",
    goal=(
        "앞 단계 산출물의 모든 [M#-U##] 인용이 실제 발화록에 존재하는 발화 ID 인지 대조하고, "
        "근거가 없거나 잘못된 인용이 붙은 문장은 삭제한 뒤, 최종 회의록만 출력한다."
    ),
    backstory=(
        "당신은 '근거가 붙어 있으면 리뷰어는 믿는다. 그러므로 틀린 근거는 근거가 없는 것보다 "
        "나쁘다'는 원칙을 지닌 편집자입니다. 검토 설명이나 편집 후기는 쓰지 말고 다듬어진 최종 "
        "회의록만 출력합니다. 모든 결과물은 한국어로 작성합니다."
    ),
    llm=llm, allow_delegation=False, verbose=VERBOSE,
)

task_minutes = Task(
    description=(
        "다음 회의 발화록을 읽고 회의록을 작성하세요.\n\n"
        "회의 발화록:\n{transcript}\n\n"
        "요구사항:\n"
        "1. '주제 / 일시 / 참석자 / 핵심 논의 / 결정사항' 순서의 마크다운으로 작성합니다.\n"
        "2. 일시는 발화록 상단의 '[회의 일시]' 값을 그대로 사용합니다. 발화 앞의 (시각)은 "
        "발언 시각일 뿐 회의 날짜가 아니므로 날짜를 임의로 지어내지 않습니다.\n"
        "3. 핵심 논의와 결정사항의 모든 문장 끝에는 근거 발화 ID 를 [M#-U##] 형식으로 붙입니다.\n"
        "   예) - 정품 조립체 납품이 2주 지연되어 납기가 8월 3일로 연기됐다. [M3-U02]\n"
        "   예) - 8월 첫째 주 환경시험은 재고 조립체 3조립체로 진행한다. [M3-U04]\n"
        "4. 발화록에 근거가 없는 내용은 절대 추가하지 않습니다."
    ),
    expected_output=(
        "주제·일시·참석자·핵심 논의·결정사항을 담고, 모든 요약 문장에 [M#-U##] 인용이 붙은 "
        "한국어 마크다운 회의록"
    ),
    agent=minutes_writer,
)

task_actions = Task(
    description=(
        "회의 발화록과 앞 단계 회의록을 바탕으로 후속 조치를 정리하세요.\n\n"
        "회의 발화록:\n{transcript}\n\n"
        "요구사항:\n"
        "1. '## 액션아이템' 표: 담당자 | 할 일 | 기한 | 근거([M#-U##]).\n"
        "2. '## 회의실/후속회의 예약 초안' 표: 일시 | 장소 | 목적 | 근거([M#-U##]).\n"
        "   사람이 승인만 하면 되도록 날짜·시간·장소를 명시합니다.\n"
        "3. 발화에 근거가 없는 항목은 만들지 않습니다."
    ),
    expected_output=(
        "담당자·기한이 명시된 액션아이템 표와 일시·장소가 명시된 예약 초안 표. 각 행에 [M#-U##] 근거 포함."
    ),
    agent=action_booking, context=[task_minutes],
)

task_verify = Task(
    description=(
        "앞 단계의 회의록과 후속 조치 초안을 하나의 최종 회의록으로 합치되, 모든 [M#-U##] 인용을 "
        "아래 발화록과 대조해 검증하세요.\n\n"
        "회의 발화록:\n{transcript}\n\n"
        "요구사항:\n"
        "1. 발화록에 존재하지 않는 발화 ID 를 인용한 문장은 삭제합니다.\n"
        "2. 인용이 아예 없는 요약 문장도 삭제합니다(근거 없는 문장 금지).\n"
        "3. 회의록 → 액션아이템 → 예약 초안 순서의 최종 마크다운만 출력하고, 검토 설명은 쓰지 않습니다."
    ),
    expected_output="모든 문장이 발화록에 실재하는 [M#-U##] 로 뒷받침되는, 검토 설명 없는 한국어 마크다운 최종 회의록",
    agent=citation_verifier, context=[task_minutes, task_actions],
)

gen_crew = Crew(
    agents=[minutes_writer, action_booking, citation_verifier],
    tasks=[task_minutes, task_actions, task_verify],
    process=Process.sequential, verbose=VERBOSE,
)


async def generate_minutes(mid: str = LATEST) -> str:
    """최신 회의 1건의 발화록에서 최종 회의록을 생성한다."""
    m = MEETINGS[mid]
    # 회의명·일시는 발화 안에 없으므로 메타데이터를 상단에 붙여 넣는다(환각 방지).
    transcript = f"[회의명] {m['title']}\n[회의 일시] {m['date']}\n{m['transcript']}"
    result = await gen_crew.kickoff_async(inputs={"transcript": transcript})
    return result.raw


# --------------------------------------------------------------- [2] RAG Q&A 에이전트
qa_agent = Agent(
    role="회의 지식 응답자",
    goal=(
        "검색으로 제공된 과거 회의 발화만을 근거로 사용자의 질문에 답한다. 답변의 각 문장 "
        "끝에는 근거가 된 발화 ID 를 [M#-U##] 형식으로 반드시 붙인다."
    ),
    backstory=(
        "당신은 제공된 발화에 있는 내용만 답하고, 근거가 없으면 '해당 내용은 과거 회의 "
        "기록에서 확인되지 않습니다.' 라고 답하는 원칙을 지닌 응답자입니다. 제공되지 않은 "
        "발화 ID 를 지어내지 않습니다. 모든 답변은 한국어로 작성합니다."
    ),
    llm=llm, allow_delegation=False, verbose=VERBOSE,
)


async def ask_meeting_rag(question: str, k: int = TOP_K):
    """질문 → 벡터 검색 → 검색된 근거로만 생성. (retrieve-then-generate)"""
    hits = retrieve(question, k)
    qa_task = Task(
        description=(
            "아래는 질문과 의미가 가까워 검색된 과거 회의 발화들입니다. 이 발화들만을 근거로 "
            "질문에 답하세요.\n\n"
            "검색된 발화:\n{context}\n\n"
            "질문: {question}\n\n"
            "규칙:\n"
            "1. 답변의 각 문장 끝에 근거 발화 ID 를 [M#-U##] 형식으로 붙입니다.\n"
            "2. 여러 회의에 걸친 변화가 있으면 시간 순서대로 설명합니다.\n"
            "3. 위 발화들에서 근거를 찾을 수 없으면 "
            "'해당 내용은 과거 회의 기록에서 확인되지 않습니다.' 라고만 답합니다."
        ),
        expected_output="근거 [M#-U##] 인용이 붙은 간결한 한국어 답변, 또는 확인 불가 안내",
        agent=qa_agent,
    )
    qa_crew = Crew(agents=[qa_agent], tasks=[qa_task], process=Process.sequential, verbose=VERBOSE)
    result = await qa_crew.kickoff_async(inputs={"question": question, "context": format_context(hits)})
    return result.raw, hits


# --------------------------------------------------------------- 인용 검증 (생성·RAG 공용)
_UID = re.compile(r"\[(M\d+-U\d{2})\]")
_SEP = re.compile(r"^\s*\|?[\s:|+-]+\|?\s*$")
_CLAIM_BULLET = re.compile(r"^([-*]|\d+\.)\s+\S")


def _is_claim_line(s: str) -> bool:
    if _CLAIM_BULLET.match(s):
        return True
    if s.startswith("|") and s.count("|") >= 2 and not _SEP.match(s) and "근거" not in s:
        return True
    return False


def audit_citations(text, allowed_ids, corpus_ids=None, sentence_check=True):
    """인용 검증.

    allowed_ids  : 이번 답변이 인용해도 되는 ID 집합
                   (생성 = 해당 회의 발화 전체 / RAG = 이번에 검색된 발화)
    corpus_ids   : 전체 코퍼스 ID (환각 판별용). 없으면 allowed_ids 로 간주.
    sentence_check : 마크다운 청구 문장(불릿·표 행)이 유효한 인용을 갖는지 문장 단위 검사.
    """
    corpus_ids = corpus_ids or allowed_ids
    cited = _UID.findall(text)
    hallucinated = sorted({c for c in cited if c not in corpus_ids})
    out_of_scope = sorted({c for c in cited if c in corpus_ids and c not in allowed_ids})
    grounded = sum(1 for c in cited if c in allowed_ids)

    claim_total = claim_grounded = 0
    if sentence_check:
        for line in text.splitlines():
            s = line.strip()
            if _is_claim_line(s):
                ids = _UID.findall(s)
                claim_total += 1
                claim_grounded += int(bool(ids) and all(i in allowed_ids for i in ids))

    bar = "━" * 50
    print(bar)
    print("근거 인용 검증 (Citation Audit)")
    print(bar)
    print(f"  인용            : {len(cited)}개")
    print(f"  유효(범위 내)    : {grounded}/{len(cited)}")
    if sentence_check:
        rate = (claim_grounded / claim_total * 100) if claim_total else 100.0
        print(f"  청구 문장        : {claim_grounded}/{claim_total} 근거 보유 (통과율 {rate:.0f}%)")
    if hallucinated:
        print(f"  환각 인용        : {hallucinated} (코퍼스에 없는 발화)")
    if out_of_scope:
        print(f"  범위 밖 인용     : {out_of_scope} (제공/검색되지 않은 발화)")
    passed = (not hallucinated and not out_of_scope
              and (not sentence_check or claim_total == 0 or claim_grounded == claim_total)
              and (len(cited) == 0 or grounded == len(cited)))
    print(f"  판정            : {'✅ 통과' if passed else '⚠️  보완 필요'}")
    print(bar)
    return passed


# --------------------------------------------------------------- 실행 진입점
async def _demo_qa(question: str):
    answer, hits = await ask_meeting_rag(question)
    print(f"\nQ: {question}")
    print("검색된 근거(top-k):")
    for h in hits:
        print(f"  · [{h['uid']}] ({h['title']}, {h['date']}) {h['speaker']}: {h['content'][:44]}…")
    print(f"\nA: {answer}\n")
    audit_citations(answer, allowed_ids={h["uid"] for h in hits}, corpus_ids=CORPUS_IDS,
                    sentence_check=False)


async def main():
    print(f"코퍼스: {len(MEETINGS)}개 회의 / {len(CHUNKS)}개 발화 벡터 DB 인덱싱 완료\n")

    # [1] 생성 파이프라인 — 최신 회의(오늘) 회의록 자동 생성
    print("=" * 60)
    print(f"[1] 생성 파이프라인 — {MEETINGS[LATEST]['title']} ({MEETINGS[LATEST]['date']}) 회의록 생성")
    print("=" * 60)
    final = await generate_minutes(LATEST)
    print(final)
    print()
    audit_citations(final, allowed_ids=meeting_ids(LATEST), corpus_ids=CORPUS_IDS, sentence_check=True)

    # [2] RAG 질의응답 — 과거 회의 전체 대상
    print("\n" + "=" * 60)
    print("[2] RAG 질의응답 — 과거 회의 전체(M1~M3) 검색")
    print("=" * 60)
    await _demo_qa("탐색기 조립체 납기가 회의를 거치며 어떻게 바뀌어 왔나요?")
    print("-" * 60)
    await _demo_qa("환경시험은 어디서, 언제 진행하기로 했나요?")
    print("-" * 60)
    await _demo_qa("이번 사업의 총 양산 물량은 몇 발로 확정됐나요?")


if __name__ == "__main__":
    asyncio.run(main())
