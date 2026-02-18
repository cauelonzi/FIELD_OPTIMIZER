import streamlit as st
import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import shape
from shapely.affinity import rotate
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
import tempfile
import os

import agro_optimizer_core as optimizer

# =====================================================
# CONFIG
# =====================================================
st.set_page_config(layout="wide")
st.title("🚜 Otimizador de Linhas de Plantio — Engenharia & ROI")

# =====================================================
# PALETA JOHN DEERE
# =====================================================
JD_GREEN = "#367C2B"     # Linhas atuais
JD_YELLOW = "#FFDE00"   # Linhas otimizadas
JD_DARK = "#1F2A1F"     # Contorno talhão
JD_RED = "#C0392B"      # Bordadura

# =====================================================
# SESSION STATE
# =====================================================
if "polygon" not in st.session_state:
    st.session_state.polygon = None
if "optimized" not in st.session_state:
    st.session_state.optimized = False

# =====================================================
# SIDEBAR — ENTRADA
# =====================================================
st.sidebar.header("📥 Entrada do Talhão")

input_mode = st.sidebar.radio(
    "Como deseja inserir o talhão?",
    ["Desenhar no mapa", "Enviar arquivo (KML / GeoJSON)"]
)

if st.sidebar.button("🆕 Novo Talhão"):
    st.session_state.clear()
    st.rerun()

# =====================================================
# SIDEBAR — PARÂMETROS
# =====================================================
st.sidebar.header("⚙️ Parâmetros Geométricos")

implement_width = float(st.sidebar.text_input("Largura do implemento (m)", "7.0"))
border_passes = int(st.sidebar.text_input("Passadas de bordadura", "0"))

# =====================================================
# ENTRADA DO TALHÃO
# =====================================================
polygon = None

if input_mode == "Desenhar no mapa":

    st.subheader("🗺️ Desenhe o talhão")

    m = folium.Map(
        location=[-15, -50],
        zoom_start=16,
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery"
    )

    Draw(draw_options={
        "polyline": False,
        "rectangle": False,
        "circle": False,
        "marker": False,
        "circlemarker": False
    }).add_to(m)

    map_data = st_folium(m, height=500, width=900)

    if map_data and map_data.get("all_drawings"):
        polygon = shape(map_data["all_drawings"][0]["geometry"])

else:
    uploaded = st.file_uploader("Envie o arquivo do talhão", type=["kml", "geojson"])
    if uploaded:
        suffix = os.path.splitext(uploaded.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.read())
            path = tmp.name
        gdf = gpd.read_file(path)
        polygon = gdf.geometry.iloc[0]

# =====================================================
# ETAPA 1 — ENGENHARIA
# =====================================================
if polygon is not None:

    st.success("✅ Talhão carregado")

    if st.button("🔧 Calcular Melhor Ângulo") and not st.session_state.optimized:

        angle_opt, passes_opt, gdf_lines_opt, gdf_outer, gdf_inner = (
            optimizer.optimize_from_geometry(
                polygon, implement_width, border_passes
            )
        )

        st.session_state.update({
            "optimized": True,
            "angle_opt": angle_opt,
            "ab_angle": angle_opt % 180,
            "passes_opt": passes_opt,
            "maneuvers_opt": passes_opt - 1,
            "distance_opt": gdf_lines_opt.length.sum() / 1000,
            "gdf_lines_opt": gdf_lines_opt,
            "gdf_outer": gdf_outer,
            "gdf_inner": gdf_inner
        })

# =====================================================
# RESULTADOS — ENGENHARIA
# =====================================================
if st.session_state.optimized:

    st.subheader("🧭 Etapa 1 — Melhor Ângulo de Plantio")

    c1, c2, c3 = st.columns(3)
    c1.metric("Ângulo geométrico", f"{st.session_state.angle_opt:.2f}°")
    c2.metric("Ângulo AB", f"{st.session_state.ab_angle:.2f}°")
    c3.metric("Passadas", st.session_state.passes_opt)

    st.metric("Manobras", st.session_state.maneuvers_opt)
    st.metric("Distância total", f"{st.session_state.distance_opt:.2f} km")

    fig, ax = plt.subplots(figsize=(8, 8))

    st.session_state.gdf_outer.plot(
        ax=ax,
        facecolor="none",
        edgecolor=JD_DARK,
        linewidth=2.2,
        zorder=1
    )

    if border_passes > 0:
        st.session_state.gdf_inner.plot(
            ax=ax,
            facecolor="none",
            edgecolor=JD_RED,
            linestyle="--",
            linewidth=1.4,
            zorder=2
        )

    st.session_state.gdf_lines_opt.plot(
        ax=ax,
        color=JD_YELLOW,
        linewidth=1.3,
        zorder=3,
        label="Otimizado"
    )

    ax.legend()
    ax.axis("off")
    st.pyplot(fig)

# =====================================================
# ETAPA 2 — OPERAÇÃO + ROI
# =====================================================
if st.session_state.optimized:

    st.subheader("💰 Etapa 2 — Comparação Operacional")

    col1, col2 = st.columns(2)

    with col1:
        angle_user = float(st.text_input("Ângulo AB atual (°)", "90"))
        maneuver_time_sec = float(st.text_input("Tempo médio de manobra (s)", "30"))

    with col2:
        speed_kmh = float(st.text_input("Velocidade média (km/h)", "6"))
        consumption_lh = float(st.text_input("Consumo médio (L/h)", "18"))
        diesel_price = float(st.text_input("Preço do diesel (R$/L)", "6.00"))

    def gerar_linhas(polygon, angle):
        gdf = gpd.GeoDataFrame(geometry=[polygon], crs="EPSG:4326")
        gdf = gdf.to_crs(gdf.estimate_utm_crs())
        poly = gdf.geometry.iloc[0]

        inner = poly.buffer(-implement_width * border_passes)
        rot = rotate(inner, -angle, origin="centroid")

        lines = optimizer.generate_parallel_lines(rot, implement_width)
        valid = [l.intersection(rot) for l in lines if not l.intersection(rot).is_empty]
        final = optimizer.rotate_back(valid, angle, inner)

        return gpd.GeoDataFrame(geometry=final, crs=gdf.crs)

    if st.button("📊 Comparar Cenários"):

        gdf_user = gerar_linhas(polygon, angle_user)

        dist_user = gdf_user.length.sum() / 1000
        maneuver_h = maneuver_time_sec / 3600

        time_user = (dist_user / speed_kmh) + (len(gdf_user) - 1) * maneuver_h
        time_opt = (st.session_state.distance_opt / speed_kmh) + st.session_state.maneuvers_opt * maneuver_h

        cost_user = time_user * consumption_lh * diesel_price
        cost_opt = time_opt * consumption_lh * diesel_price

        st.metric("💰 Economia estimada", f"R$ {cost_user - cost_opt:,.2f}")

        fig, ax = plt.subplots(figsize=(8, 8))

        st.session_state.gdf_outer.plot(ax=ax, facecolor="none", edgecolor=JD_DARK, linewidth=2)
        st.session_state.gdf_inner.plot(ax=ax, facecolor="none", edgecolor=JD_RED, linestyle="--")

        gdf_user.plot(ax=ax, color=JD_GREEN, linewidth=1.2, label="Atual", zorder=2)
        st.session_state.gdf_lines_opt.plot(ax=ax, color=JD_YELLOW, linewidth=1.3, label="Otimizado", zorder=3)

        ax.legend()
        ax.axis("off")
        st.pyplot(fig)


