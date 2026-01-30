import json
import time
from typing import Any, Dict, List, Tuple

import pandas as pd
import requests
import streamlit as st

import extruct
from w3lib.html import get_base_url


def safe_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def fetch_html(url: str, timeout: int = 25) -> Tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url


def normalize_items(extracted: Dict[str, Any]) -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = {}
    for k in ["json-ld", "microdata", "rdfa"]:
        v = extracted.get(k) or []
        if not isinstance(v, list):
            v = [v]
        out[k] = v
    return out


def guess_item_type(item: Any) -> str:
    if isinstance(item, dict):
        t = item.get("@type") or item.get("type")
        if isinstance(t, list):
            return ",".join(str(x) for x in t)
        if t:
            return str(t)
    return ""


def flatten_item(prefix: str, value: Any, rows: List[Dict[str, str]]):
    if isinstance(value, dict):
        for k, v in value.items():
            flatten_item(f"{prefix}.{k}" if prefix else k, v, rows)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            flatten_item(f"{prefix}[{i}]", v, rows)
    else:
        rows.append(
            {
                "property": prefix,
                "value": "" if value is None else str(value),
            }
        )


def extract_structured_data(url: str, timeout: int):
    html, final_url = fetch_html(url, timeout)
    base_url = get_base_url(html, final_url)

    extracted = extruct.extract(
        html,
        base_url=base_url,
        syntaxes=["json-ld", "microdata", "rdfa"],
        uniform=True,
    )

    items_by_syntax = normalize_items(extracted)

    flat_rows: List[Dict[str, str]] = []
    for syntax, items in items_by_syntax.items():
        for idx, item in enumerate(items):
            item_type = guess_item_type(item)
            tmp: List[Dict[str, str]] = []
            flatten_item("", item, tmp)
            for t in tmp:
                flat_rows.append(
                    {
                        "url": final_url,
                        "syntax": syntax,
                        "item_index": idx,
                        "item_type": item_type,
                        "property": t["property"],
                        "value": t["value"],
                    }
                )

    return {
        "url": final_url,
        "json": safe_json(items_by_syntax),
        "flat": flat_rows,
    }


st.set_page_config(page_title="Structured Data Extractor", layout="wide")

st.title("Structured Data Extractor")
st.caption("Extract JSON-LD, Microdata, and RDFa from a list of URLs.")

urls_input = st.text_area(
    "Enter URLs (one per line)",
    height=250,
)

timeout = st.number_input("Request timeout (seconds)", 5, 120, 25)
delay = st.number_input("Delay between requests (seconds)", 0.0, 10.0, 0.0)
run = st.button("Run extraction", type="primary")

if run:
    urls = [u.strip() for u in urls_input.splitlines() if u.strip()]
    if not urls:
        st.error("No URLs provided")
        st.stop()

    all_rows = []
    per_url_rows = []

    progress = st.progress(0)

    for i, url in enumerate(urls, start=1):
        try:
            result = extract_structured_data(url, int(timeout))
            per_url_rows.append(
                {
                    "url": result["url"],
                    "structured_data_json": result["json"],
                }
            )
            all_rows.extend(result["flat"])
        except Exception as e:
            all_rows.append(
                {
                    "url": url,
                    "syntax": "",
                    "item_index": "",
                    "item_type": "",
                    "property": "ERROR",
                    "value": str(e),
                }
            )

        if delay > 0:
            time.sleep(delay)

        progress.progress(i / len(urls))

    df_per_url = pd.DataFrame(per_url_rows)
    df_flat = pd.DataFrame(all_rows)

    st.subheader("Preview")
    st.dataframe(df_flat.head(50), use_container_width=True)

    from io import BytesIO

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_per_url.to_excel(writer, index=False, sheet_name="per_url_json")
        df_flat.to_excel(writer, index=False, sheet_name="flat_properties")

    st.download_button(
        "Download Excel",
        data=buffer.getvalue(),
        file_name="structured_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
