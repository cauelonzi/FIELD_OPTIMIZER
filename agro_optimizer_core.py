import geopandas as gpd
import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString

# ======================================================
# PARÂMETROS DE PESO (TUNÁVEIS)
# ======================================================
PESO_MANOBRA = 60           # penaliza muitas passadas
PESO_LINHA_CURTA = 220      # penaliza linhas muito curtas
MIN_LINE_RATIO = 0.75       # % mínima do espaçamento aceitável


# ======================================================
# GERA LINHAS PARALELAS (EM SISTEMA ROTACIONADO)
# ======================================================
def generate_parallel_lines(polygon, spacing, offset_fraction=0.0):
    minx, miny, maxx, maxy = polygon.bounds

    x = minx + spacing * offset_fraction
    lines = []

    while x <= maxx:
        lines.append(
            LineString([
                (x, miny - 5000),
                (x, maxy + 5000)
            ])
        )
        x += spacing

    return lines


# ======================================================
# AVALIA UM ÂNGULO ESPECÍFICO
# ======================================================
def evaluate_angle(polygon, spacing, angle):
    poly_rot = rotate(polygon, -angle, origin="centroid")

    best_score = float("inf")
    best_lines = []

    for offset_fraction in [0.0, 0.25, 0.5, 0.75]:
        lines = generate_parallel_lines(poly_rot, spacing, offset_fraction)

        total_length = 0
        valid_lines = []
        short_count = 0

        for line in lines:
            inter = line.intersection(poly_rot)

            if inter.is_empty:
                continue

            if inter.length < spacing * MIN_LINE_RATIO:
                short_count += 1
                continue

            total_length += inter.length
            valid_lines.append(inter)

        if not valid_lines:
            continue

        score = (
            total_length
            + len(valid_lines) * PESO_MANOBRA
            + short_count * PESO_LINHA_CURTA
        )

        if score < best_score:
            best_score = score
            best_lines = valid_lines

    return best_score, best_lines


# ======================================================
# BUSCA GLOBAL DO MELHOR ÂNGULO
# ======================================================
def find_best_angle(polygon, spacing, step=1):
    best = None

    for angle in np.arange(0, 180, step):
        score, lines = evaluate_angle(polygon, spacing, angle)

        if not lines:
            continue

        passes = len(lines)

        if (
            best is None
            or passes < best["passes"]
            or (passes == best["passes"] and score < best["score"])
        ):
            best = {
                "angle": angle,
                "lines": lines,
                "passes": passes,
                "score": score,
            }

    if best is None:
        raise ValueError("Nenhuma solução válida encontrada")

    return best["angle"], best["lines"]


# ======================================================
# ROTACIONA LINHAS DE VOLTA AO SISTEMA ORIGINAL
# ======================================================
def rotate_back(lines, angle, polygon):
    return [
        rotate(line, angle, origin=polygon.centroid)
        for line in lines
    ]


# ======================================================
# FUNÇÃO PÚBLICA (USADA PELO APP)
# ======================================================
def optimize_from_geometry(polygon, implement_width, border_passes):
    """
    polygon          : shapely Polygon (lat/lon)
    implement_width  : largura do implemento (metros)
    border_passes    : número de passadas de bordadura
    """

    # -----------------------------
    # Projeção para UTM
    # -----------------------------
    gdf = gpd.GeoDataFrame(geometry=[polygon], crs="EPSG:4326")
    gdf = gdf.to_crs(gdf.estimate_utm_crs())

    polygon_utm = gdf.geometry.iloc[0]
    crs = gdf.crs

    # -----------------------------
    # Bordadura
    # -----------------------------
    offset = implement_width * border_passes
    inner = polygon_utm.buffer(-offset)

    if inner.is_empty or not inner.is_valid:
        raise ValueError("Bordadura eliminou o talhão")

    # -----------------------------
    # Otimização angular
    # -----------------------------
    angle, lines = find_best_angle(inner, implement_width)

    final_lines = rotate_back(lines, angle, inner)

    # -----------------------------
    # GeoDataFrames finais
    # -----------------------------
    gdf_lines = gpd.GeoDataFrame(geometry=final_lines, crs=crs)
    gdf_outer = gpd.GeoDataFrame(geometry=[polygon_utm], crs=crs)
    gdf_inner = gpd.GeoDataFrame(geometry=[inner], crs=crs)

    return (
        angle,
        len(final_lines),
        gdf_lines,
        gdf_outer,
        gdf_inner
    )

