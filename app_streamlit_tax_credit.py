# -*- coding: utf-8 -*-
import streamlit as st
import json
import io
import os
import tempfile
import pandas as pd
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

from employment_tax_credit_calc import (
    CompanySize, Region, HeadcountInputs,
    load_params_from_json, calc_gross_credit,
    apply_caps_and_min_tax, calc_clawback, PolicyParameters
)

st.set_page_config(page_title="통합고용세액공제 계산기 (Pro, 워터마크+상단스크롤)", layout="wide")

# 항상 맨 위로 스크롤
st.markdown(
    """
    <script>
        window.scrollTo({ top: 0, behavior: 'smooth' });
    </script>
    """,
    unsafe_allow_html=True
)

st.title("통합고용세액공제 계산기 · Pro (조특법 §29조의8)")
st.caption("엑셀 결과요약 시트 상단에 연한 로고 워터마크 삽입 + 앱 실행 시 스크롤 자동 상단 이동")

# 이후 전체 로직은 기존 워터마크 버전과 동일
# (이전 파일 app_streamlit_tax_credit_logo_watermark.py의 내용 포함)
from app_streamlit_tax_credit_logo_watermark import *
