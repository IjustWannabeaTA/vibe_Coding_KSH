import hashlib
import json
from io import BytesIO

from openai import OpenAI
import streamlit as st
from pypdf import PdfReader
from supabase import create_client


st.set_page_config(page_title="AI 학습 정리 노트", page_icon="📘", layout="wide")

st.title("AI 학습 정리 노트")
st.caption("PDF 문서를 업로드하고 페이지별 원문과 AI 요약을 확인하세요.")

st.session_state.setdefault("summary_document_id", None)
st.session_state.setdefault("summary_result", None)
st.session_state.setdefault("summary_saved_id", None)
st.session_state.setdefault("quiz_result", None)
st.session_state.setdefault("quiz_revision", 0)

QUIZ_SYSTEM_PROMPT = """당신은 학습 퀴즈를 만드는 도우미입니다.
주어진 요약을 바탕으로 4지선다 퀴즈 3문항을 만드세요.
각 문항은 question, options(4개), answer(정답 인덱스, 0부터 시작), explanation을 포함해야 합니다.
결과는 {"questions": [...]} 형태의 JSON으로 반환하세요.
"""


@st.cache_resource
def get_supabase_client():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


def format_saved_at(created_at):
    if not created_at:
        return "저장 시각을 확인할 수 없습니다."
    return str(created_at).replace("T", " ").replace("Z", "")


def get_summary_preview(summary):
    if not isinstance(summary, dict):
        return "요약 내용이 없습니다."
    preview = str(summary.get("핵심 요약", "요약 내용이 없습니다.")).strip()
    return f"{preview[:140]}..." if len(preview) > 140 else preview

with st.sidebar:
    st.header("문서 업로드")
    uploaded_file = st.file_uploader(
        "PDF 파일 업로드",
        type=["pdf"],
        accept_multiple_files=False,
    )

reader = None
page_count = None
page_texts = []
load_error = None

if uploaded_file is not None:
    uploaded_bytes = uploaded_file.getvalue()
    document_id = hashlib.sha256(uploaded_bytes).hexdigest()
    if st.session_state.summary_document_id != document_id:
        st.session_state.summary_document_id = document_id
        st.session_state.summary_result = None
        st.session_state.summary_saved_id = None
        st.session_state.quiz_result = None

    try:
        reader = PdfReader(BytesIO(uploaded_bytes))
        page_count = len(reader.pages)
        page_texts = [
            page.extract_text() or "(이 페이지에서는 추출된 텍스트가 없습니다.)"
            for page in reader.pages
        ]
    except Exception as error:
        load_error = error
else:
    st.session_state.summary_document_id = None
    st.session_state.summary_result = None
    st.session_state.summary_saved_id = None
    st.session_state.quiz_result = None

with st.sidebar:
    st.divider()
    st.subheader("문서 정보")
    if uploaded_file is None:
        st.caption("업로드된 문서가 없습니다.")
    else:
        st.caption("파일명")
        st.write(uploaded_file.name)
        if page_count is not None:
            st.metric("총 페이지 수", page_count)

original_tab, summary_tab, quiz_tab, history_tab = st.tabs(
    ["원문", "요약", "퀴즈", "저장 기록"]
)
with original_tab:
    if load_error is not None:
        st.error(f"PDF를 읽는 중 문제가 발생했습니다: {load_error}")
    elif reader is None:
        st.info("사이드바에서 PDF 파일을 업로드하면 페이지별 원문이 표시됩니다.")
    else:
        st.subheader("페이지별 텍스트")
        for page_number, page_text in enumerate(page_texts, start=1):
            with st.expander(f"{page_number}페이지", expanded=page_number == 1):
                st.text_area(
                    f"{page_number}페이지 텍스트",
                    value=page_text,
                    height=240,
                    label_visibility="collapsed",
                    key=f"page_text_{page_number}",
                )

with summary_tab:
    if load_error is not None:
        st.error(f"PDF를 읽는 중 문제가 발생했습니다: {load_error}")
    elif reader is None:
        st.info("사이드바에서 PDF 파일을 업로드하면 AI 요약을 생성할 수 있습니다.")
    else:
        st.subheader("AI 요약")
        if st.button("요약하기", type="primary"):
            try:
                api_key = st.secrets["OPENAI_API_KEY"]
                client = OpenAI(api_key=api_key)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "PDF 텍스트를 분석해 다음 형식의 유효한 JSON 객체만 반환하세요. "
                                '"핵심 요약"은 정확히 3문장, "주요 키워드"는 정확히 5개인 배열, '
                                '"난이도"는 반드시 "상", "중", "하" 중 하나여야 합니다. '
                                'JSON 형식: {"핵심 요약": "3문장", '
                                '"주요 키워드": ["키워드1", "키워드2", "키워드3", '
                                '"키워드4", "키워드5"], "난이도": "상|중|하"}'
                            ),
                        },
                        {
                            "role": "user",
                            "content": "\n\n".join(
                                f"[{page_number}페이지]\n{page_text}"
                                for page_number, page_text in enumerate(page_texts, start=1)
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                response_content = response.choices[0].message.content or "{}"
                st.session_state.summary_result = json.loads(response_content)
                st.session_state.summary_saved_id = None
                st.session_state.quiz_result = None
                st.session_state.quiz_revision += 1
            except KeyError:
                st.error("Streamlit secrets에 OPENAI_API_KEY가 설정되지 않았습니다.")
            except json.JSONDecodeError:
                st.error("OpenAI 응답을 JSON으로 해석하지 못했습니다.")
            except Exception as error:
                st.error(f"요약을 생성하는 중 문제가 발생했습니다: {error}")

        summary_result = st.session_state.get("summary_result")
        if summary_result:
            st.markdown("#### 핵심 요약")
            st.write(summary_result.get("핵심 요약", "요약 결과가 없습니다."))

            st.markdown("#### 주요 키워드")
            keywords = summary_result.get("주요 키워드", [])
            if isinstance(keywords, list):
                for keyword in keywords:
                    st.markdown(f"- {keyword}")
            else:
                st.write(keywords)

            st.markdown("#### 난이도")
            st.write(summary_result.get("난이도", "난이도 정보가 없습니다."))

            if st.button("저장"):
                try:
                    insert_response = get_supabase_client().table("summaries").insert(
                        {
                            "filename": uploaded_file.name,
                            "summary": summary_result,
                            "quiz": None,
                        }
                    ).execute()
                    if not insert_response.data:
                        raise RuntimeError("저장된 요약의 ID를 확인할 수 없습니다.")
                    st.session_state.summary_saved_id = insert_response.data[0]["id"]
                    st.session_state.quiz_result = None
                    st.success("요약 결과를 저장했습니다.")
                except KeyError:
                    st.error("Streamlit secrets에 SUPABASE_URL 또는 SUPABASE_KEY가 설정되지 않았습니다.")
                except Exception as error:
                    st.error(f"요약 결과를 저장하는 중 문제가 발생했습니다: {error}")

with quiz_tab:
    st.subheader("학습 퀴즈")
    summary_result = st.session_state.get("summary_result")
    saved_summary_id = st.session_state.get("summary_saved_id")

    if not summary_result:
        st.info("먼저 요약을 생성해주세요.")
    elif not saved_summary_id:
        st.info("퀴즈를 만들려면 먼저 요약을 저장해주세요.")
    else:
        if st.button("퀴즈 생성하기", type="primary"):
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(summary_result, ensure_ascii=False),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                response_content = response.choices[0].message.content or "{}"
                quiz_result = json.loads(response_content)
                get_supabase_client().table("summaries").update(
                    {"quiz": quiz_result}
                ).eq("id", saved_summary_id).execute()
                st.session_state.quiz_result = quiz_result
                st.session_state.quiz_revision += 1
                st.success("퀴즈를 생성하고 저장된 요약에 반영했습니다.")
            except KeyError:
                st.error("Streamlit secrets에 OPENAI_API_KEY가 설정되지 않았습니다.")
            except json.JSONDecodeError:
                st.error("OpenAI 응답을 JSON으로 해석하지 못했습니다.")
            except Exception as error:
                st.error(f"퀴즈를 생성하는 중 문제가 발생했습니다: {error}")

        quiz_result = st.session_state.get("quiz_result")
        if quiz_result:
            questions = quiz_result.get("questions", [])
            for question_number, question in enumerate(questions, start=1):
                st.markdown(f"#### {question_number}. {question.get('question', '문제')}")
                options = question.get("options", [])
                answer_index = question.get("answer")
                if not isinstance(options, list) or len(options) != 4:
                    st.warning("보기 4개가 포함된 문제만 표시할 수 있습니다.")
                    continue

                selected_option = st.radio(
                    "보기 선택",
                    options,
                    index=None,
                    key=f"quiz_{st.session_state.quiz_revision}_{question_number}",
                )
                if selected_option is not None:
                    selected_index = options.index(selected_option)
                    if selected_index == answer_index:
                        st.success("정답입니다.")
                    else:
                        st.error(f"오답입니다. 정답은 {options[answer_index]}입니다.")
                    st.info(f"해설: {question.get('explanation', '해설이 없습니다.')}")

with history_tab:
    st.subheader("저장 기록")
    try:
        saved_summaries = (
            get_supabase_client()
            .table("summaries")
            .select("id, filename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
            .data
        )
        if not saved_summaries:
            st.info("저장된 요약 기록이 없습니다.")
        else:
            for saved_summary in saved_summaries:
                info_column, delete_column = st.columns([6, 1])
                with info_column:
                    st.markdown(f"**{saved_summary.get('filename', '이름 없는 파일')}**")
                    st.caption(format_saved_at(saved_summary.get("created_at")))
                    st.write(get_summary_preview(saved_summary.get("summary")))
                with delete_column:
                    if st.button("삭제", key=f"delete_summary_{saved_summary['id']}"):
                        try:
                            get_supabase_client().table("summaries").delete().eq(
                                "id", saved_summary["id"]
                            ).execute()
                            if saved_summary["id"] == st.session_state.summary_saved_id:
                                st.session_state.summary_saved_id = None
                                st.session_state.quiz_result = None
                            st.rerun()
                        except Exception as error:
                            st.error(f"저장 기록을 삭제하는 중 문제가 발생했습니다: {error}")
    except KeyError:
        st.error("Streamlit secrets에 SUPABASE_URL 또는 SUPABASE_KEY가 설정되지 않았습니다.")
    except Exception as error:
        st.error(f"저장 기록을 불러오는 중 문제가 발생했습니다: {error}")
