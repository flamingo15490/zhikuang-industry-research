from interaction import metal_key_from_selection, comparison_trace_names, format_radar_details, format_peer_ranking


def test_metal_selection_resolves_chinese_label_and_plotly_payload():
    assert metal_key_from_selection("黄金") == "gold"
    assert metal_key_from_selection({"label": "铜", "customdata": "copper"}) == "copper"


def test_unknown_or_other_slice_does_not_trigger_matrix_link():
    assert metal_key_from_selection("其他") is None
    assert metal_key_from_selection({"label": "未知"}) is None


def test_comparison_traces_have_distinct_legend_targets():
    assert comparison_trace_names("紫金矿业", "贵金属") == [
        "紫金矿业",
        "贵金属均值",
    ]


def test_radar_details_include_rank_composite_and_all_dimension_scores():
    text = format_radar_details("紫金矿业", "黄金", 4, 13,
                                {"基本面": 90, "估值": 75, "技术面": 60, "资金面": 40, "安全度": 85})
    assert "紫金矿业" in text
    assert "4 / 13" in text
    assert "综合分" in text
    assert "基本面 90" in text
    assert "安全度 85" in text


def test_peer_ranking_is_sorted_and_contains_composite_scores():
    text = format_peer_ranking("黄金", [("A", 88.4), ("B", 71.2)])
    assert "黄金排名" in text
    assert "1. A" in text and "88" in text
    assert "2. B" in text and "71" in text
