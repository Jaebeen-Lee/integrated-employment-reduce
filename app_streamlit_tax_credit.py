# -*- coding: utf-8 -*-

# === Force scroll to top on load & reruns ===
import streamlit.components.v1 as _components
def _inject_force_top(_interval_ms: int = 120, _repeat: int = 15, _enable_mo: bool = True) -> None:
    _mo_js = "new MutationObserver(() => { forceTop(); }).observe(document.body, {childList: true, subtree: true});" if _enable_mo else ""
    _html = f"""
    <script>
    (function() {{
      function forceTop() {{
        try {{ window.scrollTo({{top: 0, behavior: 'auto'}}); }} catch(e) {{}}
      }}
      forceTop();
      let ticks = 0;
      const iv = setInterval(() => {{
        forceTop();
        if (++ticks > {{_repeat}}) clearInterval(iv);
      }}, {{_interval_ms}});
      document.addEventListener('visibilitychange', () => {{ if (!document.hidden) forceTop(); }});
      {_mo_js}
    }})();
    </script>
    """
    _components.html(_html, height=0)
# === /Force scroll to top ===
import streamlit as st
import json
import io
import os
import tempfile
import pandas as pd
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

from employment_tax_credit_calc import (
    CompanySize, Region, HeadcountInputs,
    load_params_from_json, calc_gross_credit,
    apply_caps_and_min_tax, calc_clawback, PolicyParameters
)

st.set_page_config(page_title="통합고용증대 세액공제 계산기", layout="wide")
# Force scroll to top on load
_inject_force_top()


# =====================
# 상단 스크롤 고정 (강제)
# =====================
import streamlit.components.v1 as components
components.html(
    """
    <script>
    (function() {
      function forceTop() { try { window.scrollTo({top: 0, behavior: 'auto'}); } catch(e) {} }
      forceTop();
      let ticks = 0;
      const iv = setInterval(() => { forceTop(); if (++ticks > 12) clearInterval(iv); }, 100);
      document.addEventListener('visibilitychange', () => { if (!document.hidden) forceTop(); });
      new MutationObserver(() => { forceTop(); }).observe(document.body, {childList: true, subtree: true});
    })();
    </script>
    """,
    height=0,
)

st.title("통합고용증대 세액공제 계산기")
st.caption("조특법 §29조의8에 따른 통합고용증대 세액공제를 계산합니다.")

# =====================
# 로컬 캐시 유틸
# =====================
def _cache_dir() -> Path:
    try:
        here = Path(__file__).parent
    except NameError:
        here = Path(".").resolve()
    d = here / ".app_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d

def save_cached_logo(png_bytes: bytes):
    try:
        ( _cache_dir() / "logo.png" ).write_bytes(png_bytes)
    except Exception:
        pass

def load_cached_logo() -> bytes | None:
    p = _cache_dir() / "logo.png"
    return p.read_bytes() if p.exists() else None

def save_prefs(company_name: str):
    try:
        pref = {"company_name": company_name}
        ( _cache_dir() / "prefs.json" ).write_text(json.dumps(pref, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def load_prefs() -> dict:
    p = _cache_dir() / "prefs.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

# =====================
# 세션 상태 기본 초기화 + 캐시 로드
# =====================
def _ensure(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]

_ensure("saved_logo_png", None)
_ensure("saved_company_name", None)
_ensure("followup_table", None)
_ensure("calc_summary", None)
_ensure("last_calc", None)

# 캐시에서 로고/기관명 불러오기 (세션이 비어 있을 때만)
if st.session_state.get("saved_logo_png") is None:
    cached = load_cached_logo()
    if cached:
        st.session_state.saved_logo_png = cached
prefs = load_prefs()
if st.session_state.get("saved_company_name") is None and prefs.get("company_name"):
    st.session_state.saved_company_name = prefs["company_name"]

# ---- rerun 시 NameError 방지용 전역 플래그 초기화 ----
trigger_calc = False

# ==== 사후관리 표 유틸 ====
def ensure_followup_table(retention_years:int, default_total:int, default_youth:int):
    import pandas as _pd
    cur = st.session_state.get("followup_table")
    target_years = list(range(1, int(retention_years) + 1))

    if cur is None or getattr(cur, "empty", True):
        st.session_state.followup_table = _pd.DataFrame(
            [{"연차": y, "사후연도 상시": int(default_total), "사후연도 청년등": int(default_youth)} for y in target_years]
        )
        return

    cur = cur.copy()
    for col in ["연차", "사후연도 상시", "사후연도 청년등"]:
        if col in cur.columns:
            cur[col] = _pd.to_numeric(cur[col], errors="coerce").fillna(0).astype(int)

    map_exist = {int(r["연차"]): (int(r["사후연도 상시"]), int(r.get("사후연도 청년등", 0))) for _, r in cur.iterrows()}
    rows = []
    for y in target_years:
        if y in map_exist:
            tot, yth = map_exist[y]
            rows.append({"연차": y, "사후연도 상시": tot, "사후연도 청년등": yth})
        else:
            rows.append({"연차": y, "사후연도 상시": int(default_total), "사후연도 청년등": int(default_youth)})
    st.session_state.followup_table = _pd.DataFrame(rows).sort_values("연차").reset_index(drop=True)

with st.sidebar:
    st.header("1) 최근 법령 적용")
    uploaded = st.file_uploader("최근 법령 JSON 업로드", type=["json"], accept_multiple_files=False)
    default_info = st.toggle("예시 파라미터 사용", value=True)

    st.header("2) 보고서 옵션")
    company_name = st.text_input("회사/기관명 (머리글용)", value=st.session_state.saved_company_name or "(기관명)")
    logo_file = st.file_uploader("회사 로고 (PNG 권장)", type=["png"], accept_multiple_files=False)
    remember_logo = st.checkbox("이 로고/기관명을 계속 사용(앱 캐시에 저장)", value=True)

    logo_bytes = None
    if logo_file is not None:
        logo_bytes = logo_file.getvalue()
        if remember_logo:
            st.session_state.saved_logo_png = logo_bytes
            save_cached_logo(logo_bytes)  # 디스크 캐시
    elif st.session_state.saved_logo_png is not None:
        logo_bytes = st.session_state.saved_logo_png or load_cached_logo()

    if company_name:
        st.session_state.saved_company_name = company_name
        if remember_logo:
            save_prefs(company_name)

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
        st.info("미업로드시 예시 파라미터를 사용)")

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

st.header("세액 한도/최저한세 옵션")
tax_before_credit = st.number_input("세전세액(최저한세 적용 시 필요)", min_value=0, value=120_000_000, step=1)

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

    st.session_state.calc_summary = {
        "gross": int(gross),
        "applied": int(applied),
        "retention_years": int(retention_years),
        "company_size": size.value,
        "region": region.value,
        "base_headcount": int(curr_total),
        "clawback_method": clawback_method,
    }
    ensure_followup_table(retention_years, int(curr_total), int(curr_youth))

summary = st.session_state.calc_summary
if summary is not None:
    try:
        ensure_followup_table(int(summary["retention_years"]), int(summary["base_headcount"]), int(st.session_state.current_inputs.get("curr_youth", 0)))
    except Exception:
        pass

    st.subheader("① 공제액 계산 결과")
    st.metric("총공제액 (최저한세/한도 전)", f"{summary['gross']:,} 원")
    st.metric("적용 공제액 (최저한세/한도 후)", f"{summary['applied']:,} 원")
    st.write(f"유지기간(사후관리 대상): **{summary['retention_years']}년**")

    st.subheader("② 사후관리(추징) 시뮬레이션 - 다년표")
    st.caption("표를 입력한 뒤 아래 **[추징세액 계산하기]** 버튼을 누르면 표가 자동 반영되어 계산됩니다.")

    with st.container():
        buf_df = st.session_state.followup_table.copy() if st.session_state.followup_table is not None else pd.DataFrame()
        colcfg = {
            "연차": st.column_config.NumberColumn("연차", step=1, disabled=True),
            "사후연도 상시": st.column_config.NumberColumn("사후연도 상시", step=1, min_value=0),
            "사후연도 청년등": st.column_config.NumberColumn("사후연도 청년등", step=1, min_value=0),
        }
        edited = st.data_editor(
            buf_df,
            num_rows="fixed",
            hide_index=True,
            key="followup_editor",
            column_config=colcfg,
            use_container_width=True,
        )

    if st.button("🔁 추징세액 계산하기", type="primary"):
        st.session_state.followup_table = edited.copy()
        trigger_calc = True

    if trigger_calc:
        schedule_records = []
        for _, row in st.session_state.followup_table.iterrows():
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

        st.dataframe(schedule_df, use_container_width=True)
        st.metric("추징세액 합계", f"{total_clawback:,} 원")

        st.session_state.last_calc = {
            **summary,
            "schedule_records": schedule_df.to_dict(orient="records"),
            "total_clawback": total_clawback,
        }

if not trigger_calc:
    _prev = st.session_state.get("last_calc")
    if _prev is not None and _prev.get("schedule_records"):
        import pandas as pd
        schedule_df = pd.DataFrame(_prev["schedule_records"])
        st.subheader("사후관리(추징) 결과")
        st.dataframe(schedule_df, use_container_width=True)
        st.metric("추징세액 합계", f"{int(_prev.get('total_clawback',0)):,} 원")

safe_total_clawback = (st.session_state.last_calc["total_clawback"]
    if (st.session_state.get("last_calc") and "total_clawback" in st.session_state.last_calc)
    else 0)

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
# 엑셀 생성 (요약 + 사후관리 결과표) + 상단 로고 워터마크 삽입 (임시파일 방식)
# ============================
def _build_excel():
    """엑셀 내보내기: (1) 결과요약 시트(상단 로고 워터마크 포함), (2) 사후관리 결과표 시트."""
    buffer = io.BytesIO()
    wb = Workbook()
    tmp_logo_path = None

    # ---- 시트1: 결과요약 ----
    ws_sum = wb.active
    ws_sum.title = "결과요약"

    # 로고 워터마크 삽입: 임시파일에 저장 후 openpyxl로 로드 (A1 위치)
    start_row = 1
    logo_bytes = st.session_state.get("saved_logo_png") or load_cached_logo()
    if logo_bytes:
        try:
            img = PILImage.open(io.BytesIO(logo_bytes))
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            max_w = 420
            if img.width > max_w:
                ratio = max_w / float(img.width)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)))
            # 매우 연하게(약 15% 불투명)
            r, g, b, a = img.split()
            a = a.point(lambda p: int(p * 0.15))
            img = PILImage.merge("RGBA", (r, g, b, a))
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                img.save(tmp, format="PNG")
                tmp_logo_path = tmp.name
            xl_img = XLImage(tmp_logo_path)
            ws_sum.add_image(xl_img, "A1")
            start_row = 8
            ws_sum.row_dimensions[1].height = 24
        except Exception:
            start_row = 1

    # 데이터 작성
    summary = st.session_state.get("calc_summary") or {}
    inputs = st.session_state.get("current_inputs") or {}
    last = st.session_state.get("last_calc") or {}

    header_row = start_row
    ws_sum.cell(row=header_row, column=1, value="항목")
    ws_sum.cell(row=header_row, column=2, value="값")

    rows = [
        ("생성일시", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("회사/기관명", st.session_state.get("saved_company_name") or ""),
        ("기업규모", summary.get("company_size", "")),
        ("지역", summary.get("region", "")),
        ("유지기간(년)", summary.get("retention_years", "")),
        ("총공제액(최저한세/한도 전)", f"{summary.get('gross', 0):,}"),
        ("적용 공제액(최저한세/한도 후)", f"{summary.get('applied', 0):,}"),
        ("세전세액(입력)", f"{inputs.get('tax_before_credit', 0):,}"),
        ("추징 방식", summary.get("clawback_method", inputs.get('clawback_method', ''))),
        ("추징 합계", f"{last.get('total_clawback', 0):,}"),
        ("전년 상시/청년등", f"{inputs.get('prev_total', 0)}/{inputs.get('prev_youth', 0)}"),
        ("당해 상시/청년등", f"{inputs.get('curr_total', 0)}/{inputs.get('curr_youth', 0)}"),
        ("정규직 전환 / 육아휴직 복귀", f"{inputs.get('converted_regular', 0)} / {inputs.get('returned_parental', 0)}"),
    ]
    r = header_row + 1
    for k, v in rows:
        ws_sum.cell(row=r, column=1, value=k)
        ws_sum.cell(row=r, column=2, value=v)
        r += 1

    bold = Font(bold=True)
    ws_sum.cell(row=header_row, column=1).font = bold
    ws_sum.cell(row=header_row, column=2).font = bold
    ws_sum.column_dimensions["A"].width = 28
    ws_sum.column_dimensions["B"].width = 36

    # ---- 시트2: 사후관리 결과표 ----
    ws = wb.create_sheet(title="사후관리 결과표")
    headers = ["연차", "사후연도 상시", "사후연도 청년등", "추징세액"]
    ws.append(headers)
    last_calc = st.session_state.get("last_calc")
    if last_calc and last_calc.get("schedule_records"):
        for row in last_calc["schedule_records"]:
            ws.append([row["연차"], row["사후연도 상시"], row.get("사후연도 청년등", 0), row["추징세액"]])

    try:
        wb.save(buffer)
    finally:
        if tmp_logo_path and os.path.exists(tmp_logo_path):
            try:
                os.remove(tmp_logo_path)
            except Exception:
                pass
    return buffer.getvalue()

excel_bytes = _build_excel()
excel_name = f"tax_credit_result_pro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
st.download_button(
    label="엑셀 다운로드 (.xlsx)",
    file_name=excel_name,
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    data=excel_bytes,
)

# ==============================
# 💬 OpenAI 챗봇 (메인 화면 하단) — 기존 구조 유지
# ==============================
from dotenv import load_dotenv
import importlib, chat_utils
importlib.reload(chat_utils)
from chat_utils import stream_chat

def _build_chat_context() -> str:
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

load_dotenv()

st.divider()
st.header("💬 OpenAI 챗봇")
st.caption("계산기 사용과 관련해 궁금한 점을 물어보세요.")

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

if not st.session_state.openai_api_key:
    st.warning("⛔ OpenAI API 키가 설정되어 있지 않습니다. 위 입력창에 키를 입력하세요.")
    st.stop()

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = "You are a helpful assistant for Korean tax credit calculator users. Reply in Korean by default."

with st.expander("⚙️ 챗봇 설정", expanded=False):
    model = st.selectbox("모델 선택", ["gpt-4o-mini", "gpt-4o"], index=0)
    temperature = st.slider("온도(창의성)", 0.0, 1.0, 0.2, 0.1)
    sys_prompt = st.text_area("시스템 프롬프트", st.session_state.system_prompt, height=80)
    include_ctx = st.checkbox("질문에 계산 맥락 포함하기", value=True)
    apply_pref = st.checkbox("설정 반영하기", value=True)
    if apply_pref:
        st.session_state.system_prompt = sys_prompt

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
