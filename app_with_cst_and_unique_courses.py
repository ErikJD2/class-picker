
# app.py
# Streamlit Class Picker: Choose up to four non-conflicting classes from an Excel file.
#
# Enhancements:
#   - Once a course is selected, all other rows with the SAME Course name are removed.
#   - Class times are treated as CST. If AM/PM is missing:
#       * 11:59 or earlier => AM
#       * 12:00 or later   => PM
#
# Usage:
#   1) pip install streamlit pandas openpyxl
#   2) streamlit run app.py

import re
from datetime import datetime, time
from typing import List, Tuple, Dict, Set

import pandas as pd
import streamlit as st

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_ALIASES = {d.lower(): d for d in DAYS}

_TIME_FORMATS = ["%I:%M %p","%I %p","%I:%M%p","%I%p","%H:%M","%H%M","%H"]
_AMPM_RE = re.compile(r"\b(am|pm)\b", re.IGNORECASE)

def _normalize_range_str(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _has_ampm(s: str) -> bool:
    return bool(_AMPM_RE.search(s))

def _parse_time_str_raw(s: str) -> time:
    s = s.strip()
    if re.fullmatch(r"\d{3,4}", s) and ":" not in s:
        if len(s) == 3: s = f"{s[0]}:{s[1:]}"
        else: s = f"{s[:-2]}:{s[-2:]}"
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError("raw-parse-failed")

def _parse_time_with_rule(s: str) -> time:
    s_clean = s.strip()
    try:
        if _has_ampm(s_clean):
            return _parse_time_str_raw(s_clean)
        return _parse_time_str_raw(s_clean)
    except ValueError:
        pass
    m = re.match(r"^\s*(\d{1,2})(?::(\d{1,2}))?\s*$", s_clean)
    if not m:
        raise ValueError(f"Unrecognized time: '{s}'")
    hour = int(m.group(1)); minute = int(m.group(2) or 0)
    if not (1 <= hour <= 12):
        raise ValueError(f"Unrecognized time: '{s}'")
    is_pm = (hour == 12)
    if is_pm:
        hour_24 = 12
    else:
        hour_24 = hour
    if hour >= 12:
        hour_24 = 12 if hour == 12 else hour + 12
    return time(hour_24, minute)

def _parse_single_range(range_str: str) -> Tuple[time, time]:
    range_str = _normalize_range_str(range_str)
    parts = range_str.split("-")
    if len(parts) != 2:
        raise ValueError(f"Expected one '-', got: '{range_str}'")
    start_str, end_str = parts[0].strip(), parts[1].strip()
    end_has_ampm = _has_ampm(end_str)
    start_has_ampm = _has_ampm(start_str)
    if end_has_ampm and not start_has_ampm:
        meridiem = _AMPM_RE.search(end_str).group(1).upper()
        try:
            start = _parse_time_str_raw(f"{start_str} {meridiem}")
            end = _parse_time_str_raw(end_str)
            if start >= end:
                flipped = "AM" if meridiem == "PM" else "PM"
                start = _parse_time_str_raw(f"{parts[0].strip()} {flipped}")
            return start, end
        except Exception:
            pass
    start = _parse_time_with_rule(start_str)
    end = _parse_time_with_rule(end_str)
    if not start_has_ampm and not end_has_ampm and start >= end:
        try:
            end = _parse_time_str_raw(f"{parts[1].strip()} PM")
        except Exception:
            pass
    if start >= end:
        raise ValueError(f"Start must be before end: '{range_str}'")
    return start, end

def parse_day_cell(cell_val) -> List[Tuple[time, time]]:
    if pd.isna(cell_val) or str(cell_val).strip() == "":
        return []
    text = str(cell_val).strip()
    chunks = re.split(r"[;,]", text)
    return [_parse_single_range(chunk.strip()) for chunk in chunks if chunk.strip()]

def times_overlap(a: Tuple[time, time], b: Tuple[time, time]) -> bool:
    return a[0] < b[1] and b[0] < a[1]

def classes_conflict(ma: Dict[str, List[Tuple[time, time]]], mb: Dict[str, List[Tuple[time, time]]]) -> bool:
    for d in DAYS:
        for sa in ma.get(d, []):
            for sb in mb.get(d, []):
                if times_overlap(sa, sb):
                    return True
    return False

st.set_page_config(page_title="Class Picker (CST)", layout="wide")
st.title("📚 Class Picker — Choose up to Four Non-Conflicting Classes (CST)")

st.markdown("""
**Time Zone:** Central Standard Time (CST).  
**If AM/PM missing:** 11:59 or earlier ⇒ AM, 12:00 or later ⇒ PM.  
""")

uploaded = st.file_uploader("Upload Excel (.xlsx or .xls)", type=["xlsx", "xls"])

def _reset_selections():
    for key in ["sel1","sel2","sel3","sel4"]:
        st.session_state.pop(key, None)

st.button("🔄 Reset selections", on_click=_reset_selections)

if not uploaded:
    st.stop()

df = pd.read_excel(uploaded)
df.rename(columns={c: str(c).strip() for c in df.columns}, inplace=True)
lower_cols = {c.lower(): c for c in df.columns}
course_col = lower_cols["course"]; number_col = lower_cols["number"]; instr_col = lower_cols["instructor"]
day_cols = {DAY_ALIASES[k]: v for k,v in lower_cols.items() if k in DAY_ALIASES}

meetings_by_id, labels_by_id = {}, {}
for idx,row in df.iterrows():
    per_day = {d: [] for d in DAYS}
    for d in DAYS:
        try:
            per_day[d] = parse_day_cell(row[day_cols[d]])
        except Exception:
            per_day[d] = []
    meetings_by_id[idx] = per_day
    labels_by_id[idx] = f"[{idx}] {row[course_col]} ({row[number_col]}) — {row[instr_col]}"

all_ids = list(df.index)
conflict_map = {i:set() for i in all_ids}
for i in all_ids:
    for j in all_ids:
        if i<j and classes_conflict(meetings_by_id[i], meetings_by_id[j]):
            conflict_map[i].add(j); conflict_map[j].add(i)

def remaining_after(selected: List[int]) -> Set[int]:
    rem = set(all_ids) - set(selected)
    for sid in selected:
        rem -= conflict_map[sid]
        sel_course = df.loc[sid, course_col].strip().lower()
        rem -= set(df.index[df[course_col].str.strip().str.lower()==sel_course])
    return rem

def opts_for(selected: List[int]) -> Dict[str,int]:
    ids = sorted(list(remaining_after(selected)))
    return {"— None —": -1, **{labels_by_id[i]: i for i in ids}}

# UI
sel_ids = []
for n in range(1,5):
    opts = opts_for(sel_ids)
    choice = st.selectbox(f"Select class #{n}", list(opts.keys()), key=f"sel{n}")
    cid = opts[choice]
    if cid!=-1: sel_ids.append(cid)

st.write("**Selected classes:**", sel_ids)
