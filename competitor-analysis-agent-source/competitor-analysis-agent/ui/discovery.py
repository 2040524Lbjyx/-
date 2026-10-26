"""Candidate discovery and explicit confirmation, before the analysis workflow."""
import logging
import os
import streamlit as st
from services.competitor_discovery import CompetitorDiscovery


def render_discovery(product_name="", market="", target_users=""):
    website = st.text_input("产品网址（与业务描述至少填写一项）", placeholder="https://notion.so", key="discovery_website", max_chars=500)
    description = st.text_area("业务描述", placeholder="例如：为中小团队提供文档、知识库和项目协作", key="discovery_description", max_chars=2000)
    with st.expander("搜索配置（可选）"):
        exa_key = st.text_input("Exa API Key", value=os.getenv("EXA_API_KEY", ""), type="password", key="discovery_exa_key",
                                help="填写后使用 Exa 搜索，按其账户计费。留空使用公开搜索；也可在 .env 中配置 EXA_API_KEY。")
        st.caption("公开搜索可能遇到验证码或无结果。Exa Key 仅用于搜索，与模型 API Key 不同。")
    st.caption("根据公开搜索资料推荐候选，匹配理由为 AI 判断，请确认后再分析。竞品发现会联网并使用当前模型；侧栏演示模式仅影响后续分析。")
    profile = (website.strip(), description.strip(), product_name.strip(), market.strip(), target_users.strip())
    # Invalidate results before their widgets are created, including on a new search.
    if st.session_state.get("discovery_profile") != profile:
        st.session_state.discovery_profile = profile
        st.session_state.discovery_candidates = []
        st.session_state.discovery_confirmed = []
        st.session_state.pop("discovery_selection", None)
    has_key = bool(os.getenv("OPENAI_API_KEY"))
    if not has_key:
        st.info("请在侧栏配置模型 API Key 后发现竞品，也可以切换到“我已知道竞品”手动输入。")
    if st.button("搜索竞品候选", key="discover_competitors", disabled=not has_key or not (website.strip() or description.strip())):
        st.session_state.discovery_candidates = []
        st.session_state.discovery_confirmed = []
        st.session_state.pop("discovery_selection", None)
        try:
            with st.spinner("正在搜索并整理竞品候选…"):
                st.session_state.discovery_candidates = CompetitorDiscovery(exa_api_key=exa_key).discover(
                    website, description, product_name=product_name, market=market, target_users=target_users)
        except ValueError as exc:
            st.warning(str(exc))
        except Exception:
            logging.getLogger(__name__).exception("Competitor discovery failed")
            st.error("竞品发现暂时不可用，请稍后重试或手动输入竞品。")
    candidates = st.session_state.get("discovery_candidates", [])
    if not candidates:
        return []
    for candidate in candidates:
        with st.expander(candidate["name"], expanded=True):
            st.write("匹配理由：", candidate["reason"])
            for source in candidate["sources"]:
                st.link_button(source["title"] or "查看参考来源", source["url"])
                if source.get("snippet"):
                    st.caption(source["snippet"])
    names = [candidate["name"] for candidate in candidates]
    selected = st.multiselect("选择 2～5 个竞品", names, key="discovery_selection", max_selections=5)
    if st.session_state.get("discovery_confirmed") != selected:
        st.session_state.discovery_confirmed = []
    if len(names) < 2:
        st.info("当前有来源的候选不足两个，请补充业务描述重新搜索，或切换到手动输入。")
    if st.button("确认竞品，准备分析", key="confirm_discovery", disabled=not 2 <= len(selected) <= 5):
        st.session_state.discovery_confirmed = list(selected)
    if st.session_state.get("discovery_confirmed"):
        st.success("已确认：" + "、".join(selected) + "。点击下方“开始分析”继续。")
        return [candidate for candidate in candidates if candidate["name"] in selected]
    return []
