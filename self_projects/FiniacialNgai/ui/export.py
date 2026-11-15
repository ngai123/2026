"""Shared JSON export helper — renders a download button for any page."""
import json
from datetime import datetime

import streamlit as st


def _serialise(obj):
    """Fallback serialiser for types json.dumps can't handle natively."""
    if hasattr(obj, "isoformat"):          # datetime / date
        return obj.isoformat()
    if hasattr(obj, "to_dict"):            # pandas DataFrame
        return obj.to_dict(orient="records")
    if hasattr(obj, "tolist"):             # numpy array
        return obj.tolist()
    return str(obj)


def export_button(data: dict, prefix: str, label: str = "Export JSON") -> None:
    """
    Render a compact download button that exports *data* as pretty-printed JSON.

    Parameters
    ----------
    data    : dict of page data — price_history Series and DataFrames are
              auto-converted; anything else falls back to str().
    prefix  : used in the filename, e.g. "dashboard" → "dashboard_20260430_1430.json"
    label   : button text (default "Export JSON")
    """
    payload = {
        "exported_at": datetime.now().isoformat(),
        **data,
    }
    json_bytes = json.dumps(payload, indent=2, default=_serialise).encode("utf-8")
    filename   = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"

    st.download_button(
        label=label,
        data=json_bytes,
        file_name=filename,
        mime="application/json",
        key=f"_export_{prefix}",
    )
