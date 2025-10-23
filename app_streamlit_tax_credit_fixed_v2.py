
# app_streamlit_tax_credit_fixed_v2.py
# 통합고용증대(인원 증가 기반) 간편 계산기 + 보조 챗(옵션)
# - load_dotenv 누락으로 인한 NameError 방지
# - "계산기" 탭이 기본값으로 표시되도록 구성
# - 법령/단가는 사용자 편집 가능(기본값은 예시이며, 반드시 최신 법령에 맞게 조정해 주세요)

import os
import math
import datetime as dt
import streamlit as st

# --- (안전) dotenv 로드: 설치/임포트가 없더라도 앱이 깨지지 않게 처리 ---
try:
    from dotenv import load_dotenv  # type: ignore
    try:
        load_dotenv()
    except Exception:
        pass
except Exception:
    # dotenv 미설치/미임포트여도 앱 동작에는 영향이 없도록 무시
    pass

# -------------------- 기본 설정 --------------------
st.set_page_config(
    page_title="통합고용증대 세액공제 계산기",
    page_icon="🧮",
    layout="centered"
)

# -------------------- 유틸리티 --------------------
@st.cache_data(show_spinner=False)
def fmt_money(n: float) -> str:
    try:
        return f"{int(round(n, 0)):,}"
    except Exception:
        return "0"


def compute_credit(
    prev_regular: int,
    curr_regular: int,
    youth_increase: int,
    per_head_youth: int,
    per_head_other: int,
    cap_amount: int | None = None,
) -> dict:
    """
    단순화된 계산 로직:
      - 총 증가인원 = max(0, 당해 - 직전)
      - 청년 증가분은 사용자가 지정(검증: 총 증가인원보다 크면 총 증가인원으로 보정)
      - 비청년 증가분 = 총 증가 - 청년 증가
      - 공제액 = (청년 증가 * 청년 단가) + (비청년 증가 * 비청년 단가)
      - cap_amount(상한) 제공 시, 공제액은 상한을 초과하지 않음
    """
    inc_total = max(0, curr_regular - prev_regular)
    youth = max(0, min(youth_increase, inc_total))
    other = max(0, inc_total - youth)

    credit = youth * per_head_youth + other * per_head_other
    if cap_amount is not None:
        credit = min(credit, cap_amount)

    return {
        "inc_total": inc_total,
        "youth": youth,
        "other": other,
        "credit": credit,
    }


# -------------------- 사이드바 --------------------
st.sidebar.header("환경 설정")
st.sidebar.info(
    "※ 본 계산기는 이해를 돕기 위한 단순화 도구입니다. "
    "실제 공제 요건/단가/상한은 최신 법령·해석에 따라 달라질 수 있으므로 반드시 검토하세요."
)

# 탭(계산기 우선)
tab_calc, tab_chat = st.tabs(["🧮 계산기", "💬 보조 챗(선택)"])

# -------------------- 계산기 탭 --------------------
with tab_calc:
    st.title("통합고용증대 세액공제 계산기")
    st.caption("필수 입력만으로 증가 인원과 공제액(단순)을 산출합니다. 단가는 사용자 지정이 가능합니다.")

    col0, col1 = st.columns(2)
    with col0:
        year = st.number_input("과세연도", min_value=2018, max_value=2100, value=dt.date.today().year, step=1, format="%d")
        prev_regular = st.number_input("직전연도 상시근로자수", min_value=0, step=1, value=100)
    with col1:
        curr_regular = st.number_input("당해연도 상시근로자수", min_value=0, step=1, value=110)
        youth_increase = st.number_input("증가 인원 중 '청년' 인원", min_value=0, step=1, value=5,
                                         help="총 증가인원보다 큰 값은 자동 보정됩니다.")

    st.markdown("---")
    st.subheader("공제 단가(사용자 지정)")
    preset = st.selectbox(
        "단가 프리셋(선택) — 값은 아래 칸에 자동 반영되며 수정 가능합니다.",
        (
            "사용자 지정(기본)",
            "예시: 중소·수도권 외 — 청년 12,000,000 / 비청년 10,000,000",
            "예시: 중소·수도권 — 청년 11,000,000 / 비청년 9,000,000",
            "예시: 중견/대기업 — 청년 8,000,000 / 비청년 6,000,000",
        ),
        index=0
    )

    # 기본값
    default_youth = 12_000_000
    default_other = 10_000_000

    if preset == "예시: 중소·수도권 — 청년 11,000,000 / 비청년 9,000,000":
        default_youth, default_other = 11_000_000, 9_000_000
    elif preset == "예시: 중소·수도권 외 — 청년 12,000,000 / 비청년 10,000,000":
        default_youth, default_other = 12_000_000, 10_000_000
    elif preset == "예시: 중견/대기업 — 청년 8,000,000 / 비청년 6,000,000":
        default_youth, default_other = 8_000_000, 6_000_000

    c1, c2, c3 = st.columns(3)
    with c1:
        per_head_youth = st.number_input("청년 1인당 공제단가(원)", min_value=0, step=100000, value=default_youth)
    with c2:
        per_head_other = st.number_input("비청년 1인당 공제단가(원)", min_value=0, step=100000, value=default_other)
    with c3:
        cap_use = st.checkbox("상한 적용", value=False)
        cap_amount = st.number_input("상한액(원)", min_value=0, step=1000000, value=0, disabled=not cap_use)
        cap_amount = cap_amount if cap_use else None

    # 계산
    result = compute_credit(
        prev_regular=prev_regular,
        curr_regular=curr_regular,
        youth_increase=youth_increase,
        per_head_youth=per_head_youth,
        per_head_other=per_head_other,
        cap_amount=cap_amount,
    )

    st.markdown("### 결과")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("총 증가 인원", f"{result['inc_total']:,} 명")
    r2.metric("청년 증가", f"{result['youth']:,} 명")
    r3.metric("비청년 증가", f"{result['other']:,} 명")
    r4.metric("예상 공제액(단순)", f"{fmt_money(result['credit'])} 원")

    with st.expander("상세내역 보기", expanded=True):
        st.write(
            f"""
- 직전연도 상시근로자수: **{prev_regular:,} 명**
- 당해연도 상시근로자수: **{curr_regular:,} 명**
- 총 증가 인원: **{result['inc_total']:,} 명**
- 청년 증가 인원 × 단가: **{result['youth']:,} × {fmt_money(per_head_youth)} = {fmt_money(result['youth']*per_head_youth)} 원**
- 비청년 증가 인원 × 단가: **{result['other']:,} × {fmt_money(per_head_other)} = {fmt_money(result['other']*per_head_other)} 원**
- 상한 적용: **{'예' if cap_amount is not None else '아니오'}**
- 최종 공제액(단순): **{fmt_money(result['credit'])} 원**
"""
        )

    st.markdown("---")
    st.caption("※ 실제 적용요건(청년의 범위, 상시근로자 산정방식, 제외인원, 중복 배제 등)에 따라 결과가 달라질 수 있습니다. 최신 법령을 확인해 주세요.")

# -------------------- 보조 챗 탭 --------------------
with tab_chat:
    st.subheader("보조 챗(간단 회계 메모/계산 참고)")
    st.caption("외부 API를 사용하지 않는 로컬 에코 챗입니다. 민감정보를 입력하지 마세요.")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for role, msg in st.session_state.chat_history:
        with st.chat_message(role):
            st.markdown(msg)

    user_msg = st.chat_input("메시지를 입력하세요 (간단 회계 메모/계산 질문 등)")
    if user_msg:
        st.session_state.chat_history.append(("user", user_msg))
        # 간단한 도움말/키워드 응답 (룰베이스)
        reply = "기록해 두었습니다. 계산은 '🧮 계산기' 탭에서 입력값을 조정해 보세요."
        keywords = {
            "증가": "증가 인원 = 당해연도 상시근로자수 - 직전연도 상시근로자수(0 미만이면 0으로 처리) 입니다.",
            "청년": "청년 인원은 총 증가 인원 이내에서 직접 지정하도록 되어 있습니다.",
            "단가": "공제 단가는 프리셋 또는 사용자 지정으로 입력할 수 있습니다."
        }
        for k, v in keywords.items():
            if k in user_msg:
                reply = v
                break
        st.session_state.chat_history.append(("assistant", reply))
        with st.chat_message("assistant"):
            st.markdown(reply)
