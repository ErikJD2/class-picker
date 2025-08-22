
# app.py
# Streamlit Class Picker: Choose up to four non-conflicting classes from an Excel file.
#
# Usage:
#   1) pip install streamlit pandas openpyxl
#   2) streamlit run app.py
#
# Excel format expected:
#   Columns: Course, Number, Instructor, Monday, Tuesday, Wednesday, Thursday, Friday
#   Day cells contain time ranges like "9:00-10:15 AM", "9-10:15AM", or "13:00-14:15".
#   Multiple ranges allowed per cell, separated by ";" or ",".
#
# Notes:
#   - Conflict = any overlap on the same day (partial overlap counts).
#   - Robust time parsing supports 12/24-hour inputs; if a range omits AM/PM on the start but has it on the end,
#     the start inherits the end's meridiem.

import re
from datetime import datetime, time
from typing import List, Tuple, Dict, Set

import pandas as pd
import streamlit as st

# ----------------------------- Configuration -----------------------------

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_ALIASES = {d.lower(): d for d in DAYS}  # case-insensitive matching

# ----------------------------- Utilities: Time Parsing -----------------------------

_TIME_FORMATS = [
    "%I:%M %p",  # 9:05 AM
    "%I %p",     # 9 AM
    "%I:%M%p",   # 9:05AM
    "%I%p",      # 9AM
    "%H:%M",     # 13:05
    "%H%M",      # 1305
    "%H",        # 9 (24h)
]

def _normalize_range_str(s: str) -> str:
    if not isinstance(s, str):
        return ""
    # unify dashes and spacing
    s = s.strip()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _parse_time_str(s: str) -> time:
    s = s.strip()
    # If time looks like "900" or "930", try to insert colon
    if re.fullmatch(r"\d{3,4}", s) and ":" not in s:
        # E.g., 900 -> 9:00, 1330 -> 13:30
        if len(s) == 3:
            s = f"{s[0]}:{s[1:]}"
        else:
            s = f"{s[:-2]}:{s[-2:]}"
    # Try formats
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    # Last-chance: add minutes if only hour provided without AM/PM and not 24h parseable
    if re.fullmatch(r"\d{1,2}", s):
        for fmt in ["%I", "%H"]:
            try:
                return datetime.strptime(s, fmt).time()
            except ValueError:
                pass
    raise ValueError(f"Unrecognized time: '{s}'")

def _parse_single_range(range_str: str) -> Tuple[time, time]:
    """
    Parse a single time range like '9:00-10:15 AM', '9-10:15AM', '13:00-14:15'.
    If end has AM/PM and start does not, propagate end's meridiem to start.
    """
    range_str = _normalize_range_str(range_str)
    if not range_str:
        raise ValueError("Empty range")

    # Split on dash
    parts = range_str.split("-")
    if len(parts) != 2:
        raise ValueError(f"Expected one '-', got: '{range_str}'")
    start_str, end_str = parts[0].strip(), parts[1].strip()

    # If end contains AM/PM and start lacks, inherit
    meridiem = None
    m = re.search(r"(am|pm)\b", end_str, flags=re.IGNORECASE)
    if m and not re.search(r"(am|pm)\b", start_str, flags=re.IGNORECASE):
        meridiem = m.group(1)
        start_str = f"{start_str} {meridiem.upper()}"

    start = _parse_time_str(start_str)
    end = _parse_time_str(end_str)
    if start >= end:
        # Handle ranges like "11:30-1:00 PM" where start missing meridiem but inherited incorrectly.
        # If start >= end and no explicit AM/PM on start originally, try flipping AM/PM:
        if meridiem is not None:
            flipped = "AM" if meridiem.lower() == "pm" else "PM"
            try:
                start = _parse_time_str(parts[0].strip() + f" {flipped}")
            except ValueError:
                pass  # fall through
        if start >= end:
            raise ValueError(f"Start must be before end: '{range_str}'")
    return start, end

def parse_day_cell(cell_val) -> List[Tuple[time, time]]:
    """
    Parse a day cell which may contain multiple ranges separated by ';' or ','.
    Returns list of (start, end) time tuples.
    """
    if pd.isna(cell_val) or str(cell_val).strip() == "":
        return []
    text = str(cell_val).strip()
    # split by ; or , but not inside AM/PM (safe heuristic)
    chunks = re.split(r"[;,]", text)
    ranges = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ranges.append(_parse_single_range(chunk))
        except Exception:
            # propagate error so the row/day is listed in the UI
            raise
    return ranges

# ----------------------------- Conflict Logic -----------------------------

def times_overlap(a: Tuple[time, time], b: Tuple[time, time]) -> bool:
    a_start, a_end = a
    b_start, b_end = b
    return a_start < b_end and b_start < a_end

def classes_conflict(meetings_a: Dict[str, List[Tuple[time, time]]],
                     meetings_b: Dict[str, List[Tuple[time, time]]]) -> bool:
    for day in DAYS:
        a_slots = meetings_a.get(day, [])
        b_slots = meetings_b.get(day, [])
        if not a_slots or not b_slots:
            continue
        for sa in a_slots:
            for sb in b_slots:
                if times_overlap(sa, sb):
                    return True
    return False

# ----------------------------- Streamlit App -----------------------------

st.set_page_config(page_title="Class Picker (Up to Four Non-Conflicting)", page_icon="📚", layout="wide")
st.title("📚 Class Picker — Choose up to Four Non-Conflicting Classes")

st.markdown(
    """
Upload your Excel file with these columns:
- **Course**, **Number**, **Instructor**
- **Monday** … **Friday** (cells contain `start-end` time ranges; multiple ranges allowed using `;` or `,`)

**Flow:** Select a class → conflicting classes disappear → repeat up to 4 selections.
"""
)

uploaded = st.file_uploader("Upload Excel (.xlsx or .xls)", type=["xlsx", "xls"])

def _reset_selections():
    for key in ["sel1", "sel2", "sel3", "sel4"]:
        if key in st.session_state:
            del st.session_state[key]
    if "__previous_label_map" in st.session_state:
        del st.session_state["__previous_label_map"]

st.button("🔄 Reset selections", on_click=_reset_selections)

if not uploaded:
    st.info("Upload an Excel file to begin.")
    st.stop()

# Read Excel
try:
    df = pd.read_excel(uploaded)
except Exception as e:
    st.error(f"Could not read Excel: {e}")
    st.stop()

# Normalize and validate columns
original_cols = df.columns.tolist()
norm_map = {c: c.strip() for c in original_cols}
df.rename(columns=norm_map, inplace=True)

lower_cols = {c.lower(): c for c in df.columns}
required = ["course", "number", "instructor"]
missing = [c for c in required if c not in lower_cols]
if missing:
    st.error(f"Missing required column(s): {', '.join(missing)}")
    st.stop()

# Map day columns case-insensitively
day_cols = {}
for k, v in lower_cols.items():
    if k in DAY_ALIASES:
        day_cols[DAY_ALIASES[k]] = v

missing_days = [d for d in DAYS if d not in day_cols]
if missing_days:
    st.error(f"Missing day column(s): {', '.join(missing_days)}")
    st.stop()

# Clean core columns
course_col = lower_cols["course"]
number_col = lower_cols["number"]
instr_col = lower_cols["instructor"]

# Ensure types are strings
df[course_col] = df[course_col].astype(str).fillna("")
df[number_col] = df[number_col].astype(str).fillna("")
df[instr_col] = df[instr_col].astype(str).fillna("")

# Build meetings per row
parse_errors: List[str] = []
meetings_by_id: Dict[int, Dict[str, List[Tuple[time, time]]]] = {}
labels_by_id: Dict[int, str] = {}

def format_meetings_short(meetings: Dict[str, List[Tuple[time, time]]]) -> str:
    parts = []
    for day in DAYS:
        slots = meetings.get(day, [])
        if slots:
            segs = [f"{s.strftime('%-I:%M %p')}-{e.strftime('%-I:%M %p')}" for s, e in slots]
            parts.append(f"{day[:3]} " + ", ".join(segs))
    return " | ".join(parts) if parts else "No times"

for idx, row in df.iterrows():
    class_id = idx  # stable per file load
    per_day = {}
    row_error = []
    for day in DAYS:
        cell = row[day_cols[day]]
        try:
            per_day[day] = parse_day_cell(cell)
        except Exception as e:
            row_error.append(f"{day}: {e}")
            per_day[day] = []
    meetings_by_id[class_id] = per_day
    label = f"[{class_id}] {row[course_col]} ({row[number_col]}) — {row[instr_col]} — {format_meetings_short(per_day)}"
    labels_by_id[class_id] = label
    if row_error:
        parse_errors.append(f"Row {idx}: " + "; ".join(row_error))

if parse_errors:
    with st.expander("⚠️ Time parsing issues detected (click to view)"):
        for err in parse_errors:
            st.markdown(f"- {err}")

# Conflict map: precompute for fast filtering
all_ids = list(df.index)
conflict_map: Dict[int, Set[int]] = {i: set() for i in all_ids}
for i in all_ids:
    for j in all_ids:
        if i >= j:
            continue
        if classes_conflict(meetings_by_id[i], meetings_by_id[j]):
            conflict_map[i].add(j)
            conflict_map[j].add(i)

# Helpers to compute availability
def remaining_after(selected_ids: List[int]) -> Set[int]:
    remaining = set(all_ids) - set(selected_ids)
    for sid in selected_ids:
        remaining -= conflict_map[sid]
    return remaining

def options_for(selected_ids: List[int]) -> List[int]:
    # Available options for the next pick (excluding already selected)
    return sorted(list(remaining_after(selected_ids)))

def make_label_map(ids: List[int]) -> Dict[str, int]:
    return {"— None —": -1, **{labels_by_id[i]: i for i in ids}}

def enforce_choice(key: str, valid_labels: List[str]):
    """Ensure the saved selection still exists; if not, reset to None."""
    if key in st.session_state:
        val = st.session_state[key]
        if val not in valid_labels:
            st.session_state[key] = "— None —"
    else:
        st.session_state[key] = "— None —"

# UI layout
left, right = st.columns([2, 3])

with left:
    st.subheader("Step-by-step Selection")
    st.caption("Pick up to four classes. After each pick, conflicting classes are removed from the next list.")

    # 1st selection
    opt1_ids = options_for([])
    map1 = make_label_map(opt1_ids)
    labels1 = list(map1.keys())
    enforce_choice("sel1", labels1)
    sel1_label = st.selectbox("Select class #1", labels1, key="sel1")
    sel1_id = map1[sel1_label]

    # 2nd selection
    sel_list1 = [i for i in [sel1_id] if i != -1]
    opt2_ids = options_for(sel_list1)
    map2 = make_label_map([i for i in opt2_ids if i not in sel_list1])
    labels2 = list(map2.keys())
    enforce_choice("sel2", labels2)
    sel2_label = st.selectbox("Select class #2", labels2, key="sel2")
    sel2_id = map2[sel2_label]

    # 3rd selection
    sel_list2 = [i for i in [sel1_id, sel2_id] if i != -1]
    opt3_ids = options_for(sel_list2)
    map3 = make_label_map([i for i in opt3_ids if i not in sel_list2])
    labels3 = list(map3.keys())
    enforce_choice("sel3", labels3)
    sel3_label = st.selectbox("Select class #3", labels3, key="sel3")
    sel3_id = map3[sel3_label]

    # 4th selection
    sel_list3 = [i for i in [sel1_id, sel2_id, sel3_id] if i != -1]
    opt4_ids = options_for(sel_list3)
    map4 = make_label_map([i for i in opt4_ids if i not in sel_list3])
    labels4 = list(map4.keys())
    enforce_choice("sel4", labels4)
    sel4_label = st.selectbox("Select class #4", labels4, key="sel4")
    sel4_id = map4[sel4_label]

    selected_ids = [i for i in [sel1_id, sel2_id, sel3_id, sel4_id] if i != -1]
    st.markdown("---")
    st.markdown(f"**Selected {len(selected_ids)} / 4**")
    if selected_ids:
        chosen_df = df.loc[selected_ids, [course_col, number_col, instr_col] + [day_cols[d] for d in DAYS]].copy()
        chosen_df.insert(0, "ClassID", chosen_df.index)
        st.dataframe(chosen_df, use_container_width=True)
        # Download chosen
        csv = chosen_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download chosen classes (CSV)", data=csv, file_name="chosen_classes.csv", mime="text/csv")
    else:
        st.caption("No classes selected yet.")

with right:
    st.subheader("Available (No Conflicts with Current Selections)")
    remaining_ids = sorted(list(remaining_after(selected_ids)))
    remaining_df = df.loc[remaining_ids, [course_col, number_col, instr_col] + [day_cols[d] for d in DAYS]].copy()
    remaining_df.insert(0, "ClassID", remaining_df.index)
    st.dataframe(remaining_df, use_container_width=True)

st.markdown("---")
with st.expander("How conflicts are detected"):
    st.write(
        "Two classes conflict if they meet on the same day **and** any of their time intervals overlap. "
        "For example, 9:00–10:15 and 10:00–11:00 overlap on the shared day."
    )
