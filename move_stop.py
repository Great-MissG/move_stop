import os

import requests
import streamlit as st


ROUTE_ITEMS_URL = "https://isp.beans.ai/enterprise/v1/lists/routes/{route_id}/items"
MOVE_ITEM_URL = "https://isp.beans.ai/enterprise/v1/lists/items/{item_id}"
WAREHOUSE_RECEIVED = "WAREHOUSE_RECEIVED"


def init_state() -> None:
    st.session_state.setdefault("stops", [])
    st.session_state.setdefault("selected_item_ids", [])
    st.session_state.setdefault("last_source_route_id", "")


def get_api_token() -> str:
    return os.environ.get("BEANS_API_TOKEN", "").strip()


def normalize_authorization_value(token: str) -> str:
    normalized = token.strip()
    lower_token = normalized.lower()
    if lower_token.startswith("bearer ") or lower_token.startswith("basic "):
        return normalized
    return f"Bearer {normalized}"


def build_headers(token: str) -> dict:
    return {
        "Authorization": normalize_authorization_value(token),
        "Content-Type": "application/json",
    }


def extract_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        data = None

    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            value = data.get(key)
            if value:
                return str(value)
    return f"HTTP {response.status_code}: {response.text.strip() or 'Request failed'}"


def normalize_secondary_status(stop: dict) -> str:
    status = stop.get("secondaryStatus") or ""
    return str(status).strip()


def get_tracking_id(stop: dict) -> str:
    for key in ("trackingId", "trackingID", "tracking_id"):
        value = stop.get(key)
        if value:
            return str(value)
    return "N/A"


def is_stop_like(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    stop_keys = {
        "listItemId",
        "trackingId",
        "trackingID",
        "tracking_id",
        "secondaryStatus",
    }
    return any(key in item for key in stop_keys)


def collect_stop_like_items(data: object) -> list[dict]:
    matches: list[dict] = []
    if isinstance(data, dict):
        if is_stop_like(data):
            matches.append(data)
        for value in data.values():
            matches.extend(collect_stop_like_items(value))
    elif isinstance(data, list):
        for item in data:
            matches.extend(collect_stop_like_items(item))
    return matches


def extract_items_from_response(data: object) -> list[dict]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    direct_item = data.get("item")
    if isinstance(direct_item, list):
        return [item for item in direct_item if isinstance(item, dict)]
    if isinstance(direct_item, dict):
        nested_matches = collect_stop_like_items(direct_item)
        return nested_matches or [direct_item]

    candidate_paths = (
        ("item",),
        ("items",),
        ("data",),
        ("results",),
        ("routeItems",),
        ("listItems",),
        ("data", "item"),
        ("data", "items"),
        ("data", "results"),
        ("result", "item"),
        ("result", "items"),
    )

    for path in candidate_paths:
        current = data
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, list):
            return [item for item in current if isinstance(item, dict)]
        if isinstance(current, dict):
            nested_matches = collect_stop_like_items(current)
            return nested_matches or [current]

    return collect_stop_like_items(data)


def fetch_route_stops(route_id: str, token: str) -> list[dict]:
    response = requests.get(
        ROUTE_ITEMS_URL.format(route_id=route_id),
        headers=build_headers(token),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return extract_items_from_response(data)


def move_stop_to_route(item_id: str, target_route_id: str, token: str) -> None:
    payload = {
        "listItemId": item_id,
        "route": {
            "listRouteId": target_route_id,
        },
    }
    response = requests.patch(
        MOVE_ITEM_URL.format(item_id=item_id),
        headers=build_headers(token),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()


def filter_visible_stops(stops: list[dict]) -> list[dict]:
    filtered = []
    for stop in stops:
        status = normalize_secondary_status(stop)
        if not status or status.upper() != WAREHOUSE_RECEIVED:
            filtered.append(stop)
    return filtered


def reset_selection(valid_ids: set[str]) -> None:
    st.session_state.selected_item_ids = [
        item_id for item_id in st.session_state.selected_item_ids if item_id in valid_ids
    ]


def render_stop_table(stops: list[dict]) -> None:
    st.subheader("Stops")
    select_all_col, unselect_all_col, spacer_col = st.columns([1, 1, 4])
    with select_all_col:
        if st.button("Select All", use_container_width=True):
            st.session_state.selected_item_ids = [
                str(stop["listItemId"]) for stop in stops if stop.get("listItemId")
            ]
    with unselect_all_col:
        if st.button("Unselect All", use_container_width=True):
            st.session_state.selected_item_ids = []
    with spacer_col:
        st.caption(
            f"Filtered stops: {len(stops)} | Selected stops: {len(st.session_state.selected_item_ids)}"
        )

    header_cols = st.columns([2, 2, 1])
    header_cols[0].markdown("**Tracking ID**")
    header_cols[1].markdown("**Secondary Status**")
    header_cols[2].markdown("**Selected**")

    selected_ids = set(st.session_state.selected_item_ids)
    updated_selection = set()

    for index, stop in enumerate(stops):
        item_id = str(stop["listItemId"]) if stop.get("listItemId") else ""
        row_cols = st.columns([2, 2, 1])
        row_cols[0].write(get_tracking_id(stop))
        row_cols[1].write(normalize_secondary_status(stop) or "-")
        checked = row_cols[2].checkbox(
            "Select",
            value=bool(item_id and item_id in selected_ids),
            key=f"select_{item_id or 'missing'}_{index}",
            disabled=not item_id,
            label_visibility="collapsed",
        )
        if checked and item_id:
            updated_selection.add(item_id)

    st.session_state.selected_item_ids = [
        str(stop["listItemId"])
        for stop in stops
        if stop.get("listItemId") and str(stop["listItemId"]) in updated_selection
    ]


def main() -> None:
    st.set_page_config(page_title="Move Beans Stops", layout="wide")
    init_state()

    st.title("Move Stops Between Beans Routes")
    st.write("Fetch route stops, select the stops you want, and move them to another route.")

    source_route_id = st.text_input(
        "Source Route ID",
        value=st.session_state.last_source_route_id,
        placeholder="Enter source route ID",
    ).strip()

    if st.button("Fetch Stops", type="primary"):
        token = get_api_token()
        if not token:
            st.error("Missing environment variable BEANS_API_TOKEN.")
        elif not source_route_id:
            st.warning("Source Route ID is required.")
        else:
            with st.spinner("Fetching route stops..."):
                try:
                    fetched_stops = fetch_route_stops(source_route_id, token)
                except requests.RequestException as exc:
                    response = getattr(exc, "response", None)
                    if response is not None:
                        st.error(f"Failed to fetch stops: {extract_error_message(response)}")
                    else:
                        st.error(f"Failed to fetch stops: {exc}")
                else:
                    visible_stops = filter_visible_stops(fetched_stops)
                    st.session_state.stops = visible_stops
                    st.session_state.selected_item_ids = []
                    st.session_state.last_source_route_id = source_route_id
                    if visible_stops:
                        st.success(f"Loaded {len(visible_stops)} stop(s).")
                    else:
                        st.warning("No eligible stops found for this route.")

    visible_stops = st.session_state.stops
    valid_ids = {str(stop["listItemId"]) for stop in visible_stops if stop.get("listItemId")}
    reset_selection(valid_ids)

    if visible_stops:
        render_stop_table(visible_stops)
    else:
        st.info("No stops loaded yet.")

    target_route_id = st.text_input("Target Route ID", placeholder="Enter target route ID").strip()

    if st.button("Move Selected Stops", type="primary"):
        token = get_api_token()
        selected_ids = list(st.session_state.selected_item_ids)

        if not token:
            st.error("Missing environment variable BEANS_API_TOKEN.")
        elif not source_route_id:
            st.warning("Source Route ID is required.")
        elif not target_route_id:
            st.warning("Target Route ID is required.")
        elif not selected_ids:
            st.warning("Select at least one stop to move.")
        else:
            tracking_by_item_id = {
                str(stop["listItemId"]): get_tracking_id(stop)
                for stop in st.session_state.stops
                if stop.get("listItemId")
            }
            success_ids = []
            failures = []

            with st.spinner("Moving selected stops..."):
                for item_id in selected_ids:
                    try:
                        move_stop_to_route(item_id, target_route_id, token)
                    except requests.RequestException as exc:
                        response = getattr(exc, "response", None)
                        if response is not None:
                            message = extract_error_message(response)
                        else:
                            message = str(exc)
                        failures.append((tracking_by_item_id.get(item_id, "N/A"), message))
                    else:
                        success_ids.append(item_id)

            if success_ids:
                st.session_state.stops = [
                    stop
                    for stop in st.session_state.stops
                    if str(stop.get("listItemId")) not in set(success_ids)
                ]
                st.session_state.selected_item_ids = [
                    item_id for item_id in st.session_state.selected_item_ids if item_id not in set(success_ids)
                ]
                st.success(f"Moved {len(success_ids)} stop(s) successfully.")

            if failures:
                st.warning(f"Failed to move {len(failures)} stop(s).")
                for tracking_id, message in failures:
                    st.error(f"{tracking_id}: {message}")

            if not success_ids and not failures:
                st.warning("No stops were processed.")


if __name__ == "__main__":
    main()
