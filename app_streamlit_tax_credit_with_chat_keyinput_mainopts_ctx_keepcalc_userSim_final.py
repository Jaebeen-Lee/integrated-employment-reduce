
# -*- coding: utf-8 -*-
import streamlit as st
import json
import io
import os
import pandas as pd
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, NamedStyle
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

from employment_tax_credit_calc import (
    CompanySize, Region, HeadcountInputs,
    load_params_from_json, calc_gross_credit,
    apply_caps_and_min_tax, calc_clawback, PolicyParameters
)

st.set_page_config(page_title="통합고용세액공제 계산기 (Pro, 메모리 로고·수정)", layout="wide")

st.title("통합고용세액공제 계산기 · Pro (조특법 §29조의8)")
st.caption("로고 메모리 삽입 + 엑셀 서식 적용. NamedStyle 추가 호환성 보완. (사후관리 입력/유지 버그 수정)")

# =====================
# 세션 상태 기본 초기화
# =====================
def _ensure(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

_ensure("saved_logo_png", None)
_ensure("saved_company_name", None)
_ensure("followup_table", None)              # 사후관리 표 유지용
_ensure("calc_summary", None)                # 계산하기 직후 공제요약 유지
_ensure("last_calc", None)                   # 추징세액 계산하기 결과 유지

with st.sidebar:
    st.header("1) 정책 파라미터")
    uploaded = st.file_uploader("시행령 기준 파라미터 JSON 업로드", type=["json"], accept_multiple_files=False)
    default_info = st.toggle("예시 파라미터 사용 (업로드 없을 때)", value=True)

    st.header("2) 보고서 옵션")
    company_name = st.text_input("회사/기관명 (머리글용)", value=st.session_state.saved_company_name or "(기관명)")
    logo_file = st.file_uploader("회사 로고 (PNG 권장)", type=["png"], accept_multiple_files=False)
    remember_logo = st.checkbox("이 로고를 계속 사용(세션에 저장)", value=True)

    logo_bytes = None
    if logo_file is not None:
        logo_bytes = logo_file.getvalue()
        if remember_logo:
            st.session_state.saved_logo_png = logo_bytes
    elif st.session_state.saved_logo_png is not None:
        logo_bytes = st.session_state.saved_logo_png

    if company_name and remember_logo:
        st.session_state.saved_company_name = company_name

    params: PolicyParameters = None
    if uploaded is not None:
        try:
            cfg = json.load(uploaded)
            tmp_path = "._tmp_params.json"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
            params = load_params_from_json(tmp_path)
            os.remove(tmp_path)
            st.success("업로드한 파라미터를 불러왔습니다.")
        except Exception as e:
            st.error(f"파라미터 로딩 실패: {e}")
    elif default_info:
        demo_cfg = {
            "per_head_basic": {
                "중소기업": {"수도권": 1200000, "지방": 1300000},
                "중견기업": {"수도권": 900000, "지방": 1000000},
                "대기업":   {"수도권": 600000, "지방": 700000}
            },
            "per_head_youth": {
                "중소기업": {"수도권": 1500000, "지방": 1600000},
                "중견기업": {"수도권": 1100000, "지방": 1200000},
                "대기업":   {"수도권": 800000,  "지방": 900000}
            },
            "per_head_conversion": 800000,
            "per_head_return_from_parental": 800000,
            "retention_years": {"중소기업": 3, "중견기업": 3, "대기업": 2},
            "max_credit_total": None,
            "min_tax_limit_rate": 0.07,
            "excluded_industries": ["유흥주점업", "기타소비성서비스업"]
        }
        tmp_path = "._tmp_params_demo.json"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(demo_cfg, f, ensure_ascii=False)
        params = load_params_from_json(tmp_path)
        os.remove(tmp_path)
        st.info("예시 파라미터를 사용 중입니다. (업로드 시 자동 대체)")

st.subheader("기업 정보 및 사후관리 옵션")
colA, colB = st.columns(2)
with colA:
    size_label = st.selectbox("기업규모", [s.value for s in CompanySize], index=0, key="main_company_size")
    region_label = st.selectbox("지역", [r.value for r in Region], index=1, key="main_region")
    size = CompanySize(size_label)
    region = Region(region_label)
with colB:
    clawback_options = {
        "비례 추징 (감소율만큼)": "proportional",
        "전액 추징 (감소 발생 시 전체)": "all_or_nothing",
        "구간 추징 (감소율 구간별 단계)": "tiered"
    }
    selected_label = st.selectbox("추징 방식 선택", list(clawback_options.keys()), index=0, key="main_clawback_method")
    clawback_method = clawback_options[selected_label]

st.header("고용 인원 입력")
col1, col2, col3 = st.columns(3)

with col1:
    prev_total = st.number_input("전년 상시근로자 수", min_value=0, value=50, step=1)
    prev_youth = st.number_input("전년 청년등 상시근로자 수", min_value=0, value=10, step=1)
with col2:
    curr_total = st.number_input("당해 상시근로자 수", min_value=0, value=60, step=1)
    curr_youth = st.number_input("당해 청년등 상시근로자 수", min_value=0, value=14, step=1)
with col3:
    converted_regular = st.number_input("정규직 전환 인원 (해당연도)", min_value=0, value=2, step=1)
    returned_parental = st.number_input("육아휴직 복귀 인원 (해당연도)", min_value=0, value=1, step=1)

# 최저한세용 세전세액
st.header("세액 한도/최저한세 옵션")
tax_before_credit = st.number_input("세전세액(최저한세 적용 시 필요)", min_value=0, value=120_000_000, step=1)

# 현재 입력값을 세션에 저장(챗봇 컨텍스트용)
st.session_state.current_inputs = {
    "company_size": size.value,
    "region": region.value,
    "prev_total": int(prev_total),
    "prev_youth": int(prev_youth),
    "curr_total": int(curr_total),
    "curr_youth": int(curr_youth),
    "converted_regular": int(converted_regular),
    "returned_parental": int(returned_parental),
    "tax_before_credit": int(tax_before_credit),
    "clawback_method": clawback_method,
}

st.divider()
run = st.button("계산하기", type="primary", disabled=(params is None))

# ============================
# 계산하기: 공제액 산출 + 유지
# ============================
if run:
    if params is None:
        st.error("파라미터(JSON)를 먼저 불러오세요.")
        st.stop()

    heads = HeadcountInputs(
        prev_total=int(prev_total),
        curr_total=int(curr_total),
        prev_youth=int(prev_youth),
        curr_youth=int(curr_youth),
        converted_regular=int(converted_regular),
        returned_from_parental_leave=int(returned_parental),
    )
    gross = calc_gross_credit(size, region, heads, params)
    applied = apply_caps_and_min_tax(gross, params, tax_before_credit=int(tax_before_credit) if tax_before_credit else None)
    retention_years = params.retention_years[size]

    # 공제 요약을 세션에 보존 (편집 중 rerun에도 유지)
    st.session_state.calc_summary = {
        "gross": int(gross),
        "applied": int(applied),
        "retention_years": int(retention_years),
        "company_size": size.value,
        "region": region.value,
        "base_headcount": int(curr_total),
        "clawback_method": clawback_method,
    }

    # 사후관리 기본표 초기화(최초 한 번만) — 사용자가 값 입력 후에는 덮어쓰지 않음
    # 보존형 초기화/정렬: 기존 값은 유지, 부족한 연차만 기본값으로 채움
    ensure_followup_table(retention_years, int(curr_total), int(curr_youth))

# ============================
# 공제 요약 표시 (유지)
# ============================
summary = st.session_state.calc_summary
if summary is not None:

# 유지기간이 바뀌는 경우에도 기존 값 보존하면서 연차만 맞춰줌
try:
    ensure_followup_table(int(summary["retention_years"]), int(summary["base_headcount"]), int(st.session_state.current_inputs.get("curr_youth", 0)))
except Exception:
    pass
    st.subheader("① 공제액 계산 결과")
    st.metric("총공제액 (최저한세/한도 전)", f"{summary['gross']:,} 원")
    st.metric("적용 공제액 (최저한세/한도 후)", f"{summary['applied']:,} 원")
    st.write(f"유지기간(사후관리 대상): **{summary['retention_years']}년**")

    # ============================
    # 사후관리(추징) 시뮬레이션 입력표
    # ============================
    st.subheader("② 사후관리(추징) 시뮬레이션 - 다년표")
    st.caption("연차별로 '사후연도 상시'와 '사후연도 청년등'을 직접 입력 후, 아래 버튼을 눌러 추징세액을 계산하세요.")
    # 사용자가 입력한 값을 유지하기 위해 세션의 표를 항상 원본으로 사용
    edited = st.data_editor(
        st.session_state.followup_table.copy() if st.session_state.followup_table is not None else pd.DataFrame(),
        num_rows="fixed",
        hide_index=True,
        key="followup_editor",
    )
    # 사용자가 편집하면 즉시 세션 상태로 반영 (기본값으로 돌아가는 문제 방지)
    st.session_state.followup_table = edited.copy()

    # 별도의 계산 버튼 (공제결과는 유지)
    if st.button("🔁 추징세액 계산하기", type="primary"):
        schedule_records = []
        for _, row in edited.iterrows():
            yidx = int(row["연차"])
            fol_total = int(row["사후연도 상시"])
            fol_youth = int(row.get("사후연도 청년등", 0))

            claw = calc_clawback(
                credit_applied=int(summary["applied"]),
                base_headcount_at_credit=int(summary["base_headcount"]),
                headcount_in_followup_year=fol_total,
                retention_years_for_company=int(summary["retention_years"]),
                year_index_from_credit=yidx,
                method=summary["clawback_method"],
            )
            schedule_records.append({
                "연차": yidx,
                "사후연도 상시": fol_total,
                "사후연도 청년등": fol_youth,
                "추징세액": int(claw),
            })
        schedule_df = pd.DataFrame(schedule_records).sort_values("연차").reset_index(drop=True)
        total_clawback = int(schedule_df["추징세액"].sum()) if not schedule_df.empty else 0

        # 결과 표시
        st.dataframe(schedule_df, use_container_width=True)
        st.metric("추징세액 합계", f"{total_clawback:,} 원")

        # rerun에도 유지되도록 저장
        st.session_state.last_calc = {
            **summary,
            "schedule_records": schedule_df.to_dict(orient="records"),
            "total_clawback": total_clawback,
        }

# ============================
# 챗봇/컨텍스트
# ============================
# 안전 가드: total_clawback 기본값
safe_total_clawback = st.session_state.last_calc["total_clawback"] if (st.session_state.last_calc and "total_clawback" in st.session_state.last_calc) else 0

# 챗봇 컨텍스트 저장 (공제 결과는 삭제하지 않음)
st.session_state.calc_context = {
    "company_size": summary["company_size"] if summary else None,
    "region": summary["region"] if summary else None,
    "retention_years": summary["retention_years"] if summary else None,
    "clawback_method": summary["clawback_method"] if summary else None,
    "inputs": st.session_state.get("current_inputs", {}),
    "gross_credit": summary["gross"] if summary else None,
    "applied_credit": summary["applied"] if summary else None,
    "total_clawback": safe_total_clawback,
}

# ============================
# 엑셀 생성 (가능할 때만)
# ============================

def _build_excel():
    buffer = io.BytesIO()
    wb = Workbook()
    ws = wb.active; ws.title = "요약"

    # 스타일
    title_font = Font(name="맑은 고딕", size=14, bold=True)
    header_fill = PatternFill("solid", fgColor="F2F2F2")
    thin = Side(style="thin", color="CCCCCC")
    border_all = Border(top=thin, bottom=thin, left=thin, right=thin)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")

    # NamedStyle 등록
    currency_style = NamedStyle(name="KRW")
    currency_style.number_format = '#,##0"원"'
    currency_style.alignment = right
    try:
        wb.add_named_style(currency_style)
    except Exception:
        pass

    # 로고 (메모리)
    row_cursor = 1
    if st.session_state.saved_logo_png is not None:
        try:
            pil_img = PILImage.open(io.BytesIO(st.session_state.saved_logo_png))
            img = XLImage(pil_img)
            img.width = 140; img.height = 40
            ws.add_image(img, "A1"); row_cursor = 4
        except Exception as e:
            st.warning(f"로고 삽입 중 오류: {e}")

    title_cell = ws.cell(row=row_cursor, column=1, value="통합고용세액공제 계산 결과")
    title_cell.font = title_font
    ws.merge_cells(start_row=row_cursor, start_column=1, end_row=row_cursor, end_column=6)
    ws.cell(row=row_cursor, column=7, value=f"작성일자: {datetime.now().strftime('%Y-%m-%d')}").alignment = right
    ws.cell(row=row_cursor+1, column=1, value=f"기관명: {st.session_state.saved_company_name or '(기관명)'}")

    summary = st.session_state.get("calc_summary")
    if summary:
        ws.cell(row=row_cursor+1, column=4, value=f"기업규모/지역: {summary['company_size']}/{summary['region']}")

    start = row_cursor + 3
    data = [["항목", "값"]]
    if summary:
        data.extend([
            ["총공제액 (최저한세/한도 전)", int(summary["gross"])],
            ["적용 공제액 (최저한세/한도 후)", int(summary["applied"])],
            ["유지기간(년)", int(summary["retention_years"])],
            ["추징방식", summary["clawback_method"]],
        ])
    last_calc = st.session_state.get("last_calc")
    if last_calc is not None:
        data.append(["추징세액 합계", int(last_calc.get("total_clawback", 0))])

    # 요약 채우기
    for r_idx, row in enumerate(data, start=start):
        for c_idx, val in enumerate(row, start=1):
            ws.cell(row=r_idx, column=c_idx, value=val)

    if summary:
        ws.cell(row=start+1, column=2).style = "KRW"
        ws.cell(row=start+2, column=2).style = "KRW"
    if last_calc is not None:
        ws.cell(row=start+4, column=2).style = "KRW"

    for r in ws.iter_rows(min_row=start, max_row=start+len(data)-1, min_col=1, max_col=2):
        for cell in r:
            cell.border = border_all
            if cell.row == start:
                cell.fill = header_fill; cell.alignment = center
            elif cell.column == 1:
                cell.alignment = center
            else:
                if cell.style != "KRW":
                    cell.alignment = right

    # ▶ 사후관리 입력표 시트
    ws_in = wb.create_sheet("사후관리 입력표")
    headers_in = ["연차", "사후연도 상시", "사후연도 청년등"]
    ws_in.append(headers_in)
    fup = st.session_state.get("followup_table")
    if fup is not None and not fup.empty:
        for _, r in fup.iterrows():
            ws_in.append([int(r["연차"]), int(r["사후연도 상시"]), int(r.get("사후연도 청년등", 0))])

    for cell in ws_in[1]:
        cell.fill = header_fill; cell.border = border_all; cell.alignment = center; cell.font = Font(bold=True)
    for r in range(2, ws_in.max_row+1):
        ws_in.cell(row=r, column=1).alignment = center
        for c in [2,3]:
            ws_in.cell(row=r, column=c).alignment = right
        for c in [1,2,3]:
            ws_in.cell(row=r, column=c).border = border_all
    for col, w in zip(["A","B","C"], [10, 18, 18]):
        ws_in.column_dimensions[col].width = w

    # ▶ 사후관리 결과표 시트(계산한 경우만)
    if last_calc is not None:
        ws_res = wb.create_sheet("사후관리 결과표")
        headers = ["연차", "사후연도 상시", "사후연도 청년등", "추징세액"]
        ws_res.append(headers)
        for row in last_calc["schedule_records"]:
            ws_res.append([row["연차"], row["사후연도 상시"], row.get("사후연도 청년등", 0), row["추징세액"]])

        for cell in ws_res[1]:
            cell.fill = header_fill; cell.border = border_all; cell.alignment = center; cell.font = Font(bold=True)
        for r in range(2, 2 + len(last_calc["schedule_records"])):
            ws_res.cell(row=r, column=1).alignment = center
            ws_res.cell(row=r, column=2).alignment = right
            ws_res.cell(row=r, column=3).alignment = right
            ws_res.cell(row=r, column=4).style = "KRW"
            for c in range(1, 5):
                ws_res.cell(row=r, column=c).border = border_all
        for col, w in zip(["A","B","C","D"], [10, 18, 18, 18]):
            ws_res.column_dimensions[col].width = w

    # 컬럼 폭/헤더
    ws.column_dimensions["A"].width = 22; ws.column_dimensions["B"].width = 26
    try:
        ws.header_footer.left_header = f"&L{st.session_state.saved_company_name or '(기관명)'}"
        ws.header_footer.right_header = "&R통합고용세액공제 계산 결과"
    except Exception:
        pass

    wb.save(buffer)
    return buffer.getvalue()

# 다운로드 버튼 (요약만 있어도 활성화)
excel_bytes = _build_excel()
excel_name = f"tax_credit_result_pro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
st.download_button(
    label="엑셀 다운로드 (.xlsx, Pro 포맷)",
    file_name=excel_name,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    data=excel_bytes,
)

# ==============================
# 💬 OpenAI 챗봇 (메인 화면 하단)
# ==============================
import os
from dotenv import load_dotenv
import importlib, chat_utils
importlib.reload(chat_utils)
from chat_utils import stream_chat

# ==== 보존형 사후표 생성/정렬 유틸 ====
def ensure_followup_table(retention_years:int, default_total:int, default_youth:int):
    """
    사후관리 표를 '연차 1..N'으로 정렬/보충하되, 사용자가 입력한 값은 절대 덮어쓰지 않는다.
    필요 시 새 연차만 기본값으로 추가하고, 남는 연차는 제거한다.
    """
    import pandas as _pd

    # 현재 표
    cur = st.session_state.get("followup_table")
    # 목표 인덱스
    target_years = list(range(1, int(retention_years) + 1))

    if cur is None or cur.empty:
        st.session_state.followup_table = _pd.DataFrame(
            [{"연차": y, "사후연도 상시": int(default_total), "사후연도 청년등": int(default_youth)} for y in target_years]
        )
        return

    # 사본으로 작업
    cur = cur.copy()
    # dtype 정리
    for col in ["연차", "사후연도 상시", "사후연도 청년등"]:
        if col in cur.columns:
            cur[col] = _pd.to_numeric(cur[col], errors="coerce").fillna(0).astype(int)

    # 현재 연차 -> 값 맵
    map_exist = {int(r["연차"]): (int(r["사후연도 상시"]), int(r.get("사후연도 청년등", 0))) for _, r in cur.iterrows()}

    rows = []
    for y in target_years:
        if y in map_exist:
            tot, yth = map_exist[y]
            rows.append({"연차": y, "사후연도 상시": tot, "사후연도 청년등": yth})
        else:
            rows.append({"연차": y, "사후연도 상시": int(default_total), "사후연도 청년등": int(default_youth)})

    st.session_state.followup_table = _pd.DataFrame(rows).sort_values("연차").reset_index(drop=True)


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
load_dotenv()

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
    st.stop()

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
