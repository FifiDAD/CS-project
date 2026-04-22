"""Local fallback for streamlit-autorefresh.

This keeps the app launchable in environments where the third-party package
isn't installed. It mimics the small piece of API this project uses.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def st_autorefresh(interval: int = 0, limit: int | None = None, key: str = "autorefresh") -> int:
    """Trigger a browser refresh on a timer and return the refresh count."""
    state_key = f"__autorefresh_count_{key}"
    count = int(st.session_state.get(state_key, 0))

    if interval > 0 and (limit is None or count < limit):
        st.session_state[state_key] = count + 1
        components.html(
            f"""
            <script>
                window.setTimeout(function() {{
                    window.parent.location.reload();
                }}, {int(interval)});
            </script>
            """,
            height=0,
            width=0,
        )

    return count
