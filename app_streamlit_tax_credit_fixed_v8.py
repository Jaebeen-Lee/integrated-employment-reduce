# -*- coding: utf-8 -*-
import streamlit as st
import os
try:
    from dotenv import load_dotenv
    try:
        load_dotenv()
    except Exception:
        pass
except Exception:
    pass

# ---------------------------------------------
# 시뮬레이션 렌더 함수 (요약이 있으면 항상 표/결과 표시)


def _render_simulation_pane(params, size, region, clawback_method):
    """요약(gross/applied/years)이 있으면 언제든 시뮬레이션 표/결과를 렌더링.
    - 표는 최초 1회만 현재 요약값(curr_total/curr_youth)으로 초기화
    - 사용자가 표를 편집해도 rerun에서 유지 (Enter 시 값이 되돌아가지 않음)
    - 필요 시 "표 기본값으로 초기화" 버튼으로만 재초기화
    """
    import pandas as _pd
    st.subheader("② 사후관리(추징) 시뮬레이션 - 다년표")

    if "summary" not in st.session_state:
        st.info("먼저 상단에서 **계산하기** 버튼을 눌러 계산 요약을 생성하세요.")
        return

    gross = int(st.session_state.summary["gross"])
    applied = int(st.session_state.summary["applied"])
    retention_years = int(st.session_state.summary["retention_years"])
    curr_total = int(st.session_state.summary["curr_total"])
    curr_youth = int(st.session_state.summary["curr_youth"])

    years = [1, 2, 3]

    init_key = (curr_total, curr_youth)
    if "sim_df" not in st.session_state or st.session_state.get("sim_df") is None:
        st.session_state.sim_df = _pd.DataFrame(
            [{"연차": yr, "사후연도 상시": curr_total, "사후연도 청년등": curr_youth} for yr in years]
        )
        st.session_state.sim_df_init_key = init_key

    reset = st.button("↩️ 표 기본값으로 초기화", key="btn_reset_sim", help="현재 요약의 당해 인원으로 표를 다시 채웁니다.")
    if reset or st.session_state.get("sim_df_init_key") != init_key:
        st.session_state.sim_df = _pd.DataFrame(
            [{"연차": yr, "사후연도 상시": curr_total, "사후연도 청년등": curr_youth} for yr in years]
        )
        st.session_state.sim_df_init_key = init_key

    edited = st.data_editor(st.session_state.sim_df, num_rows="fixed", hide_index=True, key="sim_editor")
    st.session_state.sim_df = edited

    st.caption("연차별 인원을 입력한 후 아래 버튼을 눌러 추징세액을 계산하세요.")
    if st.button("🔁 추징세액 계산하기", type="primary", key="btn_compute_clawback"):
        schedule = []
        for _, row in st.session_state.sim_df.iterrows():
            yidx = int(row["연차"])
            fol_total = int(row["사후연도 상시"])
            fol_youth = int(row.get("사후연도 청년등", 0))

            claw = calc_clawback(
                credit_applied=applied,
                base_headcount_at_credit=curr_total,
                headcount_in_followup_year=fol_total,
                retention_years_for_company=retention_years,
                year_index_from_credit=yidx,
                method=clawback_method,
            )
            schedule.append({"연차": yidx, "사후연도 상시": fol_total, "사후연도 청년등": fol_youth, "추징세액": int(claw)})

        schedule_df = _pd.DataFrame(schedule).sort_values("연차").reset_index(drop=True)
        st.dataframe(schedule_df, use_container_width=True)
        total_clawback = int(schedule_df["추징세액"].sum())
        st.metric("추징세액 합계", f"{total_clawback:,} 원")

        st.session_state.last_calc = {
            "gross": gross,
            "applied": applied,
            "retention_years": retention_years,
            "company_size": size.value if hasattr(size, "value") else str(size),
            "region": region.value if hasattr(region, "value") else str(region),
            "clawback_method": clawback_method,
            "base_headcount": curr_total,
            "schedule_records": schedule_df.to_dict(orient="records"),
            "total_clawback": total_clawback,
        }
    else:
        if st.session_state.get("last_calc") and st.session_state.last_calc.get("schedule_records"):
            _df = _pd.DataFrame(st.session_state.last_calc["schedule_records"])
            st.dataframe(_df, use_container_width=True)
            tc = int(st.session_state.last_calc.get("total_clawback", _df["추징세액"].sum()))
            st.metric("추징세액 합계", f"{tc:,} 원")

from chat_utils import stream_chat


def _build_chat_context() -> str:
    """현재 입력값과 마지막 계산 결과를 요약해 챗봇에 제공."""
    ci = st.session_state.get("current_inputs")
    cc = st.session_state.get("calc_context")
    lines = []
    if ci:
        lines.append(f"[현재 입력] 기업규모={ci.get('company_size')} / 지역={ci.get('region')}")
        lines.append(f"전년 상시={ci.get('prev_total')}, 청년등={ci.get('prev_youth')} / 당해 상시={ci.get('curr_total')}, 청년등={ci.get('curr_youth')}")
        lines.append(f"정규직 전환={ci.get('converted_regular')}, 육아휴직 복귀={ci.get('returned_parental')}")
        if ci.get("tax_before_credit") is not None:
            lines.append(f"세전세액={ci.get('tax_before_credit'):,}원")
        lines.append(f"추징방식={ci.get('clawback_method')}")
    if cc:
        lines.append(f"[최근 계산 결과] 총공제액={cc.get('gross_credit'):,}원 / 적용공제액={cc.get('applied_credit'):,}원 / 유지기간={cc.get('retention_years')}년 / 추징합계={cc.get('total_clawback'):,}원")
    return "\n".join(lines) if lines else ""
# .env 로드
# load_dotenv()  # removed unsafe call
st.divider()
st.header("💬 OpenAI 챗봇")
st.caption("계산기 사용과 관련해 궁금한 점을 물어보세요. (모델: gpt-4o-mini)")

# 🔐 API 키 입력/저장
if "openai_api_key" not in st.session_state:
    st.session_state.openai_api_key = os.getenv("OPENAI_API_KEY", "")

with st.expander("🔑 OpenAI API 키 설정", expanded=not bool(st.session_state.openai_api_key)):
    st.info("아래에 OpenAI API 키를 입력하세요. (한 번 입력하면 세션이 유지됩니다.)")
    key_input = st.text_input("API 키 입력 (sk-로 시작)", type="password", value=st.session_state.openai_api_key)
    if st.button("✅ 적용하기", use_container_width=True):
        st.session_state.openai_api_key = key_input.strip()
        if not st.session_state.openai_api_key.startswith("sk-"):
            st.warning("유효한 OpenAI API 키 형식이 아닙니다.")
        else:
            os.environ["OPENAI_API_KEY"] = st.session_state.openai_api_key
            st.success("API 키가 설정되었습니다. 이제 챗봇을 사용할 수 있습니다.")

# API 키가 없으면 챗봇 비활성화
if not st.session_state.openai_api_key:
    st.warning("⛔ OpenAI API 키가 설정되어 있지 않습니다. 위 입력창에 키를 입력하세요.")
# 세션 상태 초기화
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = "You are a helpful assistant for Korean tax credit calculator users. Reply in Korean by default."

# 챗봇 설정
with st.expander("⚙️ 챗봇 설정", expanded=False):
    model = st.selectbox("모델 선택", ["gpt-4o-mini", "gpt-4o"], index=0)
    temperature = st.slider("온도(창의성)", 0.0, 1.0, 0.2, 0.1)
    sys_prompt = st.text_area("시스템 프롬프트", st.session_state.system_prompt, height=80)
    include_ctx = st.checkbox("질문에 계산 맥락 포함하기", value=True)
    apply_pref = st.checkbox("설정 반영하기", value=True)
    if apply_pref:
        st.session_state.system_prompt = sys_prompt

# 대화 이력 표시
for m in st.session_state.chat_history:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

with st.expander("🐞 디버그(이벤트 타입 확인)", expanded=False):
    if st.button("이벤트 타입 미리보기"):
        # 미리보기용으로 events를 구성해 보여줍니다.
        preview = []
        if st.session_state.get("system_prompt"):
            preview.append({"role":"system","type":"input_text"})
        for m in st.session_state.get("chat_history", []):
            role = m.get("role","user")
            typ = "output_text" if role == "assistant" else "input_text"
            preview.append({"role": role, "type": typ})
        st.write(preview if preview else "이력 없음")

# 입력창
user_text = st.chat_input("메시지를 입력하세요…")
if user_text:
    st.session_state.chat_history.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        acc = ""
        try:
            ctx = _build_chat_context() if include_ctx else ""
            sys_msg = st.session_state.system_prompt + ("\n\n" + ctx if ctx else "")
            for token in stream_chat(
                st.session_state.chat_history,
                system_prompt=sys_msg,
                model=model,
            ):
                acc += token
                placeholder.markdown(acc)
        except Exception as e:
            acc = f"⚠️ 오류가 발생했어요: {e}"
            placeholder.markdown(acc)

    st.session_state.chat_history.append({"role": "assistant", "content": acc})